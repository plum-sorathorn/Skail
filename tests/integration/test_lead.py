import asyncio
import hashlib
import logging
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fakes.models import ScriptedChatModel, parallel_tool_call_message, tool_call_message
from fakes.provider import FakeProviderAdapter
from langchain_core.messages import AIMessage

from skail.agents.lead import LeadControls
from skail.domain.events import SecretRedactor
from skail.domain.ids import new_session_id
from skail.providers.models import CapabilityVector, ModelProfile, ProviderSupportLevel
from skail.routing.assignment import (
    AccountingReconciliationRequired,
    RoutingSnapshot,
    config_revision,
)
from skail.routing.selector import RouteCandidate
from skail.runtime import run_controller as run_controller_module
from skail.runtime.failure_monitor import RunModelCallLimitExceeded
from skail.runtime.run_controller import RunController
from skail.sessions.journal import Journal


def _journal(tmp_path: Path) -> Journal:
    j = Journal(tmp_path / "journal.sqlite")
    j.migrate()
    return j


@pytest.mark.asyncio
async def test_lead_completes_direct_coding_flow_without_delegation(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Direct coding", created_at=datetime.now(UTC)
    )

    # Scripted lead model: writes a file directly using write_file tool
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        {
                            "mode": "direct",
                            "objective": "Write solution.py",
                            "constraints": [],
                            "reason": "The requested edit is bounded.",
                        },
                        "call-decision-1",
                    ),
                    (
                        "write_file",
                        {"file_path": "solution.py", "content": "def solve(): return 42\n"},
                        "call-write-1",
                    ),
                ]
            ),
            AIMessage(content="I have written solution.py successfully without delegating."),
        ],
    )

    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model},
        default_lead_model="lead-model",
    )

    result = await controller.run_instruction("Write solution.py")

    assert "solution.py" in (tmp_path / "solution.py").name
    assert (tmp_path / "solution.py").read_text(encoding="utf-8") == "def solve(): return 42\n"
    assert "written solution.py" in result.output
    assert result.lead_assignment.model == "lead-model"
    assert result.lead_assignment.attempt_number == 1
    assert result.lead_context_packet.task_id == str(result.run_id)


@pytest.mark.asyncio
async def test_no_qualified_lead_returns_actionable_result_without_calling_provider(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="No lead", created_at=datetime.now(UTC)
    )
    weak = ModelProfile(
        provider="fake",
        model="weak-lead",
        input_usd_per_million=Decimal("1"),
        output_usd_per_million=Decimal("2"),
        context_tokens=32_000,
        max_output_tokens=4_000,
        supports_tools=True,
        supports_structured_output=False,
        capability=CapabilityVector(
            coding=0.5, reasoning=0.5, tool_reliability=0.5, latency=0.5
        ),
        auto_eligible=True,
    )
    model = ScriptedChatModel(responses=[AIMessage(content="must not run")])
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"weak-lead": model},
        default_lead_model="weak-lead",
        candidates_fn=lambda: RoutingSnapshot(
            catalog_revision="catalog-v1",
            config_revision=config_revision({"routing": {"mode": "auto"}}),
            health_revision="health-v1",
            candidates=(
                RouteCandidate(
                    profile=weak,
                    estimated_cost_usd=Decimal("0.10"),
                ),
            ),
        ),
    )

    result = await controller.run_instruction("answer hi")

    assert result.status == "blocked"
    assert "No capable lead model is available" in result.output
    assert "Required capability floor" in result.output
    assert not model.calls


@pytest.mark.asyncio
async def test_planned_decision_is_persisted_before_the_lead_continues(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Planned decision", created_at=datetime.now(UTC)
    )
    plan = {
        "schema_version": 1,
        "policy_version": "adaptive-v1",
        "revision": 1,
        "nodes": [
            {
                "local_id": "inspect",
                "kind": "agent",
                "objective": "Inspect the requested files",
            }
        ],
    }
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={
            "lead-model": ScriptedChatModel(
                responses=[
                    tool_call_message(
                        "execution_decision",
                        {
                            "mode": "planned",
                            "objective": "Inspect before changing code",
                            "constraints": [],
                            "reason": "The work needs a recorded dependency graph.",
                            "plan": plan,
                        },
                        call_id="planned-decision-1",
                    ),
                    AIMessage(content="The plan is admitted and awaiting its coordinator."),
                ]
            )
        },
        default_lead_model="lead-model",
    )

    result = await controller.run_instruction("Inspect the project before changing code")

    admitted = journal.plans_for_run(str(result.run_id))
    assert len(admitted) == 1
    assert admitted[0].plan.nodes[0].local_id == "inspect"
    event_types = [event.type for event in journal.events_after(run_id=str(result.run_id))]
    assert event_types.index("plan.admitted") < event_types.index("tool.started")
    assert event_types.index("plan.node_admitted") < event_types.index("tool.completed")


