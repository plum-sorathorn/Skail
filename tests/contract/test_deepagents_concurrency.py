from __future__ import annotations

import asyncio
from collections import deque
from threading import Lock
from typing import Any

import pytest
from fakes.barriers import AsyncStartBarrier
from fakes.models import ScriptedChatModel, parallel_tool_call_message
from langchain_core.messages import AIMessage, BaseMessage

from skail.runtime.deepagents_adapter import (
    ChildRunGate,
    build_lead_agent,
    run_task_batch,
    stream_events,
)
from skail.runtime.task_graph_spike import SpikeAssignment, build_compiled_task_subagent


class TaskIdFactory:
    def __init__(self, *task_ids: str) -> None:
        self._task_ids = deque(task_ids)
        self._lock = Lock()

    def __call__(self) -> str:
        with self._lock:
            return self._task_ids.popleft()


@pytest.mark.asyncio
async def test_nested_child_streams_have_distinct_namespaces_and_task_identity() -> None:
    child_model = ScriptedChatModel(
        model_name="stream-child",
        responses=[
            AIMessage(content="first child result"),
            AIMessage(content="second child result"),
        ],
    )
    child = build_compiled_task_subagent(
        name="stream-worker",
        description="Return an isolated streaming result.",
        assignment=SpikeAssignment(
            assignment_id="stream-assignment",
            attempt_id="stream-attempt",
            model_id="stream-child",
        ),
        models={"stream-child": child_model},
        task_id_factory=TaskIdFactory("stream-alpha", "stream-beta"),
    )
    lead_model = ScriptedChatModel(
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "task",
                        {
                            "description": "Inspect the identical target",
                            "subagent_type": "stream-worker",
                        },
                        "stream-task-alpha",
                    ),
                    (
                        "task",
                        {
                            "description": "Inspect the identical target",
                            "subagent_type": "stream-worker",
                        },
                        "stream-task-beta",
                    ),
                ]
            ),
            AIMessage(content="combined stream result"),
        ]
    )
    lead = build_lead_agent(lead_model, subagents=[child])

    events = [
        event
        async for event in stream_events(
            lead,
            {"messages": [{"role": "user", "content": "Delegate twice"}]},
            task_id="lead-stream-task",
        )
    ]

    child_stream_roots = {
        event.namespace[0]
        for event in events
        if event.namespace and event.namespace[0].startswith("tools:")
    }
    assert len(child_stream_roots) == 2, [event.namespace for event in events]
    nested_task_ids = {
        event.task_id for event in events if event.namespace and event.task_id is not None
    }
    assert nested_task_ids == {"stream-alpha", "stream-beta"}
    assert {event.task_id for event in events if not event.namespace} == {"lead-stream-task"}
    assert len(child_model.calls) == 2


def _barrier_lead(
    barrier: AsyncStartBarrier,
    gate: ChildRunGate,
) -> tuple[Any, ScriptedChatModel, ScriptedChatModel]:
    async def wait_in_model(
        model: ScriptedChatModel,
        messages: tuple[BaseMessage, ...],
    ) -> None:
        del model
        raw = str(messages[-1].content)
        task_id = raw.rsplit(" ", 1)[-1]
        await barrier.worker(task_id)

    child_model = ScriptedChatModel(
        model_name="barrier-child",
        responses=[AIMessage(content=f"result:{index}") for index in range(4)],
        async_call_hook=wait_in_model,
    )
    child = build_compiled_task_subagent(
        name="barrier-worker",
        description="Wait at a deterministic concurrency barrier.",
        assignment=SpikeAssignment("barrier-assignment", "barrier-attempt", "barrier-child"),
        models={"barrier-child": child_model},
        execution_gate=gate,
        task_id_factory=TaskIdFactory("gate-1", "gate-2", "gate-3", "gate-4"),
    )
    calls = [
        (
            "task",
            {
                "description": f"Wait for release child-{index}",
                "subagent_type": "barrier-worker",
            },
            f"tool-call-{index}",
        )
        for index in range(1, 5)
    ]
    lead_model = ScriptedChatModel(
        model_name="barrier-lead",
        responses=[parallel_tool_call_message(calls), AIMessage(content="batch complete")],
    )
    return build_lead_agent(lead_model, subagents=[child]), lead_model, child_model


