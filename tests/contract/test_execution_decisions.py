from __future__ import annotations

from typing import Any

import pytest
from fakes.models import ScriptedChatModel, parallel_tool_call_message
from langchain_core.messages import AIMessage, ToolMessage

from skail.domain.decisions import ExecutionMode
from skail.domain.plans import ExecutionPlan
from skail.runtime.decisions import (
    DecisionAdmissionError,
    ExecutionDecisionGate,
    ExecutionDecisionMiddleware,
    execution_decision_tool,
)
from skail.tools.assembly import build_default_agent


def _direct_decision() -> dict[str, Any]:
    return {
        "mode": "direct",
        "objective": "Write the requested output",
        "constraints": [],
        "reason": "The work is bounded.",
    }


def test_decision_and_following_operation_share_the_initial_model_response(tmp_path) -> None:
    admitted: list[dict[str, Any]] = []
    gate = ExecutionDecisionGate(admit_plan=admitted.append)
    model = ScriptedChatModel(
        responses=[
            parallel_tool_call_message(
                [
                    ("execution_decision", _direct_decision(), "decision-1"),
                    (
                        "write_file",
                        {"file_path": "answer.txt", "content": "ready\n"},
                        "write-1",
                    ),
                ]
            ),
            AIMessage(content="Done."),
        ]
    )
    agent = build_default_agent(
        model,
        workspace=tmp_path,
        profile="lead",
        extension_tools=[execution_decision_tool(gate)],
        extra_middleware=[ExecutionDecisionMiddleware(gate)],
    )

    result = agent.invoke({"messages": [{"role": "user", "content": "Write it."}]})

    assert (tmp_path / "answer.txt").read_text(encoding="utf-8") == "ready\n"
    assert len(model.calls) == 2
    assert admitted == []
    assert gate.decision is not None
    assert gate.decision.mode == "direct"
    assert result["messages"][-1].content == "Done."


def test_nested_full_decision_plan_shape_is_normalized_before_validation() -> None:
    admitted: list[ExecutionPlan] = []
    gate = ExecutionDecisionGate(admit_plan=admitted.append)
    nested_plan = {
        "mode": "planned",
        "objective": "Inspect before implementation",
        "reason": "The work needs a gated discovery pass.",
        "plan": {
            "schema_version": 1,
            "policy_version": "adaptive-v1",
            "revision": 1,
            "nodes": [
                {
                    "local_id": "checkpoint",
                    "kind": "checkpoint",
                    "objective": "Review discovery evidence",
                    "effect_scope": "read",
                }
            ],
        },
    }

    decision = gate.admit(
        {
            "mode": "planned",
            "objective": "Inspect before implementation",
            "reason": "The work needs a gated discovery pass.",
            "plan": nested_plan,
        }
    )

    assert decision.mode.value == "planned"
    assert decision.plan is not None
    assert decision.plan.revision == 1
    assert len(admitted) == 1


@pytest.mark.parametrize(
    "field, inner_value",
    [("mode", "direct"), ("objective", "A conflicting objective")],
)
def test_nested_decision_metadata_conflicts_are_rejected(field: str, inner_value: str) -> None:
    admitted: list[ExecutionPlan] = []
    gate = ExecutionDecisionGate(admit_plan=admitted.append)
    nested_plan: dict[str, Any] = {
        "mode": "planned",
        "objective": "Inspect before implementation",
        "reason": "The work needs a gated discovery pass.",
        "plan": {
            "schema_version": 1,
            "policy_version": "adaptive-v1",
            "revision": 1,
            "nodes": [
                {
                    "local_id": "checkpoint",
                    "kind": "checkpoint",
                    "objective": "Review discovery evidence",
                    "effect_scope": "read",
                }
            ],
        },
    }
    nested_plan[field] = inner_value

    with pytest.raises(DecisionAdmissionError, match="decision.payload_conflict"):
        gate.admit(
            {
                "mode": "planned",
                "objective": "Inspect before implementation",
                "reason": "The work needs a gated discovery pass.",
                "plan": nested_plan,
            }
        )

    assert admitted == []