@pytest.mark.asyncio
async def test_terminal_failure_event_observes_committed_failed_run(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Terminal failure", created_at=datetime.now(UTC)
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": ScriptedChatModel(responses=[])},
        default_lead_model="lead-model",
    )
    observed: list[tuple[str, str]] = []

    def observe(event) -> None:
        if event.type != "run.failed":
            return
        snapshot = journal.get_session_snapshot(str(session_id))
        observed.append((event.type, snapshot.runs[0].status))

    controller.subscribe_events(observe)

    with pytest.raises(AccountingReconciliationRequired):
        await controller.run_instruction("fail deterministically")

    assert observed == [("run.failed", "failed")]


@pytest.mark.asyncio
async def test_run_failed_event_and_log_carry_error_diagnostics(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Diagnostic failure", created_at=datetime.now(UTC)
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": ScriptedChatModel(responses=[])},
        default_lead_model="lead-model",
    )
    failed: list[object] = []
    observed: list[tuple[str, str]] = []

    def observe(event) -> None:
        if event.type != "run.failed":
            return
        snapshot = journal.get_session_snapshot(str(session_id))
        observed.append((event.type, snapshot.runs[0].status))
        failed.append(event.payload)

    controller.subscribe_events(observe)

    with (
        caplog.at_level(logging.ERROR, logger="skail.runtime.run_controller"),
        pytest.raises(AccountingReconciliationRequired) as excinfo,
    ):
        await controller.run_instruction("fail deterministically")

    exc = excinfo.value
    [payload] = failed
    assert observed == [("run.failed", "failed")]
    assert payload.status == "failed"
    assert payload.error_type == f"{type(exc).__module__}.{type(exc).__name__}"
    # The handler records the caught lead-invoke exception; finalization may replace
    # the propagated error, so the recorded message is verified against the log.
    assert payload.error_message == "provider outcome is ambiguous; paid execution is blocked"
    assert payload.error_message in caplog.text
    assert "AccountingReconciliationRequired" in caplog.text
    assert "Traceback (most recent call last)" in caplog.text


@pytest.mark.asyncio
async def test_cancelled_lead_does_not_log_framework_traceback(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Cancelled lead", created_at=datetime.now(UTC)
    )

    started = asyncio.Event()
    blocked = asyncio.Event()

    async def block(_: ScriptedChatModel, __) -> None:
        started.set()
        await blocked.wait()

    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={
            "lead-model": ScriptedChatModel(
                responses=[AIMessage(content="unused")],
                async_call_hook=block,
            )
        },
        default_lead_model="lead-model",
    )

    with caplog.at_level(logging.ERROR, logger="skail.runtime.run_controller"):
        run = asyncio.create_task(controller.run_instruction("cancel me"))
        await started.wait()
        run.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run

    assert "Traceback (most recent call last)" not in caplog.text
    snapshot = journal.get_session_snapshot(str(session_id))
    assert snapshot.runs[0].status == "cancelled"


