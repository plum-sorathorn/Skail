from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from skail.domain.events import BudgetPayload, EventEnvelope, RoutePayload
from skail.domain.ids import (
    AttemptId,
    InvocationId,
    RunId,
    SessionId,
    TaskId,
    new_assignment_id,
    new_event_id,
    new_reservation_id,
)
from skail.domain.routing import TaskAssignment
from skail.domain.usage import NormalizedUsage, UsageAuthority
from skail.providers.base import ProviderAdapter
from skail.providers.fallback import FallbackBinding
from skail.routing.budget import BudgetLedger, ReservationRequest
from skail.routing.requirements import RoutingRequirements
from skail.routing.selector import RouteCandidate, RouteFailure, RouteSelection, select_model
from skail.sessions.journal import Journal


class AssignmentRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: SessionId
    run_id: RunId
    task_id: TaskId
    attempt_id: AttemptId
    attempt_number: Literal[1, 2]
    catalog_revision: str = Field(min_length=1)
    requirements: RoutingRequirements
    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    task_limit_usd: Decimal | None = None
    manual_model: tuple[str, str] | None = None
    fallback_of_assignment_id: str | None = None


class BatchAssignmentResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    assignments: tuple[TaskAssignment, ...]
    deferred_task_ids: tuple[TaskId, ...]
    lead_reservation_id: str | None = None


class RoutingSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    catalog_revision: str = Field(min_length=1)
    config_revision: str = Field(min_length=1)
    health_revision: str = Field(min_length=1)
    candidates: tuple[RouteCandidate, ...]


class StaleRoutingSnapshot(RuntimeError):
    pass


