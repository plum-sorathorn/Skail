from __future__ import annotations

import asyncio

import pytest
from fakes.barriers import AsyncStartBarrier

from rudder.domain.tasks import TaskResult
from rudder.runtime.scheduler import ChildScheduler


@pytest.mark.asyncio
async def test_failed_dependency_propagates_blocked_result() -> None:
    scheduler = ChildScheduler(max_children=3)
    scheduler.submit("parent", priority=1)
    scheduler.submit("child", priority=1, depends_on=("parent",))

    async def fail_parent() -> TaskResult:
        return TaskResult(
            task_id="11111111-1111-4111-8111-111111111111",  # type: ignore[arg-type]
            status="failed",
            summary="parent failure",
        )

    async def child_op() -> str:
        return "child ran"

    results = await scheduler.run({"parent": fail_parent, "child": child_op})
    assert results["parent"].status == "failed"
    assert results["child"].status == "blocked"
    assert "dependency_blocked" in results["child"].summary


@pytest.mark.asyncio
async def test_cancelled_dependency_propagates_blocked_result() -> None:
    scheduler = ChildScheduler(max_children=3)
    scheduler.submit("parent", priority=1)
    scheduler.submit("child", priority=1, depends_on=("parent",))

    scheduler.cancel("parent")
    assert scheduler.blocked["child"] == "dependency_cancelled"

    results = await scheduler.run({"child": lambda: asyncio.sleep(0)})
    assert results["child"].status == "blocked"
    assert "dependency_cancelled" in results["child"].summary


@pytest.mark.asyncio
async def test_approval_wait_releases_slot_and_resumes_when_approved() -> None:
    barrier = AsyncStartBarrier()
    scheduler = ChildScheduler(max_children=1)
    scheduler.submit("waiting", priority=10, awaiting_approval=True)
    scheduler.submit("ready", priority=1)

    operations = {
        "waiting": lambda: barrier.worker("waiting"),
        "ready": lambda: barrier.worker("ready"),
    }

    running = asyncio.create_task(scheduler.run(operations))
    await barrier.wait_for_started(1)
    assert barrier.started == ["ready"]

    # Now approve the waiting task and release ready
    scheduler.approve("waiting")
    barrier.release("ready")

    await barrier.wait_for_started(2)
    assert barrier.started == ["ready", "waiting"]
    barrier.release("waiting")

    results = await running
    assert results == {"ready": "result:ready", "waiting": "result:waiting"}


@pytest.mark.asyncio
async def test_scheduler_priority_and_creation_ordering_with_barrier() -> None:
    barrier = AsyncStartBarrier()
    scheduler = ChildScheduler(max_children=2)

    scheduler.submit("first-low", priority=1)
    scheduler.submit("second-high", priority=5)
    scheduler.submit("third-high", priority=5)

    operations = {
        "first-low": lambda: barrier.worker("first-low"),
        "second-high": lambda: barrier.worker("second-high"),
        "third-high": lambda: barrier.worker("third-high"),
    }

    running = asyncio.create_task(scheduler.run(operations))
    await barrier.wait_for_started(2)
    # The two high-priority tasks must start first, in creation order
    assert barrier.started == ["second-high", "third-high"]

    barrier.release("second-high")
    await barrier.wait_for_started(3)
    assert barrier.started[-1] == "first-low"

    barrier.release("third-high")
    barrier.release("first-low")
    await running


@pytest.mark.asyncio
async def test_direct_compiled_dispatch_uses_ordered_scheduler_queue() -> None:
    barrier = AsyncStartBarrier()
    scheduler = ChildScheduler(max_children=1)
    scheduler.submit("low", priority=1)
    scheduler.submit("high", priority=10)

    high = asyncio.create_task(scheduler.execute("high", lambda: barrier.worker("high")))
    low = asyncio.create_task(scheduler.execute("low", lambda: barrier.worker("low")))
    await barrier.wait_for_started(1)
    assert barrier.started == ["high"]
    barrier.release("high")
    await barrier.wait_for_started(2)
    assert barrier.started == ["high", "low"]
    barrier.release("low")

    assert await high == "result:high"
    assert await low == "result:low"


@pytest.mark.asyncio
async def test_direct_dispatch_wakes_when_approval_arrives() -> None:
    scheduler = ChildScheduler(max_children=1)
    scheduler.submit("waiting", priority=1, awaiting_approval=True)
    started = asyncio.Event()

    async def operation() -> str:
        started.set()
        return "approved"

    running = asyncio.create_task(scheduler.execute("waiting", operation))
    await asyncio.sleep(0)
    assert not started.is_set()
    scheduler.approve("waiting")

    assert await running == "approved"
    assert started.is_set()
