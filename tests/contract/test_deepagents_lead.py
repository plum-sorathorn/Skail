from __future__ import annotations

from pathlib import Path

import pytest
from fakes.models import ScriptedChatModel, tool_call_message
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from skail.runtime.deepagents_adapter import build_lead_agent, stream_events


@tool
def lookup_weather(city: str) -> str:
    """Return deterministic weather for a city."""

    return f"clear:{city}"


def test_fake_lead_uses_a_tool_then_returns_a_final_response() -> None:
    model = ScriptedChatModel(
        responses=[
            tool_call_message(
                "lookup_weather",
                {"city": "Oslo"},
                call_id="weather-1",
            ),
            AIMessage(content="Oslo is clear."),
        ]
    )
    agent = build_lead_agent(model, tools=[lookup_weather])

    result = agent.invoke({"messages": [{"role": "user", "content": "Weather?"}]})

    assert result["messages"][-1].content == "Oslo is clear."
    tool_results = [message for message in result["messages"] if isinstance(message, ToolMessage)]
    assert [message.content for message in tool_results] == ["clear:Oslo"]
    assert "lookup_weather" in model.bound_tool_names
    assert len(model.calls) == 2


@pytest.mark.asyncio
async def test_framework_stream_is_adapted_without_leaking_ui_types() -> None:
    model = ScriptedChatModel(responses=[AIMessage(content="streamed final")])
    agent = build_lead_agent(model)

    events = [
        event
        async for event in stream_events(
            agent,
            {"messages": [{"role": "user", "content": "Answer once"}]},
            task_id="lead-task",
        )
    ]

    assert events
    assert {event.task_id for event in events} == {"lead-task"}
    assert {event.stream_mode for event in events} <= {"updates", "messages"}
    assert all(isinstance(event.namespace, tuple) for event in events)
    assert not any(type(event.payload).__module__.startswith("textual") for event in events)


def test_sqlite_checkpoint_resumes_a_deliberately_interrupted_lead(
    tmp_path: Path,
) -> None:
    model = ScriptedChatModel(
        responses=[
            tool_call_message(
                "lookup_weather",
                {"city": "Reykjavik"},
                call_id="weather-approval-1",
            ),
            AIMessage(content="Approved result: clear:Reykjavik"),
        ]
    )
    config = {"configurable": {"thread_id": "sqlite-resume-contract"}}
    database = tmp_path / "checkpoints.sqlite"

    with SqliteSaver.from_conn_string(str(database)) as checkpointer:
        agent = build_lead_agent(
            model,
            tools=[lookup_weather],
            checkpointer=checkpointer,
            interrupt_on={"lookup_weather": True},
        )
        interrupted = agent.invoke(
            {"messages": [{"role": "user", "content": "Check Reykjavik"}]},
            config=config,
        )

        assert interrupted["__interrupt__"]
        assert len(model.calls) == 1

    with SqliteSaver.from_conn_string(str(database)) as reopened_checkpointer:
        resumed_agent = build_lead_agent(
            model,
            tools=[lookup_weather],
            checkpointer=reopened_checkpointer,
            interrupt_on={"lookup_weather": True},
        )
        resumed = resumed_agent.invoke(
            Command(resume={"decisions": [{"type": "approve"}]}),
            config=config,
        )

    assert resumed["messages"][-1].content == "Approved result: clear:Reykjavik"
    tool_results = [message for message in resumed["messages"] if isinstance(message, ToolMessage)]
    assert [message.content for message in tool_results] == ["clear:Reykjavik"]
    assert len(model.calls) == 2