@pytest.mark.asyncio
async def test_lead_delegates_to_implementer_and_synthesizes_result(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Delegated coding", created_at=datetime.now(UTC)
    )
    output_digest = hashlib.sha256(("hello from child" + os.linesep).encode()).hexdigest()

    # Scripted child model completes the work
    child_model = ScriptedChatModel(
        model_name="implementer-model",
        responses=[
            tool_call_message(
                "write_file",
                {"file_path": "child_output.txt", "content": "hello from child\n"},
                call_id="child-write-1",
            ),
            AIMessage(
                content=(
                    '{"status":"succeeded","summary":"Child finished writing",'
                    '"changed_paths":["child_output.txt"],"verification":[{'
                    '"criterion":"Provide evidence for the completed task",'
                    '"passed":true,"evidence":"child_output.txt digest",'
                    f'"evidence_ref":{{"kind":"file","path":"child_output.txt",'
                    f'"digest":"{output_digest}"}}}}]}}'
                )
            ),
        ],
    )

    # Lead model delegates to implementer, then synthesizes
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        {
                            "mode": "direct",
                            "objective": "Delegate one bounded file write",
                            "constraints": [],
                            "reason": "A single specialist can perform the work.",
                        },
                        "task-decision-1",
                    ),
                    (
                        "task",
                        {
                            "description": "Write child_output.txt file",
                            "subagent_type": "implementer",
                        },
                        "task-call-1",
                    ),
                ]
            ),
            AIMessage(content="Delegated task completed: child output created."),
        ],
    )

    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model, "implementer-model": child_model},
        default_lead_model="lead-model",
        default_child_model="implementer-model",
    )

    result = await controller.run_instruction("Delegate writing to implementer")

    assert (tmp_path / "child_output.txt").read_text(encoding="utf-8") == "hello from child\n"
    assert "Delegated task completed" in result.output
    assert len(result.child_results) == 1
    assert result.child_results[0].verification[0].evidence_ref is not None
    assert controller._validate_evidence_ref(
        result.child_results[0].verification[0].evidence_ref
    )
    assert result.child_results[0].status == "succeeded", result.child_results[0]
    child_assignment = next(
        assignment
        for assignment in journal.get_session_snapshot(str(session_id)).assignments
        if assignment.model == "implementer-model"
    )
    assumptions = child_assignment.payload["routing_inputs"][0]["estimate_assumptions"]
    assert "expected_calls=8" in assumptions
    assert "expected_calls_prior=profile:implementer" in assumptions
    assert "cache_assumption=no_cache_reuse" in assumptions


@pytest.mark.asyncio
async def test_controller_rejects_child_candidate_that_lacks_profile_tool_requirement(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Routing requirements", created_at=datetime.now(UTC)
    )
    child_model = ScriptedChatModel(
        model_name="implementer-model", responses=[AIMessage(content="must not run")]
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            tool_call_message(
                "task",
                {"description": "Write output", "subagent_type": "implementer"},
                call_id="task-tool-requirements",
            ),
            AIMessage(content="The child could not be routed."),
        ],
    )

    def candidate(model: str, *, tools: bool, auto_eligible: bool, cost: str) -> RouteCandidate:
        return RouteCandidate(
            profile=ModelProfile(
                provider="injected",
                model=model,
                support_level=ProviderSupportLevel.NATIVE,
                input_usd_per_million=Decimal("1"),
                output_usd_per_million=Decimal("2"),
                context_tokens=128_000,
                max_output_tokens=8_192,
                supports_tools=tools,
                supports_structured_output=True,
                capability=CapabilityVector(
                    coding=0.9, reasoning=0.9, tool_reliability=0.9, latency=0.1
                ),
                auto_eligible=auto_eligible,
                manual_selectable=True,
            ),
            estimated_cost_usd=Decimal(cost),
        )

    routing_snapshot = RoutingSnapshot(
        catalog_revision="catalog-v1",
        config_revision=config_revision({"routing": {"mode": "auto"}}),
        health_revision="healthy",
        candidates=(
            candidate("lead-model", tools=True, auto_eligible=False, cost="0.01"),
            candidate("implementer-model", tools=False, auto_eligible=True, cost="0.02"),
        ),
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model, "implementer-model": child_model},
        default_lead_model="lead-model",
        default_child_model="implementer-model",
        providers={"injected": FakeProviderAdapter()},
        candidates_fn=lambda: routing_snapshot,
    )

    await controller.run_instruction(
        "Delegate the write", controls=LeadControls(model="lead-model")
    )

    snapshot = journal.get_session_snapshot(str(session_id))
    assert [assignment.model for assignment in snapshot.assignments] == ["lead-model"]
    assert child_model.calls == ()


@pytest.mark.asyncio
async def test_lead_assignment_persists_before_first_model_call(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Persistence check", created_at=datetime.now(UTC)
    )

    observed_assignments_before_call = []

    def check_persisted(messages):
        # Query journal database directly to verify assignment was already inserted
        with journal.transaction() as tx:
            rows = tx.connection.execute("SELECT * FROM assignments").fetchall()
            observed_assignments_before_call.append(len(rows))

    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[AIMessage(content="Direct answer.")],
    )
    orig_agenerate = lead_model._agenerate

    async def hooked_agenerate(*args, **kwargs):
        check_persisted(args)
        return await orig_agenerate(*args, **kwargs)

    lead_model._agenerate = hooked_agenerate  # type: ignore[method-assign]

    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model},
    )

    result = await controller.run_instruction("Direct prompt")
    assert observed_assignments_before_call == [1]
    assert result.output == "Direct answer."


