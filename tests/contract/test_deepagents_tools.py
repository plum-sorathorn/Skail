from __future__ import annotations

from pathlib import Path

from fakes.models import ScriptedChatModel, tool_call_message
from langchain_core.messages import AIMessage

from skail.tools.assembly import build_default_agent


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


def test_agent_read_file_returns_extracted_pdf_text_to_model(tmp_path: Path) -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "documents" / "sample.pdf"
    (tmp_path / "sample.pdf").write_bytes(fixture.read_bytes())
    model = ScriptedChatModel(
        responses=[
            tool_call_message(
                "read_file", {"file_path": "/sample.pdf"}, call_id="read-pdf"
            ),
            AIMessage(content="done"),
        ]
    )
    agent = build_default_agent(model, workspace=tmp_path, profile="explorer")

    agent.invoke({"messages": [{"role": "user", "content": "Inspect the PDF"}]})

    tool_messages = [message for message in model.calls[1] if message.type == "tool"]
    assert len(tool_messages) == 1
    assert isinstance(tool_messages[0].content, str)
    assert "Skail PDF sample page one" in tool_messages[0].content
    assert "JVBER" not in tool_messages[0].content


async def test_async_agent_read_file_returns_extracted_pdf_text_to_model(tmp_path: Path) -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "documents" / "sample.pdf"
    (tmp_path / "sample.pdf").write_bytes(fixture.read_bytes())
    model = ScriptedChatModel(
        responses=[
            tool_call_message(
                "read_file", {"file_path": "/sample.pdf"}, call_id="read-pdf-async"
            ),
            AIMessage(content="done"),
        ]
    )
    agent = build_default_agent(model, workspace=tmp_path, profile="explorer")

    await agent.ainvoke({"messages": [{"role": "user", "content": "Inspect the PDF"}]})

    tool_messages = [message for message in model.calls[1] if message.type == "tool"]
    assert len(tool_messages) == 1
    assert isinstance(tool_messages[0].content, str)
    assert "Skail PDF sample page one" in tool_messages[0].content