class AssignmentService:
    def __init__(
        self,
        journal: Journal,
        ledger: BudgetLedger,
        *,
        event_observer: Callable[[EventEnvelope], None] | None = None,
        invocation_id: InvocationId | None = None,
        snapshot_is_current: Callable[[RoutingSnapshot], bool] | None = None,
        max_snapshot_retries: int = 2,
    ) -> None:
        self.journal = journal
        self.ledger = ledger
        self.event_observer = event_observer
        self.invocation_id = invocation_id
        self.snapshot_is_current = snapshot_is_current or (lambda snapshot: True)
        self.max_snapshot_retries = max_snapshot_retries

    def assign(
        self,
        request: AssignmentRequest,
        candidates: Callable[[], RoutingSnapshot],
    ) -> TaskAssignment | RouteFailure:
        for attempt in range(self.max_snapshot_retries + 1):
            try:
                return self._assign_once(request, candidates)
            except StaleRoutingSnapshot:
                if attempt == self.max_snapshot_retries:
                    raise
        raise AssertionError("bounded assignment retry loop did not terminate")

    def _assign_once(
        self,
        request: AssignmentRequest,
        candidates: Callable[[], RoutingSnapshot],
    ) -> TaskAssignment | RouteFailure:
        with self.journal.transaction() as transaction:
            self._validate_ownership(transaction, request)
            decision_key = self._decision_key(request)
            existing = self._existing_assignment(transaction, decision_key)
            if existing is not None:
                return existing
            fallback_source = (
                None
                if request.fallback_of_assignment_id is None
                else self._fallback_source(transaction, request)
            )
            budget = self.ledger._snapshot(transaction.connection, str(request.run_id))
            available = budget.available_usd
            if (
                available is not None
                and fallback_source is not None
                and fallback_source[3] == "reserved"
            ):
                available += fallback_source[2]
            if request.task_limit_usd is not None:
                task_available = request.task_limit_usd - self.ledger.task_committed_usd(
                    transaction.connection,
                    str(request.run_id),
                    str(request.task_id),
                )
                if fallback_source is not None and fallback_source[3] == "reserved":
                    task_available += fallback_source[2]
                available = task_available if available is None else min(available, task_available)
            routing_snapshot = candidates()
            if not self.snapshot_is_current(routing_snapshot):
                raise StaleRoutingSnapshot("routing inputs changed before commit")
            if routing_snapshot.catalog_revision != request.catalog_revision:
                raise StaleRoutingSnapshot("catalog revision changed during assignment")
            if routing_snapshot.config_revision != config_revision(request.config_snapshot):
                raise StaleRoutingSnapshot("config revision changed during assignment")
            candidate_snapshot = routing_snapshot.candidates
            selection = select_model(
                candidate_snapshot,
                request.requirements,
                available_budget_usd=available,
                manual_model=request.manual_model,
            )
            if isinstance(selection, RouteFailure):
                return selection
            if selection.candidate.estimated_cost_usd is None:
                return RouteFailure(
                    excluded_counts={"price_unavailable_for_reservation": 1},
                    binding_constraint="price_unavailable_for_reservation",
                )
            if (
                fallback_source is not None
                and selection.candidate.profile.model != fallback_source[0]
            ):
                return RouteFailure(
                    excluded_counts={"fallback_model_mismatch": 1},
                    binding_constraint="fallback_model_mismatch",
                )
            if fallback_source is not None:
                self._release_fallback_source(transaction, request, fallback_source)
            return self._persist(
                transaction,
                request,
                selection,
                budget,
                candidate_snapshot,
                decision_key,
                routing_snapshot.health_revision,
            )

    def assign_and_construct(
        self,
        request: AssignmentRequest,
        candidates: Callable[[], RoutingSnapshot],
        construct: Callable[[TaskAssignment], Any],
    ) -> tuple[TaskAssignment | RouteFailure, Any | None]:
        assignment = self.assign(request, candidates)
        if isinstance(assignment, RouteFailure):
            return assignment, None
        return assignment, construct(assignment)

    def assign_batch(
        self,
        requests: tuple[AssignmentRequest, ...],
        candidates: Callable[[AssignmentRequest], RoutingSnapshot],
        *,
        lead_allowance_usd: Decimal,
    ) -> BatchAssignmentResult:
        if not requests:
            return BatchAssignmentResult(assignments=(), deferred_task_ids=())
        with self.journal.transaction() as transaction:
            run_id = str(requests[0].run_id)
            if any(str(request.run_id) != run_id for request in requests):
                raise ValueError("one batch cannot span runs")
            for request in requests:
                self._validate_ownership(transaction, request)
            batch_key = "assignment-batch:" + ":".join(
                str(request.attempt_id) for request in requests
            )
            replay = transaction.connection.execute(
                "SELECT payload_json FROM assignment_batches WHERE idempotency_key=?",
                (batch_key,),
            ).fetchone()
            if replay is not None:
                return BatchAssignmentResult.model_validate_json(replay["payload_json"])
            budget = self.ledger._snapshot(transaction.connection, run_id)
            remaining = budget.available_usd
            if remaining is not None:
                remaining -= lead_allowance_usd
            selections: list[
                tuple[AssignmentRequest, RouteSelection, tuple[RouteCandidate, ...], str]
            ] = []
            deferred: list[TaskId] = []
            for request in requests:
                routing_snapshot = candidates(request)
                if routing_snapshot.catalog_revision != request.catalog_revision:
                    raise ValueError("catalog revision changed during batch assignment")
                if routing_snapshot.config_revision != config_revision(request.config_snapshot):
                    raise ValueError("config revision changed during batch assignment")
                candidate_snapshot = routing_snapshot.candidates
                request_available = remaining
                if request.task_limit_usd is not None:
                    task_available = request.task_limit_usd - self.ledger.task_committed_usd(
                        transaction.connection,
                        run_id,
                        str(request.task_id),
                    )
                    request_available = (
                        task_available
                        if request_available is None
                        else min(request_available, task_available)
                    )
                selection = select_model(
                    candidate_snapshot,
                    request.requirements,
                    available_budget_usd=request_available,
                    manual_model=request.manual_model,
                )
                if isinstance(selection, RouteFailure):
                    deferred.append(request.task_id)
                    continue
                if selection.candidate.estimated_cost_usd is None:
                    deferred.append(request.task_id)
                    continue
                selections.append(
                    (request, selection, candidate_snapshot, routing_snapshot.health_revision)
                )
                if remaining is not None:
                    assert selection.candidate.estimated_cost_usd is not None
                    remaining -= selection.candidate.estimated_cost_usd
            if not selections:
                return BatchAssignmentResult(
                    assignments=(), deferred_task_ids=tuple(request.task_id for request in requests)
                )
            lead_reservation_id = str(new_reservation_id())
            self.ledger.reserve_in_transaction(
                transaction,
                ReservationRequest(
                    reservation_id=lead_reservation_id,
                    run_id=run_id,
                    task_id=None,
                    amount_usd=lead_allowance_usd,
                    idempotency_key=f"batch-lead:{lead_reservation_id}",
                    purpose="lead_continuation",
                ),
            )
            assignments = tuple(
                self._persist(
                    transaction,
                    request,
                    selection,
                    self.ledger._snapshot(transaction.connection, run_id),
                    candidate_snapshot,
                    self._decision_key(request),
                    health_revision,
                )
                for request, selection, candidate_snapshot, health_revision in selections
            )
            result = BatchAssignmentResult(
                assignments=assignments,
                deferred_task_ids=tuple(deferred),
                lead_reservation_id=lead_reservation_id,
            )
            transaction.connection.execute(
                "INSERT INTO assignment_batches VALUES (?,?,?)",
                (batch_key, result.model_dump_json(), datetime.now(UTC).isoformat()),
            )
            return result

    def _persist(
        self,
        transaction: Any,
        request: AssignmentRequest,
        selection: RouteSelection,
        budget: Any,
        candidate_snapshot: tuple[RouteCandidate, ...],
        decision_key: str,
        health_revision: str,
    ) -> TaskAssignment:
        candidate = selection.candidate
        assert candidate.estimated_cost_usd is not None
        assignment_id = new_assignment_id()
        reservation_id = new_reservation_id()
        reservation = self.ledger.reserve_in_transaction(
            transaction,
            ReservationRequest(
                reservation_id=str(reservation_id),
                run_id=str(request.run_id),
                task_id=str(request.task_id),
                amount_usd=candidate.estimated_cost_usd,
                idempotency_key=f"assignment-reservation:{assignment_id}",
            ),
            task_limit_usd=request.task_limit_usd,
        )
        explanation = (
            *selection.ranking_reasons,
            f"binding_constraint={selection.binding_constraint or 'none'}",
            f"included={selection.included_count}",
            *(f"excluded.{key}={value}" for key, value in selection.excluded_counts.items()),
        )
        assignment = TaskAssignment(
            assignment_id=assignment_id,
            task_id=request.task_id,
            attempt_number=request.attempt_number,
            provider=candidate.profile.provider,
            model=candidate.profile.model,
            routing_mode=request.requirements.mode,
            capability_floor=request.requirements.capability_floor,
            estimated_attempt_cost_usd=candidate.estimated_cost_usd,
            reservation_id=reservation_id,
            explanation=explanation,
            catalog_revision=request.catalog_revision,
        )
        payload = {
            **assignment.model_dump(mode="json"),
            "attempt_id": str(request.attempt_id),
            "requirements": request.requirements.model_dump(mode="json"),
            "config": request.config_snapshot,
            "budget": budget.model_dump(mode="json"),
            "health_revision": health_revision,
            "routing_inputs": [
                {
                    "provider": item.profile.provider,
                    "model": item.profile.model,
                    "configured": item.configured,
                    "healthy": item.healthy,
                    "enabled": item.enabled,
                    "estimated_cost_usd": (
                        None
                        if item.estimated_cost_usd is None
                        else format(item.estimated_cost_usd, "f")
                    ),
                    "estimate_assumptions": item.estimate_assumptions,
                }
                for item in candidate_snapshot
            ],
            "fallback_of_assignment_id": request.fallback_of_assignment_id,
        }
        now = datetime.now(UTC)
        transaction.create_assignment(
            assignment_id=str(assignment.assignment_id),
            attempt_id=str(request.attempt_id),
            provider=assignment.provider,
            model=assignment.model,
            estimated_cost_usd=assignment.estimated_attempt_cost_usd,
            idempotency_key=decision_key,
            payload=payload,
            created_at=now,
        )
        sequence = transaction.connection.execute(
            "SELECT COALESCE(MAX(sequence),0) FROM events WHERE run_id=?", (str(request.run_id),)
        ).fetchone()[0]
        events: list[tuple[str, BudgetPayload | RoutePayload]] = [
            (
                "budget.reserved",
                BudgetPayload(
                    action="reserved",
                    amount_usd=assignment.estimated_attempt_cost_usd,
                ),
            )
        ]
        if reservation.warning_crossed:
            events.append(
                (
                    "budget.warned",
                    BudgetPayload(
                        action="warned",
                        amount_usd=assignment.estimated_attempt_cost_usd,
                    ),
                )
            )
        events.append(
            (
                "route.fallback" if request.fallback_of_assignment_id else "route.selected",
                RoutePayload(
                    action="fallback" if request.fallback_of_assignment_id else "selected",
                    assignment_id=str(assignment.assignment_id),
                ),
            )
        )
        for offset, (event_type, event_payload) in enumerate(
            events,
            start=1,
        ):
            event = EventEnvelope(
                event_id=new_event_id(),
                session_id=request.session_id,
                run_id=request.run_id,
                invocation_id=self.invocation_id,
                task_id=request.task_id,
                attempt_id=request.attempt_id,
                sequence=sequence + offset,
                occurred_at=now,
                type=event_type,
                payload=event_payload,
            )
            transaction.append_event(event)
            if self.event_observer is not None:
                transaction.after_commit(lambda event=event: self.event_observer(event))
        return assignment

    @staticmethod
    def _decision_key(request: AssignmentRequest) -> str:
        if request.fallback_of_assignment_id is None:
            return f"assignment:attempt:{request.attempt_id}:primary"
        return (
            f"assignment:attempt:{request.attempt_id}:fallback:{request.fallback_of_assignment_id}"
        )

    @staticmethod
    def _existing_assignment(transaction: Any, decision_key: str) -> TaskAssignment | None:
        row = transaction.connection.execute(
            "SELECT payload_json FROM assignments WHERE idempotency_key=?",
            (decision_key,),
        ).fetchone()
        if row is None:
            return None
        return TaskAssignment.model_validate(json.loads(row["payload_json"]))

    @staticmethod
    def _validate_ownership(transaction: Any, request: AssignmentRequest) -> None:
        row = transaction.connection.execute(
            "SELECT a.attempt_number,t.task_id,t.run_id,r.session_id "
            "FROM attempts a JOIN tasks t ON t.task_id=a.task_id "
            "JOIN runs r ON r.run_id=t.run_id WHERE a.attempt_id=?",
            (str(request.attempt_id),),
        ).fetchone()
        expected = (
            request.attempt_number,
            str(request.task_id),
            str(request.run_id),
            str(request.session_id),
        )
        if row is None or tuple(row) != expected:
            raise ValueError("assignment identifiers do not describe one persisted attempt")

    @staticmethod
    def _fallback_source(
        transaction: Any, request: AssignmentRequest
    ) -> tuple[str, str, Decimal, str]:
        row = transaction.connection.execute(
            "SELECT attempt_id,model,payload_json FROM assignments WHERE assignment_id=?",
            (request.fallback_of_assignment_id,),
        ).fetchone()
        if row is None or row["attempt_id"] != str(request.attempt_id):
            raise ValueError("fallback source must belong to the same persisted attempt")
        reservation_id = json.loads(row["payload_json"])["reservation_id"]
        reservation = transaction.connection.execute(
            "SELECT status,amount_usd FROM budget_reservations WHERE reservation_id=?",
            (reservation_id,),
        ).fetchone()
        if reservation is None:
            raise ValueError("fallback source reservation is missing")
        return (
            row["model"],
            reservation_id,
            Decimal(reservation["amount_usd"]),
            reservation["status"],
        )

    def _release_fallback_source(
        self,
        transaction: Any,
        request: AssignmentRequest,
        source: tuple[str, str, Decimal, str],
    ) -> None:
        _, reservation_id, amount_usd, status = source
        if status == "reserved":
            transaction.connection.execute(
                "UPDATE budget_reservations SET status='released',updated_at=? "
                "WHERE reservation_id=?",
                (datetime.now(UTC).isoformat(), reservation_id),
            )
            self.ledger._update_warning(transaction.connection, str(request.run_id))
            sequence = transaction.connection.execute(
                "SELECT COALESCE(MAX(sequence),0) FROM events WHERE run_id=?",
                (str(request.run_id),),
            ).fetchone()[0]
            event = EventEnvelope(
                event_id=new_event_id(),
                session_id=request.session_id,
                run_id=request.run_id,
                invocation_id=self.invocation_id,
                task_id=request.task_id,
                attempt_id=request.attempt_id,
                sequence=sequence + 1,
                occurred_at=datetime.now(UTC),
                type="budget.released",
                payload=BudgetPayload(
                    action="released",
                    amount_usd=amount_usd,
                ),
            )
            transaction.append_event(event)
            if self.event_observer is not None:
                transaction.after_commit(lambda: self.event_observer(event))


