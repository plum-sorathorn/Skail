from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fakes.models import ScriptedChatModel
from fakes.provider import FakeProviderAdapter
from langchain_core.messages import AIMessage

from rudder.domain.events import EventEnvelope
from rudder.domain.ids import AttemptId, RunId, SessionId, TaskId
from rudder.providers.models import CapabilityVector, ModelProfile
from rudder.routing.assignment import (
    AssignmentRequest,
    AssignmentService,
    AssignmentUsageSettler,
    PersistedAssignmentRegistry,
    RoutingSnapshot,
    config_revision,
)
from rudder.routing.budget import BudgetLedger
from rudder.routing.requirements import RequirementBuilder, TaskRisk
from rudder.routing.selector import RouteCandidate, RouteFailure
from rudder.runtime.errors import FrameworkContractError
from rudder.runtime.task_bound import build_persisted_task_subagent
from rudder.sessions import Journal

NOW = datetime(2026, 9, 2, tzinfo=UTC)
SESSION_ID = SessionId("11111111-1111-4111-8111-111111111111")
RUN_ID = RunId("22222222-2222-4222-8222-222222222222")
TASK_ID = TaskId("33333333-3333-4333-8333-333333333333")
ATTEMPT_ID = AttemptId("44444444-4444-4444-8444-444444444444")


def _service(tmp_path: Path, *, limit: str = "1.00") -> tuple[AssignmentService, Journal]:
    journal = Journal(tmp_path / "rudder.sqlite")
    journal.migrate()
    journal.create_session(session_id=SESSION_ID, title="assignment", created_at=NOW)
    journal.create_run(
        run_id=RUN_ID,
        session_id=SESSION_ID,
        status="running",
        budget_limit_usd=Decimal(limit),
        created_at=NOW,
    )
    journal.create_task(
        task_id=TASK_ID,
        run_id=RUN_ID,
        description="route",
        status="queued",
        idempotency_key="task",
        created_at=NOW,
    )
    journal.create_attempt(
        attempt_id=ATTEMPT_ID,
        task_id=TASK_ID,
        number=1,
        status="assigned",
        idempotency_key="attempt",
        created_at=NOW,
    )
    return AssignmentService(journal, BudgetLedger(journal)), journal


def _candidate(model: str = "model", cost: str = "0.20") -> RouteCandidate:
    return RouteCandidate(
        profile=ModelProfile(
            provider="fake",
            model=model,
            input_usd_per_million=Decimal("1"),
            output_usd_per_million=Decimal("2"),
            context_tokens=10_000,
            max_output_tokens=2_000,
            supports_tools=True,
            capability=CapabilityVector(
                coding=0.8, reasoning=0.8, tool_reliability=0.8, latency=0.5
            ),
            auto_eligible=True,
        ),
        estimated_cost_usd=Decimal(cost),
        estimate_assumptions=("expected_calls=2", "output_tokens=2000"),
    )


def _request() -> AssignmentRequest:
    return AssignmentRequest(
        session_id=SESSION_ID,
        run_id=RUN_ID,
        task_id=TASK_ID,
        attempt_id=ATTEMPT_ID,
        attempt_number=1,
        catalog_revision="catalog-v1",
        config_snapshot={"routing": {"mode": "auto"}},
        requirements=RequirementBuilder().build(role="implementer", risk=TaskRisk.ROUTINE),
    )


def _snapshot(*candidates: RouteCandidate) -> RoutingSnapshot:
    return RoutingSnapshot(
        catalog_revision="catalog-v1",
        config_revision=config_revision({"routing": {"mode": "auto"}}),
        health_revision="health-v1",
        candidates=tuple(candidates),
    )


def test_assignment_reservation_snapshot_and_events_commit_before_model_construction(
    tmp_path: Path,
) -> None:
    service, journal = _service(tmp_path)
    observed: list[str] = []

    def construct(assignment: object) -> object:
        snapshot = journal.get_session_snapshot(str(SESSION_ID))
        assert len(snapshot.assignments) == 1
        assert len(snapshot.budget_reservations) == 1
        assert [event.type for event in snapshot.events] == ["budget.reserved", "route.selected"]
        observed.append("constructed")
        return assignment

    result, model = service.assign_and_construct(
        _request(), lambda: _snapshot(_candidate()), construct
    )
    assert result.model == "model"
    assert model is result
    assert observed == ["constructed"]
    stored = journal.get_session_snapshot(str(SESSION_ID)).assignments[0]
    assert stored.payload["catalog_revision"] == "catalog-v1"
    assert stored.payload["config"] == {"routing": {"mode": "auto"}}
    assert stored.payload["budget"]["hard_limit_usd"] == "1.00"
    assert stored.payload["routing_inputs"][0]["estimate_assumptions"] == [
        "expected_calls=2",
        "output_tokens=2000",
    ]