def test_explicit_direct_intent_rejects_plans_before_admission() -> None:
    admitted: list[ExecutionPlan] = []
    gate = ExecutionDecisionGate(
        admit_plan=admitted.append,
        required_mode=ExecutionMode.DIRECT,
    )
    planned = {
        "mode": "planned",
        "objective": "Inspect before implementation",
        "reason": "The work needs a plan.",
        "plan": {
            "schema_version": 1,
            "policy_version": "adaptive-v1",
            "revision": 1,
            "nodes": [
                {
                    "local_id": "checkpoint",
                    "kind": "checkpoint",
                    "objective": "Review evidence",
                }
            ],
        },
    }

    with pytest.raises(DecisionAdmissionError, match="execution.intent_conflict"):
        gate.admit(planned)

    assert admitted == []


def test_exact_agent_count_requires_disjoint_scopes() -> None:
    admitted: list[ExecutionPlan] = []
    gate = ExecutionDecisionGate(admit_plan=admitted.append, required_agent_count=2)
    plan = {
        "schema_version": 1,
        "policy_version": "adaptive-v1",
        "revision": 1,
        "nodes": [
            {
                "local_id": "source",
                "kind": "agent",
                "objective": "Inspect source",
                "resource_scopes": ["src/a.py"],
            },
            {
                "local_id": "tests",
                "kind": "agent",
                "objective": "Inspect tests",
                "resource_scopes": ["tests/a.py"],
            },
        ],
    }

    decision = gate.admit(
        {
            "mode": "planned",
            "objective": "Inspect source and tests",
            "reason": "The two independent reviews are explicitly requested.",
            "plan": plan,
        }
    )

    assert decision.mode is ExecutionMode.PLANNED
    assert len(admitted) == 1


@pytest.mark.parametrize(
    "nodes, error_code",
    [
        (
            [
                {
                    "local_id": "source",
                    "kind": "agent",
                    "objective": "Inspect source",
                    "resource_scopes": ["src/a.py"],
                }
            ],
            "execution.agent_count_conflict",
        ),
        (
            [
                {
                    "local_id": "source",
                    "kind": "agent",
                    "objective": "Inspect source",
                    "resource_scopes": ["src"],
                },
                {
                    "local_id": "nested",
                    "kind": "agent",
                    "objective": "Inspect a nested source path",
                    "resource_scopes": ["src/a.py"],
                },
            ],
            "execution.agent_scope_conflict",
        ),
    ],
)
def test_exact_agent_constraint_rejects_count_or_scope_conflicts(
    nodes: list[dict[str, Any]], error_code: str
) -> None:
    admitted: list[ExecutionPlan] = []
    gate = ExecutionDecisionGate(admit_plan=admitted.append, required_agent_count=2)

    with pytest.raises(DecisionAdmissionError, match=error_code):
        gate.admit(
            {
                "mode": "planned",
                "objective": "Inspect source and tests",
                "reason": "The two independent reviews are explicitly requested.",
                "plan": {
                    "schema_version": 1,
                    "policy_version": "adaptive-v1",
                    "revision": 1,
                    "nodes": nodes,
                },
            }
        )

    assert admitted == []


def test_operation_before_decision_is_rejected_without_a_side_effect(tmp_path) -> None:
    gate = ExecutionDecisionGate(admit_plan=lambda _: None)
    model = ScriptedChatModel(
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "write_file",
                        {"file_path": "unsafe.txt", "content": "must not exist\n"},
                        "write-first",
                    ),
                    ("execution_decision", _direct_decision(), "decision-late"),
                ]
            ),
            AIMessage(content="The unsafe operation was rejected."),
        ]
    )
    agent = build_default_agent(
        model,
        workspace=tmp_path,
        profile="lead",
        extension_tools=[execution_decision_tool(gate)],
        extra_middleware=[ExecutionDecisionMiddleware(gate)],
    )

    result = agent.invoke({"messages": [{"role": "user", "content": "Write it."}]})

    assert not (tmp_path / "unsafe.txt").exists()
    errors = [
        message
        for message in result["messages"]
        if isinstance(message, ToolMessage) and message.status == "error"
    ]
    assert len(errors) == 1
    assert "execution.decision_required" in str(errors[0].content)