@pytest.mark.asyncio
async def test_lead_assignments_use_the_assembled_packet_and_profile_call_prior(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Packet estimates", created_at=datetime.now(UTC)
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={
            "lead-model": ScriptedChatModel(
                model_name="lead-model",
                responses=[AIMessage(content="short done"), AIMessage(content="long done")],
            )
        },
    )

    await controller.run_instruction("Summarize this")
    await controller.run_instruction("x" * 16_000)

    assignments = journal.get_session_snapshot(str(session_id)).assignments
    assert assignments[1].estimated_cost_usd > assignments[0].estimated_cost_usd
    for assignment in assignments:
        assumptions = assignment.payload["routing_inputs"][0]["estimate_assumptions"]
        assert "expected_calls=12" in assumptions
        assert "expected_calls_prior=profile:lead" in assumptions
        assert "cached_input_tokens=0" in assumptions


@pytest.mark.asyncio
async def test_controller_subscribers_see_committed_assignment_events(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Event delivery", created_at=datetime.now(UTC)
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": ScriptedChatModel(responses=[AIMessage(content="Done")])},
    )
    received: list[str] = []

    def observe(event) -> None:
        persisted = journal.get_session_snapshot(str(session_id)).events
        assert any(item.event_id == event.event_id for item in persisted)
        received.append(event.type)

    controller.subscribe_events(observe)
    await controller.run_instruction("Answer directly")

    assert "route.selected" in received
    assert "run.completed" in received


@pytest.mark.asyncio
async def test_lead_completion_persists_terminal_lifecycle_and_context_packet(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Terminal lifecycle", created_at=datetime.now(UTC)
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={
            "lead-model": ScriptedChatModel(
                responses=[
                    AIMessage(
                        content=(
                            '{"answer":"Done.","verification":[{"criterion":'
                            '"The request is complete","passed":true,'
                            '"evidence":"No edits were needed."}]}'
                        )
                    )
                ]
            )
        },
    )

    result = await controller.run_instruction("Finish work")

    snapshot = journal.get_session_snapshot(str(session_id))
    assert snapshot.runs[0].run_id == str(result.run_id)
    assert snapshot.runs[0].status == "completed"
    assert snapshot.tasks[0].status == "succeeded"
    assert snapshot.attempts[0].status == "succeeded"
    assert snapshot.context_packets[0].run_id == str(result.run_id)
    assert snapshot.context_packets[0].payload["objective"] == "Finish work"
    completed = next(event for event in snapshot.events if event.type == "run.completed")
    assert completed.payload.output == {
        "answer": "Done.",
        "verification": [
            {
                "criterion": "The request is complete",
                "passed": True,
                "evidence": "No edits were needed.",
            }
        ],
    }


@pytest.mark.asyncio
async def test_completed_output_redacts_registered_secrets_before_return(tmp_path: Path) -> None:
    secret = "sk-test-secret-value"
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Redacted output", created_at=datetime.now(UTC)
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": ScriptedChatModel(responses=[AIMessage(content=f"Echo {secret}")])},
        redactor=SecretRedactor((secret,)),
    )

    result = await controller.run_instruction("Reply directly")

    assert result.output == "Echo [REDACTED]"
    completed = next(
        event
        for event in journal.get_session_snapshot(str(session_id)).events
        if event.type == "run.completed"
    )
    assert completed.payload.output == "Echo [REDACTED]"


@pytest.mark.asyncio
async def test_explicit_instruction_constraints_apply_only_to_current_run(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Controls check", created_at=datetime.now(UTC)
    )

    lead_custom = ScriptedChatModel(
        model_name="custom-lead", responses=[AIMessage(content="Custom lead run")]
    )
    lead_default = ScriptedChatModel(
        model_name="lead-model", responses=[AIMessage(content="Default lead run")]
    )

    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"custom-lead": lead_custom, "lead-model": lead_default},
        default_lead_model="lead-model",
    )

    # Instruction 1: explicit model constraint
    res1 = await controller.run_instruction("Run 1", controls=LeadControls(model="custom-lead"))
    assert res1.lead_assignment.model == "custom-lead"

    # Instruction 2: default controls - must not retain custom-lead
    res2 = await controller.run_instruction("Run 2")
    assert res2.lead_assignment.model == "lead-model"


