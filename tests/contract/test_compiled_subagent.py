from __future__ import annotations

import json
from typing import Any

import pytest
from fakes.models import ScriptedChatModel, tool_call_message
from fakes.provider import FakeProviderAdapter, FakeProviderChatModel
from langchain.agents.middleware import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from rudder.providers.errors import ProviderError, ProviderErrorKind
from rudder.providers.fallback import FallbackBinding, ProviderFallbackPolicy
from rudder.runtime.deepagents_adapter import build_lead_agent
from rudder.runtime.model_middleware import (
    AssignmentInvariantError,
    TaskBoundModelMiddleware,
)
from rudder.runtime.task_graph_spike import SpikeAssignment, build_compiled_task_subagent


@tool
def probe(value: str) -> str:
    """Return a deterministic probe result."""

    return f"probed:{value}"


def test_standard_task_tool_invokes_compiled_child_with_isolated_context() -> None:
    child_model = ScriptedChatModel(
        model_name="fake-child-v1",
        responses=[AIMessage(content="child report")],
    )
    child = build_compiled_task_subagent(
        name="explorer",
        description="Inspect one isolated concern.",
        assignment=SpikeAssignment(
            assignment_id="assignment-child-1",
            attempt_id="attempt-child-1",
            model_id="fake-child-v1",
        ),
        models={"fake-child-v1": child_model},
    )
    lead_model = ScriptedChatModel(
        model_name="fake-lead",
        responses=[
            tool_call_message(
                "task",
                {
                    "description": "Inspect the parser without the lead transcript.",
                    "subagent_type": "explorer",
                },
                call_id="task-child-1",
            ),
            AIMessage(content="Lead synthesized the child report."),
        ],
    )
    lead = build_lead_agent(lead_model, subagents=[child])

    result = lead.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Private lead context. Delegate parser inspection.",
                }
            ]
        }
    )

    assert "task" in lead_model.bound_tool_names
    assert child_model.calls
    child_first_call = child_model.calls[0]
    assert any("Inspect the parser" in str(message.content) for message in child_first_call)
    assert not any("Private lead context" in str(message.content) for message in child_first_call)
    lead_human_messages = [
        message for message in result["messages"] if isinstance(message, HumanMessage)
    ]
    assert [message.content for message in lead_human_messages] == [
        "Private lead context. Delegate parser inspection."
    ]
    task_results = [message for message in result["messages"] if isinstance(message, ToolMessage)]
    assert len(task_results) == 1
    payload = json.loads(str(task_results[0].content))
    assert payload == {
        "schema_version": 1,
        "status": "succeeded",
        "assignment_id": "assignment-child-1",
        "attempt_id": "attempt-child-1",
        "model": "fake-child-v1",
        "output": "child report",
    }
    assert "task" not in child_model.bound_tool_names
    assert result["messages"][-1].content == "Lead synthesized the child report."


def test_standard_task_tool_keeps_the_pinned_two_field_schema() -> None:
    child_model = ScriptedChatModel(responses=[AIMessage(content="child")])
    child = build_compiled_task_subagent(
        name="schema-child",
        description="Inspect the task schema.",
        assignment=SpikeAssignment("schema-assignment", "schema-attempt", "schema-model"),
        models={"schema-model": child_model},
    )
    lead_model = ScriptedChatModel(responses=[AIMessage(content="done")])
    lead = build_lead_agent(lead_model, subagents=[child])

    lead.invoke({"messages": [{"role": "user", "content": "Answer directly"}]})

    task_tool = next(
        tool for tool in lead_model.bound_tools if getattr(tool, "name", None) == "task"
    )
    assert set(task_tool.args_schema.model_fields) == {"description", "subagent_type"}


@pytest.mark.asyncio
async def test_assignment_node_finishes_before_the_child_first_model_call() -> None:
    observed: list[str] = []
    construction_model = ScriptedChatModel(
        model_name="construction-model",
        responses=[AIMessage(content="must never run")],
    )

    def record_model_call(
        model: ScriptedChatModel,
        messages: tuple[Any, ...],
    ) -> None:
        del model, messages
        observed.append("model-called")

    child_model = ScriptedChatModel(
        model_name="sticky-child",
        responses=[AIMessage(content="assigned child result")],
        call_hook=record_model_call,
    )
    child = build_compiled_task_subagent(
        name="assigned-child",
        description="Prove assignment ordering.",
        assignment=SpikeAssignment(
            assignment_id="assignment-sticky",
            attempt_id="attempt-sticky",
            model_id="sticky-child",
        ),
        models={"sticky-child": child_model},
        construction_model=construction_model,
    )

    async for update in child["runnable"].astream(
        {"messages": [HumanMessage(content="Perform assigned work")]},
        stream_mode="updates",
    ):
        node = next(iter(update))
        observed.append(node)

    assert observed.index("assign_attempt") < observed.index("model-called")
    assert observed.index("model-called") < observed.index("run_profile_agent")
    assert construction_model.calls == ()


def _sticky_tool_loop() -> tuple[Any, ScriptedChatModel, ScriptedChatModel]:
    construction_model = ScriptedChatModel(
        model_name="construction-loop",
        responses=[AIMessage(content="must never run")],
    )
    assigned_model = ScriptedChatModel(
        model_name="assigned-loop",
        responses=[
            tool_call_message("probe", {"value": "one"}, call_id="probe-1"),
            AIMessage(content="loop complete"),
        ],
    )
    child = build_compiled_task_subagent(
        name="loop-child",
        description="Exercise a two-call tool loop.",
        assignment=SpikeAssignment("loop-assignment", "loop-attempt", "assigned-loop"),
        models={"assigned-loop": assigned_model},
        construction_model=construction_model,
        tools=[probe],
    )
    return child["runnable"], construction_model, assigned_model


