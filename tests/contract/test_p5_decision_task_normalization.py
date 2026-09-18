"""P5-shape repro for BUG 2: planner decision + task alias normalization."""

from __future__ import annotations

import json

import pytest

from skail.agents.task_graph import decode_task_request
from skail.runtime.decisions import DecisionAdmissionError, ExecutionDecisionGate
from skail.runtime.failure_monitor import FailureMonitor


def _planned_no_plan() -> dict[str, object]:
    # Old TASK_PACKET_GUIDANCE shape: planned mode, no plan.
    return {
        "mode": "planned",
        "objective": "Inspect two files",
        "constraints": "read only",
        "reason": "Independent inspections.",
    }


def test_planned_without_plan_fails_with_actionable_hint() -> None:
    gate = ExecutionDecisionGate(admit_plan=lambda _: None)
    with pytest.raises(DecisionAdmissionError, match="decision.plan_required"):
        gate.admit(_planned_no_plan())  # type: ignore[arg-type]
    assert gate.repairs_remaining == 0


def test_constraints_string_and_json_plan_normalize() -> None:
    admitted: list[object] = []
    gate = ExecutionDecisionGate(admit_plan=admitted.append)
    plan = {
        "schema_version": 1,
        "policy_version": "adaptive-v1",
        "revision": 1,
        "nodes": [
            {
                "local_id": "first",
                "kind": "agent",
                "objective": "Inspect the first file",
                "effect_scope": "read",
                "task_features": {"profile": "explorer"},
            },
        ],
    }
    decision = gate.admit(
        {
            "mode": "planned",
            "objective": "Inspect files",
            "constraints": "read only",
            "reason": "Bounded inspections.",
            "plan": json.dumps(plan),
        }
    )
    assert decision.constraints == ("read only",)
    assert len(admitted) == 1


def test_task_alias_subagent_type_validates() -> None:
    payload = json.dumps(
        {
            "description": "Update the tracked file",
            "subagent_type": "implementer",
            "success_criteria": ["Provide evidence for the completed task"],
        }
    )
    request = decode_task_request(payload, profile="implementer")
    assert request.profile == "implementer"
    assert request.description == "Update the tracked file"


def test_task_json_string_description_validates() -> None:
    inner = json.dumps(
        {
            "description": "Update the tracked file",
            "success_criteria": ["Provide evidence for the completed task"],
        }
    )
    request = decode_task_request(json.dumps(inner), profile="implementer")
    assert request.description == "Update the tracked file"


def test_model_completed_breaks_consecutive_chain() -> None:
    monitor = FailureMonitor()
    assert monitor.observe_error(ValueError("tool failed one")) is None
    monitor.observe_success()  # Simulates model.completed via RuntimeActivityMiddleware.
    assert monitor.observe_error(ValueError("tool failed two")) is None


def test_grep_alias_query_normalizes_to_pattern() -> None:
    from skail.tools.assembly import normalize_tool_args

    normalized = normalize_tool_args("grep", {"query": "SKAIL_LIVE_OK"})
    assert normalized["pattern"] == "SKAIL_LIVE_OK"


def test_grep_wrong_case_keys_normalize() -> None:
    from skail.tools.assembly import normalize_tool_args

    normalized = normalize_tool_args(
        "grep", {"Pattern": "SKAIL_LIVE_OK", "Path": ".", "Include": "*.py"}
    )
    assert normalized["pattern"] == "SKAIL_LIVE_OK"
    assert normalized["path"] == "."
    assert normalized["glob"] == "*.py"


def test_grep_json_string_args_normalize() -> None:
    from skail.tools.assembly import normalize_tool_args

    normalized = normalize_tool_args(
        "grep", '{"query": "SKAIL_LIVE_OK", "dir": "."}'
    )
    assert normalized["pattern"] == "SKAIL_LIVE_OK"
    assert normalized["path"] == "."


def test_grep_missing_pattern_fails_with_actionable_hint() -> None:
    from skail.tools.assembly import ToolArgValidationError, normalize_tool_args

    with pytest.raises(ToolArgValidationError, match="pattern"):
        normalize_tool_args("grep", {"path": "."})
