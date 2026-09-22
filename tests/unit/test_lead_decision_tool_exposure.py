"""Prove execution_decision reaches the model's tool list and system prompt.

Verdict test for live runs where the lead never calls execution_decision:
(A) wiring bug - tool not offered in the outbound request, vs
(B) behavioral failure - tool offered but the model ignores it.

Exercises the REAL assembly path used by run_controller:
build_production_lead -> build_default_agent with
extension_tools=[execution_decision_tool(gate)].
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from skail.agents.lead import (
    TASK_PACKET_GUIDANCE,
    LeadControls,
    build_production_lead,
)
from skail.runtime.decisions import ExecutionDecisionGate, execution_decision_tool
from skail.runtime.leases import WorkspaceLeaseManager
from tests.fakes.models import ScriptedChatModel


def _build_lead(model: ScriptedChatModel, workspace: Path) -> object:
    gate = ExecutionDecisionGate(admit_plan=lambda plan: None)
    return build_production_lead(
        model,
        workspace=workspace,
        controls=LeadControls(),
        leases=WorkspaceLeaseManager(),
        extension_tools=[execution_decision_tool(gate)],
        session_id="test-session",
        run_id="test-run",
    )


def test_execution_decision_reaches_model_tool_list(tmp_path: Path) -> None:
    """The model must be offered execution_decision via the real lead path."""
    model = ScriptedChatModel(responses=[AIMessage(content="done")])
    agent = _build_lead(model, tmp_path)

    # DeepAgents binds tools lazily at invoke time, so drive one model call
    # first; bound_tool_names then reflects exactly what the model received.
    invoke = getattr(agent, "invoke")
    invoke({"messages": [HumanMessage(content="hello")]})  # type: ignore[operator]

    bound = set(model.bound_tool_names)
    assert "execution_decision" in bound, (
        f"execution_decision missing from model tool list; got {sorted(bound)}"
    )


def test_lead_guidance_reaches_system_prompt(tmp_path: Path) -> None:
    """The rendered system prompt the model receives must name execution_decision."""
    assert "execution_decision" in TASK_PACKET_GUIDANCE

    model = ScriptedChatModel(responses=[AIMessage(content="done")])
    agent = _build_lead(model, tmp_path)

    invoke = getattr(agent, "invoke")
    invoke({"messages": [HumanMessage(content="hello")]})  # type: ignore[operator]

    assert model.calls, "expected at least one model call"
    first_call = model.calls[0]
    system_text = "\n".join(
        str(getattr(message, "content", ""))
        for message in first_call
        if isinstance(message, SystemMessage)
    )
    assert "execution_decision" in system_text, (
        f"guidance missing from system prompt; got {system_text!r}"
    )
