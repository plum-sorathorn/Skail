"""Actionable rejection messages for decision gating (P3 live follow-up)."""
from __future__ import annotations

from typing import Any

import pytest
from langchain.agents.middleware import ToolCallRequest
from langchain_core.messages import ToolMessage

from skail.runtime.decisions import DecisionAdmissionError, ExecutionDecisionGate


def _tool_request(name: str, args: dict[str, Any], call_id: str) -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"name": name, "args": args, "id": call_id, "type": "tool_call"},
        tool=None,
        state=None,
        runtime=None,  # type: ignore[arg-type]
    )


async def test_decision_required_names_recovery() -> None:
    from skail.runtime.decisions import ExecutionDecisionMiddleware

    gate = ExecutionDecisionGate(admit_plan=lambda _: None)
    middleware = ExecutionDecisionMiddleware(gate)

    async def terminal(request: ToolCallRequest) -> ToolMessage:
        call_id = request.tool_call.get("id")
        assert isinstance(call_id, str)
        return ToolMessage(content="ok", tool_call_id=call_id)

    result = await middleware.awrap_tool_call(
        _tool_request("grep", {"pattern": "TODO", "path": "."}, "grep-1"),
        terminal,
    )
    assert isinstance(result, ToolMessage)
    content = str(result.content)
    assert content.startswith("execution.decision_required")
    assert "execution_decision" in content
    assert "mode" in content


def test_plan_refused_is_actionable_not_bare() -> None:
    def refuse(_: Any) -> None:
        raise ValueError("plan store unavailable: missing nodes.0.objective")

    gate = ExecutionDecisionGate(admit_plan=refuse)
    with pytest.raises(DecisionAdmissionError) as caught:
        gate.admit(
            {
                "mode": "planned",
                "objective": "survey the repo",
                "reason": "recon",
                "constraints": (),
                "plan": {
                    "schema_version": 1,
                    "policy_version": "adaptive-v1",
                    "revision": 1,
                    "nodes": [
                        {
                            "local_id": "explore",
                            "kind": "checkpoint",
                            "objective": "survey the repo",
                            "effect_scope": "read",
                        }
                    ],
                },
                "revision": None,
            }
        )
    message = str(caught.value)
    assert message.startswith("decision.plan_refused")
    assert message != "decision.plan_refused"
    assert (
        "missing" in message
        or "unexpected" in message
        or "skeleton" in message
        or "schema_version" in message
        or "nodes.0.objective" in message
        or "ValueError" in message
        or "plan store unavailable" in message
    )