def test_assignment_notifies_event_stream_only_after_journal_commit(tmp_path: Path) -> None:
    service, journal = _service(tmp_path)
    observed: list[str] = []

    def observe(event: EventEnvelope) -> None:
        persisted = journal.get_session_snapshot(str(SESSION_ID)).events
        assert any(item.event_id == event.event_id for item in persisted)
        observed.append(event.type)

    service = AssignmentService(journal, service.ledger, event_observer=observe)
    result = service.assign(_request(), lambda: _snapshot(_candidate()))
    assert not isinstance(result, RouteFailure)
    assert observed == ["budget.reserved", "route.selected"]


def test_assignment_retries_from_a_fresh_versioned_snapshot(tmp_path: Path) -> None:
    service, journal = _service(tmp_path)
    revisions = iter(("stale", "current"))
    service = AssignmentService(
        journal,
        service.ledger,
        snapshot_is_current=lambda snapshot: snapshot.health_revision == "current",
        max_snapshot_retries=1,
    )

    def snapshot() -> RoutingSnapshot:
        return _snapshot(_candidate()).model_copy(update={"health_revision": next(revisions)})

    result = service.assign(_request(), snapshot)
    assert not isinstance(result, RouteFailure)
    stored = journal.get_session_snapshot(str(SESSION_ID)).assignments[0]
    assert stored.payload["health_revision"] == "current"


def test_unfundable_route_persists_nothing_and_constructs_nothing(tmp_path: Path) -> None:
    service, journal = _service(tmp_path, limit="0.10")
    constructed = False

    def construct(_: object) -> object:
        nonlocal constructed
        constructed = True
        return object()

    result, model = service.assign_and_construct(
        _request(), lambda: _snapshot(_candidate()), construct
    )
    assert isinstance(result, RouteFailure)
    assert model is None
    assert constructed is False
    snapshot = journal.get_session_snapshot(str(SESSION_ID))
    assert snapshot.assignments == ()
    assert snapshot.budget_reservations == ()


def test_task_budget_block_is_a_structured_route_failure(tmp_path: Path) -> None:
    service, journal = _service(tmp_path)
    request = _request().model_copy(update={"task_limit_usd": Decimal("0.10")})
    result = service.assign(request, lambda: _snapshot(_candidate(cost="0.20")))
    assert isinstance(result, RouteFailure)
    assert result.binding_constraint == "budget_unaffordable"
    assert journal.get_session_snapshot(str(SESSION_ID)).assignments == ()


def test_batch_funds_ordered_affordable_subset_and_one_lead_allowance(tmp_path: Path) -> None:
    service, journal = _service(tmp_path)
    second_task = TaskId("55555555-5555-4555-8555-555555555555")
    second_attempt = AttemptId("66666666-6666-4666-8666-666666666666")
    journal.create_task(
        task_id=second_task,
        run_id=RUN_ID,
        description="second",
        status="queued",
        idempotency_key="task-2",
        created_at=NOW,
    )
    journal.create_attempt(
        attempt_id=second_attempt,
        task_id=second_task,
        number=1,
        status="assigned",
        idempotency_key="attempt-2",
        created_at=NOW,
    )
    second_request = _request().model_copy(
        update={"task_id": second_task, "attempt_id": second_attempt}
    )
    result = service.assign_batch(
        (_request(), second_request),
        lambda request: _snapshot(
            _candidate(
                str(request.task_id),
                "0.50" if request.task_id == TASK_ID else "0.40",
            )
        ),
        lead_allowance_usd=Decimal("0.25"),
    )
    assert [assignment.task_id for assignment in result.assignments] == [TASK_ID]
    assert result.deferred_task_ids == (second_task,)
    reservations = journal.get_session_snapshot(str(SESSION_ID)).budget_reservations
    assert [(item.task_id, item.amount_usd) for item in reservations] == [
        (None, Decimal("0.25")),
        (str(TASK_ID), Decimal("0.50")),
    ]