def _assert_sticky_loop(
    result: dict[str, Any],
    construction_model: ScriptedChatModel,
    assigned_model: ScriptedChatModel,
) -> None:
    assert result["structured_response"]["output"] == "loop complete"
    assert len(assigned_model.calls) == 2
    assert construction_model.calls == ()
    assert "probe" in assigned_model.bound_tool_names
    assert "task" not in assigned_model.bound_tool_names


def test_compiled_child_keeps_assignment_through_a_sync_tool_loop() -> None:
    runnable, construction_model, assigned_model = _sticky_tool_loop()
    result = runnable.invoke({"messages": [HumanMessage(content="Run the loop")]})
    _assert_sticky_loop(result, construction_model, assigned_model)


@pytest.mark.asyncio
async def test_compiled_child_keeps_assignment_through_an_async_tool_loop() -> None:
    runnable, construction_model, assigned_model = _sticky_tool_loop()
    result = await runnable.ainvoke({"messages": [HumanMessage(content="Run the loop")]})
    _assert_sticky_loop(result, construction_model, assigned_model)


def test_task_bound_middleware_installs_one_sticky_assigned_model() -> None:
    construction_model = ScriptedChatModel(responses=[AIMessage(content="unused")])
    assigned_model = ScriptedChatModel(
        model_name="assigned-model",
        responses=[AIMessage(content="unused")],
    )
    middleware = TaskBoundModelMiddleware(
        {"assigned-model": assigned_model},
        assignments={"assignment-1": "assigned-model"},
        allow_delegation=False,
    )
    state = {
        "messages": [],
        "current_assignment_id": "assignment-1",
        "locked_assignment_id": "assignment-1",
        "assigned_model": "assigned-model",
        "attempt_id": "attempt-1",
    }

    first = middleware.wrap_model_call(
        ModelRequest(
            model=construction_model,
            messages=[],
            state=state,
            tools=[{"name": "task"}, {"name": "read_file"}],
        ),
        lambda request: request,  # type: ignore[arg-type,return-value]
    )
    second = middleware.wrap_model_call(
        ModelRequest(model=construction_model, messages=[], state=state),
        lambda request: request,  # type: ignore[arg-type,return-value]
    )

    assert first.model is assigned_model
    assert second.model is assigned_model
    assert [tool["name"] for tool in first.tools] == ["read_file"]


@pytest.mark.parametrize(
    ("state", "code"),
    [
        ({"messages": []}, "route.assignment_missing"),
        (
            {
                "messages": [],
                "current_assignment_id": "assignment-mutated",
                "locked_assignment_id": "assignment-original",
                "assigned_model": "assigned-model",
                "attempt_id": "attempt-1",
            },
            "route.assignment_changed",
        ),
    ],
)
def test_missing_or_mutated_assignment_stops_before_the_model_call(
    state: dict[str, Any],
    code: str,
) -> None:
    assigned_model = ScriptedChatModel(
        model_name="assigned-model",
        responses=[AIMessage(content="must not run")],
    )
    middleware = TaskBoundModelMiddleware(
        {"assigned-model": assigned_model},
        assignments={"assignment-original": "assigned-model"},
    )
    request = ModelRequest(model=assigned_model, messages=[], state=state)

    with pytest.raises(AssignmentInvariantError) as raised:
        middleware.wrap_model_call(
            request,
            lambda bound: bound,  # type: ignore[arg-type,return-value]
        )

    assert raised.value.error.code == code
    assert assigned_model.calls == ()


def test_unpersisted_assignment_id_stops_before_the_model_call() -> None:
    assigned_model = ScriptedChatModel(responses=[AIMessage(content="must not run")])
    middleware = TaskBoundModelMiddleware({"assigned-model": assigned_model}, assignments={})
    state = {
        "messages": [],
        "current_assignment_id": "unknown",
        "locked_assignment_id": "unknown",
        "assigned_model": "assigned-model",
        "attempt_id": "attempt-1",
    }
    with pytest.raises(AssignmentInvariantError) as raised:
        middleware.wrap_model_call(
            ModelRequest(model=assigned_model, messages=[], state=state),
            lambda bound: bound,  # type: ignore[arg-type,return-value]
        )
    assert raised.value.error.code == "route.assignment_unknown"
    assert assigned_model.calls == ()


def test_compiled_tool_loop_keeps_transport_fallback_binding_for_later_calls() -> None:
    primary = FakeProviderChatModel(model_name="primary", failures=[ProviderErrorKind.RATE_LIMIT])
    fallback = ScriptedChatModel(
        model_name="fallback",
        responses=[
            tool_call_message("probe", {"value": "one"}, call_id="probe-1"),
            AIMessage(content="fallback complete"),
        ],
    )
    calls = 0

    def persisted_fallback(previous: str, error: ProviderError) -> FallbackBinding:
        nonlocal calls
        calls += 1
        return FallbackBinding(
            assignment_id="fallback-assignment",
            provider="backup",
            model="primary",
            model_key="fallback",
            reservation_id="fallback-reservation",
        )

    child = build_compiled_task_subagent(
        name="fallback-child",
        description="Keep fallback sticky.",
        assignment=SpikeAssignment("primary-assignment", "attempt", "primary"),
        models={"primary": primary, "fallback": fallback},
        tools=[probe],
        providers={"fake": FakeProviderAdapter(primary)},
        fallback_policy=ProviderFallbackPolicy(
            {("fake", "primary"): persisted_fallback},
            is_persisted=lambda binding: True,
        ),
    )
    child["runnable"].invoke({"messages": [HumanMessage(content="Run fallback loop")]})
    assert calls == 1
    assert len(fallback.calls) >= 2