def test_invalid_plan_allows_one_repair_but_never_admits_the_invalid_record() -> None:
    admitted: list[dict[str, Any]] = []
    gate = ExecutionDecisionGate(admit_plan=admitted.append)
    invalid = {
        "mode": "planned",
        "objective": "Change code",
        "constraints": [],
        "reason": "Needs a plan.",
        "plan": {
            "schema_version": 1,
            "policy_version": "adaptive-v1",
            "revision": 1,
            "nodes": [],
        },
    }

    with pytest.raises(DecisionAdmissionError, match="decision.plan_invalid"):
        gate.admit(invalid)

    assert gate.repairs_remaining == 1
    assert admitted == []
    with pytest.raises(DecisionAdmissionError, match="decision.plan_invalid"):
        gate.admit(invalid)
    assert gate.repairs_remaining == 0
    with pytest.raises(DecisionAdmissionError, match="decision.repair_exhausted"):
        gate.admit(invalid)


def test_invalid_decision_tool_call_consumes_only_one_repair(tmp_path) -> None:
    gate = ExecutionDecisionGate(admit_plan=lambda _: None)
    model = ScriptedChatModel(
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        {
                            "mode": "planned",
                            "objective": "Invalid plan",
                            "constraints": [],
                            "reason": "Exercise the repair boundary.",
                            "plan": {
                                "schema_version": 1,
                                "policy_version": "adaptive-v1",
                                "revision": 1,
                                "nodes": [],
                            },
                        },
                        "invalid-decision-1",
                    )
                ]
            ),
            AIMessage(content="I need to repair the plan."),
        ]
    )
    agent = build_default_agent(
        model,
        workspace=tmp_path,
        profile="lead",
        extension_tools=[execution_decision_tool(gate)],
        extra_middleware=[ExecutionDecisionMiddleware(gate)],
    )

    result = agent.invoke({"messages": [{"role": "user", "content": "Plan this."}]})

    assert gate.repairs_remaining == 1
    decision_results = [
        message
        for message in result["messages"]
        if isinstance(message, ToolMessage)
    ]
    assert "decision.plan_invalid" in str(decision_results[0].content)


def test_discovery_admits_only_read_evidence_work_with_a_checkpoint() -> None:
    admitted: list[dict[str, Any]] = []
    gate = ExecutionDecisionGate(admit_plan=admitted.append)

    decision = gate.admit(
        {
            "mode": "discovery",
            "objective": "Inspect the current configuration",
            "constraints": ["do not modify files"],
            "reason": "The next implementation step depends on repository evidence.",
            "plan": {
                "schema_version": 1,
                "policy_version": "adaptive-v1",
                "revision": 1,
                "nodes": [
                    {
                        "local_id": "inspect",
                        "kind": "agent",
                        "objective": "Read the current configuration",
                    },
                    {
                        "local_id": "checkpoint",
                        "kind": "checkpoint",
                        "objective": "Decide whether implementation is warranted",
                        "depends_on": ["inspect"],
                    },
                ],
            },
        }
    )

    assert decision.mode == "discovery"
    assert len(admitted) == 1


def test_final_answer_does_not_trigger_a_classifier_model_call(tmp_path) -> None:
    gate = ExecutionDecisionGate(admit_plan=lambda _: None)
    model = ScriptedChatModel(responses=[AIMessage(content="The answer is concise.")])
    agent = build_default_agent(
        model,
        workspace=tmp_path,
        profile="lead",
        extension_tools=[execution_decision_tool(gate)],
        extra_middleware=[ExecutionDecisionMiddleware(gate)],
    )

    result = agent.invoke({"messages": [{"role": "user", "content": "Answer directly."}]})

    assert result["messages"][-1].content == "The answer is concise."
    assert len(model.calls) == 1
