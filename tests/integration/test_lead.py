import hashlib
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fakes.models import ScriptedChatModel, tool_call_message
from langchain_core.messages import AIMessage

from rudder.agents.lead import LeadControls
from rudder.domain.ids import new_session_id
from rudder.providers.models import CapabilityVector, ModelProfile, ProviderSupportLevel
from rudder.routing.assignment import RoutingSnapshot, config_revision
from rudder.routing.selector import RouteCandidate
from rudder.runtime.run_controller import RunController
from rudder.sessions.journal import Journal


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
            tool_call_message(
                "write_file",
                {"file_path": "solution.py", "content": "def solve(): return 42\n"},
                call_id="call-write-1",
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
            tool_call_message(
                "task",
                {
                    "description": "Write child_output.txt file",
                    "subagent_type": "implementer",
                },
                call_id="task-call-1",
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
                provider="fake",
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
        models={"lead-model": ScriptedChatModel(responses=[AIMessage(content="Done.")])},
    )

    result = await controller.run_instruction("Finish work")

    snapshot = journal.get_session_snapshot(str(session_id))
    assert snapshot.runs[0].run_id == str(result.run_id)
    assert snapshot.runs[0].status == "completed"
    assert snapshot.tasks[0].status == "succeeded"
    assert snapshot.attempts[0].status == "succeeded"
    assert snapshot.context_packets[0].run_id == str(result.run_id)
    assert snapshot.context_packets[0].payload["objective"] == "Finish work"


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