@pytest.mark.asyncio
async def test_direct_user_instruction_rejects_plan_and_task_admission(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Direct intent", created_at=datetime.now(UTC)
    )
    planned = {
        "mode": "planned",
        "objective": "Inspect the requested files",
        "constraints": [],
        "reason": "The model incorrectly chose a plan.",
        "plan": {
            "schema_version": 1,
            "policy_version": "adaptive-v1",
            "revision": 1,
            "nodes": [
                {
                    "local_id": "review",
                    "kind": "checkpoint",
                    "objective": "Review the evidence",
                }
            ],
        },
    }
    direct = {
        "mode": "direct",
        "objective": "Inspect the requested files",
        "constraints": [],
        "reason": "The instruction requires direct execution.",
    }
    lead = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    ("execution_decision", planned, "planned-first"),
                    (
                        "task",
                        {"description": "Inspect the requested files", "subagent_type": "explorer"},
                        "task-first",
                    ),
                ]
            ),
            parallel_tool_call_message([("execution_decision", direct, "direct-repair")]),
            AIMessage(content="I inspected the files directly."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead},
    )

    result = await controller.run_instruction(
        "Review the requested files. Do not edit or delegate."
    )

    assert result.status == "completed"
    assert result.child_count == 0
    assert journal.plans_for_run(str(result.run_id)) == ()
    snapshot = journal.get_session_snapshot(str(session_id))
    assert len([task for task in snapshot.tasks if task.run_id == str(result.run_id)]) == 1


@pytest.mark.asyncio
async def test_exact_child_agent_instruction_rejects_extra_plan_agents(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Exact child count", created_at=datetime.now(UTC)
    )
    planned = {
        "mode": "planned",
        "objective": "Implement two independent fixture modules",
        "constraints": [],
        "reason": "Three agent nodes were incorrectly proposed for an exact-two request.",
        "plan": {
            "schema_version": 1,
            "policy_version": "adaptive-v1",
            "revision": 1,
            "nodes": [
                {
                    "local_id": "parser",
                    "kind": "agent",
                    "objective": "Implement the parser fixture",
                    "resource_scopes": ["src/live_fixture/parser.py", "tests/test_parser.py"],
                },
                {
                    "local_id": "report",
                    "kind": "agent",
                    "objective": "Implement the report fixture",
                    "resource_scopes": ["src/live_fixture/report.py", "tests/test_report.py"],
                },
                {
                    "local_id": "extra",
                    "kind": "agent",
                    "objective": "Run integration verification",
                    "resource_scopes": ["tests/test_integration.py"],
                },
            ],
        },
    }
    lead = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            tool_call_message("execution_decision", planned, call_id="too-many-agents"),
            AIMessage(content="The conflicting plan was rejected before work started."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead},
    )

    result = await controller.run_instruction("Use exactly two child agents in parallel.")

    assert result.status == "completed"
    assert result.child_count == 0
    assert journal.plans_for_run(str(result.run_id)) == ()
    snapshot = journal.get_session_snapshot(str(session_id))
    failures = [
        event
        for event in snapshot.events
        if event.run_id == str(result.run_id) and event.type == "tool.failed"
    ]
    assert any(
        "execution.agent_count_conflict" in str(getattr(event.payload, "reason", ""))
        for event in failures
    )
    assert len([task for task in snapshot.tasks if task.run_id == str(result.run_id)]) == 1


@pytest.mark.asyncio
async def test_exact_implementer_intent_rejects_explorer_plan_agents(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Exact implementer profile", created_at=datetime.now(UTC)
    )
    planned = {
        "mode": "planned",
        "objective": "Implement the parser and report fixtures",
        "constraints": [],
        "reason": "The requested implementer profile is required for both writers.",
        "plan": {
            "schema_version": 1,
            "policy_version": "adaptive-v1",
            "revision": 1,
            "nodes": [
                {
                    "local_id": "parser",
                    "kind": "agent",
                    "objective": "Inspect parser fixture",
                    "effect_scope": "read",
                    "resource_scopes": ["src/live_fixture/parser.py"],
                    "task_features": {"profile": "explorer"},
                },
                {
                    "local_id": "report",
                    "kind": "agent",
                    "objective": "Inspect report fixture",
                    "effect_scope": "read",
                    "resource_scopes": ["src/live_fixture/report.py"],
                    "task_features": {"profile": "explorer"},
                },
                {
                    "local_id": "checkpoint",
                    "kind": "checkpoint",
                    "objective": "Review both agent results",
                    "depends_on": ["parser", "report"],
                    "effect_scope": "read",
                },
            ],
        },
    }
    lead = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            tool_call_message("execution_decision", planned, call_id="wrong-agent-profile"),
            AIMessage(
                content="The explorer plan conflicts with the requested implementer profile."
            ),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead},
    )

    result = await controller.run_instruction(
        "Use exactly two implementer child agents in parallel."
    )

    assert result.child_count == 0
    assert journal.plans_for_run(str(result.run_id)) == ()
    snapshot = journal.get_session_snapshot(str(session_id))
    assert len([task for task in snapshot.tasks if task.run_id == str(result.run_id)]) == 1
    assert any(
        event.type == "tool.failed"
        and "execution.agent_profile_conflict" in str(getattr(event.payload, "reason", ""))
        for event in snapshot.events
        if event.run_id == str(result.run_id)
    )


