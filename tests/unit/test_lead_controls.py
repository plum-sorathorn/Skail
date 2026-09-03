from pathlib import Path

from fakes.models import ScriptedChatModel
from langchain_core.messages import AIMessage

from rudder.agents.lead import LeadControls, build_production_lead, delegation_allowed
from rudder.runtime.leases import WorkspaceLeaseManager


def test_delegation_controls_are_runtime_decisions() -> None:
    assert delegation_allowed(LeadControls(delegation="off"), requested=True) is False
    assert delegation_allowed(LeadControls(delegation="ask"), requested=False) is False
    assert delegation_allowed(LeadControls(delegation="ask"), requested=True) is True
    assert delegation_allowed(LeadControls(), requested=False) is True


def test_off_and_no_write_controls_remove_runtime_tool_authority(tmp_path: Path) -> None:
    model = ScriptedChatModel(responses=[AIMessage(content="done")])
    lead = build_production_lead(
        model,
        workspace=tmp_path,
        controls=LeadControls(delegation="off", write_allowed=False),
        leases=WorkspaceLeaseManager(),
    )
    lead.invoke({"messages": [{"role": "user", "content": "work directly"}]})

    assert "task" not in model.bound_tool_names
    assert {"write_file", "edit_file", "execute"}.isdisjoint(model.bound_tool_names)
