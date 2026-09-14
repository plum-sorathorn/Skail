from __future__ import annotations

import asyncio

import pytest
from fakes.barriers import AsyncStartBarrier

from skail.runtime.scheduler import ChildScheduler


def test_scheduler_accepts_only_the_stable_child_limit() -> None:
    for limit in (1, 2, 3):
        assert ChildScheduler(max_children=limit).max_children == limit
    for limit in (0, 4):
        with pytest.raises(ValueError, match="between 1 and 3"):
            ChildScheduler(max_children=limit)


def test_ready_tasks_are_ordered_by_priority_then_creation() -> None:
    scheduler = ChildScheduler(max_children=3)
    scheduler.submit("later-low", priority=1)
    scheduler.submit("first-high", priority=5)
    scheduler.submit("second-high", priority=5)

    assert scheduler.ready() == ("first-high", "second-high", "later-low")


def test_failed_dependency_blocks_its_dependents() -> None:
    scheduler = ChildScheduler(max_children=3)
    scheduler.submit("parent", priority=1)
    scheduler.submit("child", priority=1, depends_on=("parent",))

    scheduler.finish("parent", succeeded=False)

    assert scheduler.blocked == {"child": "dependency_unsuccessful"}


def test_approval_wait_does_not_consume_a_child_slot() -> None:
    scheduler = ChildScheduler(max_children=1)
    scheduler.submit("waiting", priority=1, awaiting_approval=True)
    scheduler.submit("ready", priority=1)

    assert scheduler.ready() == ("ready",)
    assert scheduler.gate.active == 0


@pytest.mark.asyncio
async def test_scheduler_dispatches_three_and_queues_the_fourth() -> None:
    barrier = AsyncStartBarrier()
    scheduler = ChildScheduler(max_children=3)
    operations = {}
    for task_id in ("one", "two", "three", "four"):
        scheduler.submit(task_id, priority=1)
        operations[task_id] = lambda task_id=task_id: barrier.worker(task_id)

    running = asyncio.create_task(scheduler.run(operations))
    await barrier.wait_for_started(3)
    assert barrier.started == ["one", "two", "three"]
    barrier.release("one")
    await barrier.wait_for_started(4)
    assert barrier.started[-1] == "four"
    for task_id in ("two", "three", "four"):
        barrier.release(task_id)
    assert await running == {
        "one": "result:one", "two": "result:two",
        "three": "result:three", "four": "result:four",
    }