@pytest.mark.asyncio
async def test_real_task_path_runs_three_children_and_queues_the_fourth() -> None:
    barrier = AsyncStartBarrier()
    gate = ChildRunGate(max_children=3)
    lead, _, child_model = _barrier_lead(barrier, gate)

    run = asyncio.create_task(
        lead.ainvoke({"messages": [{"role": "user", "content": "Run four tasks"}]})
    )
    await barrier.wait_for_started(3)
    assert len(barrier.started) == 3
    assert set(barrier.started) < {"child-1", "child-2", "child-3", "child-4"}
    assert gate.active == 3

    first_wave = tuple(barrier.started)
    barrier.release(first_wave[0])
    await barrier.wait_for_started(4)
    assert set(barrier.started) == {"child-1", "child-2", "child-3", "child-4"}
    for task_id in barrier.started:
        barrier.release(task_id)

    result = await run
    assert result["messages"][-1].content == "batch complete"
    assert len(child_model.calls) == 4
    assert gate.peak_active == 3


@pytest.mark.asyncio
async def test_real_lead_cancellation_stops_children_and_keeps_completed_evidence() -> None:
    barrier = AsyncStartBarrier()
    gate = ChildRunGate(max_children=3)
    lead, lead_model, _ = _barrier_lead(barrier, gate)
    run = asyncio.create_task(
        lead.ainvoke({"messages": [{"role": "user", "content": "Run and cancel"}]})
    )
    await barrier.wait_for_started(3)

    first_wave = tuple(barrier.started)
    barrier.release(first_wave[0])
    await gate.wait_for_completed(1)
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run

    assert len(gate.completed) == 1
    assert set(barrier.cancelled) == set(first_wave[1:])
    assert len(barrier.started) == 3
    assert gate.active == 0
    assert len(lead_model.calls) == 1


@pytest.mark.asyncio
async def test_three_children_start_and_a_fourth_waits_for_a_gate_slot() -> None:
    barrier = AsyncStartBarrier()
    gate = ChildRunGate(max_children=3)
    operations = {
        task_id: (lambda task_id=task_id: barrier.worker(task_id))
        for task_id in ("child-1", "child-2", "child-3", "child-4")
    }

    batch = asyncio.create_task(run_task_batch(operations, gate=gate))
    await barrier.wait_for_started(3)

    assert barrier.started == ["child-1", "child-2", "child-3"]
    assert gate.active == 3
    assert gate.peak_active == 3
    assert "child-4" not in barrier.started

    barrier.release("child-1")
    await barrier.wait_for_started(4)
    assert barrier.started[-1] == "child-4"

    for task_id in ("child-2", "child-3", "child-4"):
        barrier.release(task_id)
    result = await batch

    assert result == {
        "child-1": "result:child-1",
        "child-2": "result:child-2",
        "child-3": "result:child-3",
        "child-4": "result:child-4",
    }
    assert gate.active == 0


def test_child_gate_rejects_more_than_the_hard_maximum() -> None:
    with pytest.raises(ValueError, match="between 1 and 3"):
        ChildRunGate(max_children=4)


@pytest.mark.asyncio
async def test_whole_run_cancellation_preserves_completed_child_evidence() -> None:
    barrier = AsyncStartBarrier()
    gate = ChildRunGate(max_children=3)
    operations = {
        task_id: (lambda task_id=task_id: barrier.worker(task_id))
        for task_id in ("completed-child", "unfinished-child", "queued-child", "last-child")
    }
    batch = asyncio.create_task(run_task_batch(operations, gate=gate))
    await barrier.wait_for_started(3)

    barrier.release("completed-child")
    await barrier.wait_for_completed(1)
    batch.cancel()

    with pytest.raises(asyncio.CancelledError):
        await batch

    assert gate.completed == {"completed-child": "result:completed-child"}
    assert "unfinished-child" in barrier.cancelled
    assert "queued-child" in barrier.cancelled
    assert gate.active == 0
