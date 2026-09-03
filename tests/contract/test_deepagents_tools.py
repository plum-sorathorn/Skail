from __future__ import annotations

from fakes.models import ScriptedChatModel, tool_call_message
from langchain_core.messages import AIMessage

from rudder.tools.assembly import build_default_agent


def test_profile_visibility_filters_deepagents_tools_at_model_boundary(tmp_path) -> None:
    model = ScriptedChatModel(responses=[AIMessage(content="done")])
    agent = build_default_agent(model, workspace=tmp_path, profile="explorer")
    agent.invoke({"messages": [{"role": "user", "content": "Inspect"}]})
    assert {"ls", "glob", "grep", "read_file"} <= model.bound_tool_names
    assert not {"write_file", "edit_file", "execute", "task"} & model.bound_tool_names


def test_hidden_deepagents_tool_cannot_be_dispatched_by_hostile_model(tmp_path) -> None:
    model = ScriptedChatModel(
        responses=[
            tool_call_message(
                "write_file",
                {"file_path": "/pwned.txt", "content": "pwned"},
                call_id="hostile-write",
            ),
            AIMessage(content="done"),
        ]
    )
    agent = build_default_agent(model, workspace=tmp_path, profile="explorer")
    result = agent.invoke({"messages": [{"role": "user", "content": "Inspect"}]})
    assert not (tmp_path / "pwned.txt").exists()
    tool_messages = [message for message in result["messages"] if message.type == "tool"]
    assert tool_messages[-1].status == "error"