@pytest.mark.asyncio
async def test_no_edit_user_instruction_blocks_write_tool(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Read only intent", created_at=datetime.now(UTC)
    )
    lead = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        {
                            "mode": "direct",
                            "objective": "Review the workspace",
                            "constraints": [],
                            "reason": "The user requested inspection only.",
                        },
                        "decision-read-only",
                    ),
                    (
                        "write_file",
                        {"file_path": "should-not-exist.txt", "content": "blocked\n"},
                        "write-read-only",
                    ),
                ]
            ),
            AIMessage(content="I left the workspace unchanged."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead},
    )

    result = await controller.run_instruction("Review the workspace. Do not edit files.")

    assert result.status == "completed"
    assert not (tmp_path / "should-not-exist.txt").exists()


@pytest.mark.asyncio
async def test_run_model_call_limit_stops_a_read_only_tool_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_controller_module, "MAX_MODEL_CALLS_PER_RUN", 2)
    (tmp_path / "one.txt").write_text("one", encoding="utf-8")
    (tmp_path / "two.txt").write_text("two", encoding="utf-8")
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Bounded tool loop", created_at=datetime.now(UTC)
    )
    lead = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        {
                            "mode": "direct",
                            "objective": "Read the fixture files",
                            "constraints": [],
                            "reason": "This is a bounded read-only loop.",
                        },
                        "loop-decision",
                    ),
                    ("read_file", {"file_path": "one.txt"}, "loop-read-1"),
                ]
            ),
            tool_call_message("read_file", {"file_path": "two.txt"}, call_id="loop-read-2"),
            AIMessage(content="This response must never be requested."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead},
    )

    with pytest.raises(RunModelCallLimitExceeded, match="run.model_call_limit_exhausted"):
        await controller.run_instruction("Read the fixture files.")

    snapshot = journal.get_session_snapshot(str(session_id))
    run = snapshot.runs[-1]
    run_events = [event for event in snapshot.events if event.run_id == run.run_id]
    assert run.status == "failed"
    assert len(lead.calls) == 2
    assert sum(event.type == "model.started" for event in run_events) == 2
    assert sum(event.type == "run.failed" for event in run_events) == 1
    assert not any(event.type == "run.completed" for event in run_events)


@pytest.mark.asyncio
async def test_run_model_call_limit_is_shared_with_child_agents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_controller_module, "MAX_MODEL_CALLS_PER_RUN", 2)
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Shared model call limit", created_at=datetime.now(UTC)
    )
    child = ScriptedChatModel(
        model_name="explorer-model",
        responses=[AIMessage(content='{"status":"failed","summary":"Stopped for test."}')],
    )
    lead = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        {
                            "mode": "direct",
                            "objective": "Delegate a bounded inspection",
                            "constraints": [],
                            "reason": "The user requested one read-only child.",
                        },
                        "shared-limit-decision",
                    ),
                    (
                        "task",
                        {
                            "description": "Inspect the current workspace",
                            "subagent_type": "explorer",
                        },
                        "shared-limit-task",
                    ),
                ]
            ),
            AIMessage(content="This synthesis response must never be requested."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead, "explorer-model": child},
        default_child_model="explorer-model",
        profile_models={"explorer": "explorer-model"},
    )

    with pytest.raises(RunModelCallLimitExceeded, match="run.model_call_limit_exhausted"):
        await controller.run_instruction("Delegate one read-only inspection.")

    snapshot = journal.get_session_snapshot(str(session_id))
    run = snapshot.runs[-1]
    run_events = [event for event in snapshot.events if event.run_id == run.run_id]
    assert len(lead.calls) == 1
    assert len(child.calls) == 1
    assert sum(event.type == "model.started" for event in run_events) == 2
    assert sum(event.type == "run.failed" for event in run_events) == 1