def test_transport_fallback_is_a_second_assignment_on_the_same_attempt(tmp_path: Path) -> None:
    service, journal = _service(tmp_path)
    limited_request = _request().model_copy(update={"task_limit_usd": Decimal("0.20")})
    original = service.assign(
        limited_request, lambda: _snapshot(_candidate("same-model", "0.20"))
    )
    assert not isinstance(original, RouteFailure)
    fallback_request = limited_request.model_copy(
        update={"fallback_of_assignment_id": str(original.assignment_id)}
    )
    fallback = service.assign(
        fallback_request,
        lambda: _snapshot(
            _candidate("same-model", "0.20").model_copy(
                update={
                    "profile": _candidate("same-model", "0.20").profile.model_copy(
                        update={"provider": "backup"}
                    )
                }
            )
        ),
    )
    assert not isinstance(fallback, RouteFailure)
    snapshot = journal.get_session_snapshot(str(SESSION_ID))
    assert len(snapshot.attempts) == 1
    assert [item.provider for item in snapshot.assignments] == ["fake", "backup"]
    assert snapshot.assignments[1].payload["fallback_of_assignment_id"] == str(
        original.assignment_id
    )
    assert [item.status for item in snapshot.budget_reservations] == [
        "released",
        "reserved",
    ]
    assert [event.type for event in snapshot.events if event.type.startswith("route.")] == [
        "route.selected",
        "route.fallback",
    ]
    assignments, active = PersistedAssignmentRegistry(journal).runtime_bindings()
    assert assignments[str(fallback.assignment_id)] == "backup:same-model"
    assert active[str(ATTEMPT_ID)].assignment_id == str(fallback.assignment_id)


def test_assignment_emits_warning_only_on_threshold_crossing(tmp_path: Path) -> None:
    service, journal = _service(tmp_path)
    result = service.assign(_request(), lambda: _snapshot(_candidate(cost="0.80")))
    assert not isinstance(result, RouteFailure)
    assert [event.type for event in journal.get_session_snapshot(str(SESSION_ID)).events] == [
        "budget.reserved",
        "budget.warned",
        "route.selected",
    ]


def test_assignment_replay_returns_persisted_decision_without_reserving_twice(
    tmp_path: Path,
) -> None:
    service, journal = _service(tmp_path)
    first = service.assign(_request(), lambda: _snapshot(_candidate()))
    replay = service.assign(
        _request(), lambda: (_ for _ in ()).throw(AssertionError("must not resnapshot"))
    )
    assert replay == first
    snapshot = journal.get_session_snapshot(str(SESSION_ID))
    assert len(snapshot.assignments) == 1
    assert len(snapshot.budget_reservations) == 1


def test_assignment_rejects_mixed_session_run_task_attempt_identity(tmp_path: Path) -> None:
    service, journal = _service(tmp_path)
    wrong_task = TaskId("77777777-7777-4777-8777-777777777777")
    with pytest.raises(ValueError, match="one persisted attempt"):
        service.assign(
            _request().model_copy(update={"task_id": wrong_task}),
            lambda: _snapshot(_candidate()),
        )
    assert journal.get_session_snapshot(str(SESSION_ID)).assignments == ()


def test_provider_usage_normalizes_and_settles_assignment_reservation_once(
    tmp_path: Path,
) -> None:
    service, journal = _service(tmp_path)
    assignment = service.assign(_request(), lambda: _snapshot(_candidate()))
    assert not isinstance(assignment, RouteFailure)
    adapter = FakeProviderAdapter()
    response = adapter.model.invoke("work")
    settler = AssignmentUsageSettler(journal, service.ledger, {"fake": adapter})
    settler.record_call(str(assignment.assignment_id), response, call_id="call-1")
    settler.record_call(str(assignment.assignment_id), response, call_id="call-1")
    settler.record_call(str(assignment.assignment_id), response, call_id="call-2")
    assert service.ledger.snapshot(str(RUN_ID)).reserved_usd == Decimal("0.20")
    settler.settle_attempt(str(assignment.assignment_id))
    settler.settle_attempt(str(assignment.assignment_id))
    snapshot = journal.get_session_snapshot(str(SESSION_ID))
    assert len(snapshot.usage_records) == 1
    assert snapshot.usage_records[0].amount_usd == adapter.model.cost_usd * 2
    assert snapshot.usage_records[0].authoritative is True
    assert snapshot.budget_reservations[0].status == "settled"


def test_compiled_runtime_rejects_assignment_not_loaded_from_journal(tmp_path: Path) -> None:
    service, journal = _service(tmp_path)
    assignment = service.assign(_request(), lambda: _snapshot(_candidate()))
    assert not isinstance(assignment, RouteFailure)
    fabricated = assignment.model_copy(
        update={"assignment_id": "99999999-9999-4999-8999-999999999999"}
    )
    with pytest.raises(FrameworkContractError) as caught:
        build_persisted_task_subagent(
            name="child",
            description="persisted only",
            attempt_id=str(ATTEMPT_ID),
            assignment=fabricated,
            registry=PersistedAssignmentRegistry(journal),
            models={"fake:model": ScriptedChatModel(responses=[AIMessage(content="unused")])},
        )
    assert caught.value.error.code == "route.assignment_not_persisted"