def config_revision(snapshot: dict[str, Any]) -> str:
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


class AccountingReconciliationRequired(RuntimeError):
    pass


class AssignmentUsageSettler:
    def __init__(
        self,
        journal: Journal,
        ledger: BudgetLedger,
        providers: dict[str, ProviderAdapter],
    ) -> None:
        self.journal = journal
        self.ledger = ledger
        self.providers = dict(providers)

    def begin_call(self, assignment_id: str, execution_key: str | None = None) -> str:
        now = datetime.now(UTC).isoformat()
        with self.journal.transaction() as transaction:
            assignment = transaction.connection.execute(
                "SELECT a.attempt_id,a.payload_json,t.run_id "
                "FROM assignments a JOIN attempts p ON p.attempt_id=a.attempt_id "
                "JOIN tasks t ON t.task_id=p.task_id WHERE a.assignment_id=?",
                (assignment_id,),
            ).fetchone()
            if assignment is None:
                raise KeyError(assignment_id)
            execution_key = execution_key or f"new:{uuid4()}"
            replay = transaction.connection.execute(
                "SELECT call_id,status FROM provider_calls "
                "WHERE assignment_id=? AND execution_key=?",
                (assignment_id, execution_key),
            ).fetchone()
            if replay is not None:
                raise AccountingReconciliationRequired(
                    f"provider call replay is blocked ({replay['status']})"
                )
            uncertain = transaction.connection.execute(
                "SELECT 1 FROM accounting_reconciliation_failures f "
                "JOIN assignments a ON a.assignment_id=f.assignment_id "
                "JOIN attempts p ON p.attempt_id=a.attempt_id "
                "JOIN tasks t ON t.task_id=p.task_id "
                "WHERE t.run_id=? AND f.status='open' LIMIT 1",
                (assignment["run_id"],),
            ).fetchone()
            if uncertain is not None:
                raise AccountingReconciliationRequired(
                    "paid execution is blocked pending usage reconciliation"
                )
            budget = transaction.connection.execute(
                "SELECT budget_limit_usd FROM runs WHERE run_id=?",
                (assignment["run_id"],),
            ).fetchone()
            observed_rows = transaction.connection.execute(
                "SELECT c.amount_usd FROM provider_calls c "
                "JOIN assignments a ON a.assignment_id=c.assignment_id "
                "JOIN attempts p ON p.attempt_id=a.attempt_id "
                "JOIN tasks t ON t.task_id=p.task_id "
                "WHERE t.run_id=? AND c.status='completed' AND c.amount_usd IS NOT NULL",
                (assignment["run_id"],),
            ).fetchall()
            observed_cost = sum(
                (Decimal(row["amount_usd"]) for row in observed_rows), Decimal("0")
            )
            if (
                budget is not None
                and budget["budget_limit_usd"] is not None
                and observed_cost >= Decimal(budget["budget_limit_usd"])
            ):
                raise AccountingReconciliationRequired(
                    "paid execution is blocked because observed cost exhausted the budget"
                )
            payload = json.loads(assignment["payload_json"])
            reservation = transaction.connection.execute(
                "SELECT status FROM budget_reservations WHERE reservation_id=?",
                (payload["reservation_id"],),
            ).fetchone()
            if reservation is None or reservation["status"] != "reserved":
                raise AccountingReconciliationRequired(
                    "provider call has no active funded reservation"
                )
            ordinal = transaction.connection.execute(
                "SELECT COALESCE(MAX(ordinal),0)+1 FROM provider_calls "
                "WHERE assignment_id=?",
                (assignment_id,),
            ).fetchone()[0]
            call_id = str(uuid4())
            transaction.connection.execute(
                "INSERT INTO provider_calls "
                "(call_id,assignment_id,attempt_id,execution_key,ordinal,status,"
                "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    call_id,
                    assignment_id,
                    assignment["attempt_id"],
                    execution_key,
                    ordinal,
                    "started",
                    now,
                    now,
                ),
            )
        return call_id

    def mark_ambiguous(self, call_id: str, error: Exception) -> None:
        now = datetime.now(UTC).isoformat()
        summary = str(error) or type(error).__name__
        with self.journal.transaction() as transaction:
            row = transaction.connection.execute(
                "SELECT assignment_id,status FROM provider_calls WHERE call_id=?", (call_id,)
            ).fetchone()
            if row is None:
                raise KeyError(call_id)
            if row["status"] == "completed":
                return
            transaction.connection.execute(
                "UPDATE provider_calls SET status='ambiguous',error_summary=?,updated_at=? "
                "WHERE call_id=?",
                (summary, now, call_id),
            )
            transaction.connection.execute(
                "INSERT OR IGNORE INTO accounting_reconciliation_failures "
                "(failure_id,assignment_id,call_id,status,summary,created_at) "
                "VALUES (?,?,?,?,?,?)",
                (str(uuid4()), row["assignment_id"], call_id, "open", summary, now),
            )

    @staticmethod
    def _normalize_response(
        adapter: ProviderAdapter, response: object
    ) -> NormalizedUsage | None:
        messages = getattr(response, "result", None)
        values = messages if isinstance(messages, list) else [response]
        normalized = [adapter.normalize_usage(value) for value in values]
        observed = [value for value in normalized if value is not None]
        if not observed:
            return None
        return NormalizedUsage(
            input_tokens=sum(value.input_tokens for value in observed),
            output_tokens=sum(value.output_tokens for value in observed),
            cost_usd=sum((value.cost_usd for value in observed), Decimal("0")),
            authority=(
                UsageAuthority.AUTHORITATIVE_ACTUAL
                if len(observed) == len(values)
                and all(
                    value.authority is UsageAuthority.AUTHORITATIVE_ACTUAL
                    for value in observed
                )
                else UsageAuthority.ESTIMATED_ACTUAL
            ),
        )

    def record_call(self, assignment_id: str, response: object, *, call_id: str) -> None:
        with self.journal._connect() as connection:
            row = connection.execute(
                "SELECT provider,payload_json FROM assignments WHERE assignment_id=?",
                (assignment_id,),
            ).fetchone()
        if row is None:
            raise KeyError(assignment_id)
        adapter = self.providers[row["provider"]]
        usage = self._normalize_response(adapter, response)
        if usage is None:
            usage_unknown = True
            usage = NormalizedUsage(
                input_tokens=0,
                output_tokens=0,
                cost_usd=Decimal("0"),
                authority=UsageAuthority.ESTIMATED_ACTUAL,
            )
        else:
            usage_unknown = False
        values = (
            assignment_id,
            call_id,
            usage.input_tokens,
            usage.output_tokens,
            format(usage.cost_usd, "f"),
            int(usage.authority is UsageAuthority.AUTHORITATIVE_ACTUAL),
        )
        with self.journal.transaction() as transaction:
            existing = transaction.connection.execute(
                "SELECT assignment_id,call_id,input_tokens,output_tokens,amount_usd,"
                "authoritative FROM assignment_call_usage "
                "WHERE assignment_id=? AND call_id=?",
                (assignment_id, call_id),
            ).fetchone()
            if existing is not None:
                if tuple(existing) != values:
                    raise ValueError("model call usage replay conflicts")
                return
            transaction.connection.execute(
                "INSERT INTO assignment_call_usage VALUES (?,?,?,?,?,?)", values
            )
            now = datetime.now(UTC).isoformat()
            call = transaction.connection.execute(
                "SELECT status FROM provider_calls WHERE call_id=?", (call_id,)
            ).fetchone()
            if call is not None:
                transaction.connection.execute(
                    "UPDATE provider_calls SET status='completed',input_tokens=?,"
                    "output_tokens=?,amount_usd=?,authority=?,updated_at=? WHERE call_id=?",
                    (
                        usage.input_tokens,
                        usage.output_tokens,
                        None if usage_unknown else format(usage.cost_usd, "f"),
                        "unknown" if usage_unknown else usage.authority.value,
                        now,
                        call_id,
                    ),
                )

    def settle_attempt(self, assignment_id: str) -> None:
        with self.journal._connect() as connection:
            assignment = connection.execute(
                "SELECT payload_json FROM assignments WHERE assignment_id=?",
                (assignment_id,),
            ).fetchone()
            calls = connection.execute(
                "SELECT input_tokens,output_tokens,amount_usd,authoritative "
                "FROM assignment_call_usage WHERE assignment_id=? ORDER BY call_id",
                (assignment_id,),
            ).fetchall()
        if assignment is None:
            raise KeyError(assignment_id)
        payload = json.loads(assignment["payload_json"])
        all_authoritative = bool(calls) and all(row["authoritative"] for row in calls)
        recorded_cost = sum((Decimal(row["amount_usd"]) for row in calls), Decimal("0"))
        estimated_cost = Decimal(payload["estimated_attempt_cost_usd"])
        usage = NormalizedUsage(
            input_tokens=sum(row["input_tokens"] for row in calls),
            output_tokens=sum(row["output_tokens"] for row in calls),
            cost_usd=recorded_cost if all_authoritative else max(recorded_cost, estimated_cost),
            authority=(
                UsageAuthority.AUTHORITATIVE_ACTUAL
                if all_authoritative
                else UsageAuthority.ESTIMATED_ACTUAL
            ),
        )
        try:
            self.ledger.settle(
                payload["reservation_id"],
                usage_id=f"usage:{assignment_id}",
                usage=usage,
                idempotency_key=f"attempt-usage:{assignment_id}",
            )
        except Exception as error:
            with self.journal.transaction() as transaction:
                transaction.connection.execute(
                    "INSERT OR IGNORE INTO accounting_reconciliation_failures "
                    "(failure_id,assignment_id,call_id,status,summary,created_at) "
                    "VALUES (?,?,NULL,'open',?,?)",
                    (
                        str(uuid4()),
                        assignment_id,
                        str(error) or type(error).__name__,
                        datetime.now(UTC).isoformat(),
                    ),
                )
            raise AccountingReconciliationRequired(
                "usage settlement failed; paid execution is blocked"
            ) from error


class PersistedAssignmentRegistry:
    def __init__(self, journal: Journal) -> None:
        self.journal = journal

    def runtime_bindings(
        self,
    ) -> tuple[dict[str, str], dict[str, FallbackBinding]]:
        with self.journal._connect() as connection:
            rows = connection.execute(
                "SELECT assignment_id,attempt_id,provider,model,payload_json "
                "FROM assignments ORDER BY rowid"
            ).fetchall()
        assignments: dict[str, str] = {}
        active: dict[str, FallbackBinding] = {}
        for row in rows:
            payload = json.loads(row["payload_json"])
            model_key = f"{row['provider']}:{row['model']}"
            assignments[row["assignment_id"]] = model_key
            active[row["attempt_id"]] = FallbackBinding(
                assignment_id=row["assignment_id"],
                provider=row["provider"],
                model=row["model"],
                model_key=model_key,
                reservation_id=payload["reservation_id"],
            )
        return assignments, active
