from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest
from fakes.barriers import AsyncStartBarrier
from fakes.executors import FakeTaskExecutor

from rudder.runtime.errors import FrameworkContractError
from rudder.runtime.task_executor import (
    BackgroundTaskExecutor,
    ForegroundTaskExecutor,
    TaskExecutionStatus,
    TaskExecutor,
    TaskRequest,
)


async def assert_success_contract(
    executor: TaskExecutor,
    request: TaskRequest,
) -> None:
    handle = await executor.start(request)
    result = await executor.result(request.task_id)
    snapshot = await executor.status(request.task_id)

    assert handle.task_id == request.task_id
    assert result.task_id == request.task_id
    assert result.value == f"result:{request.task_id}"
    assert snapshot.status is TaskExecutionStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_fake_and_foreground_executors_share_the_success_contract() -> None:
    request = TaskRequest(
        task_id="executor-success",
        description="Run foreground work",
        subagent_type="tester",
    )
    fake = FakeTaskExecutor({request.task_id: f"result:{request.task_id}"})

    async def foreground_runner(current: TaskRequest) -> str:
        return f"result:{current.task_id}"

    await assert_success_contract(fake, request)
    await assert_success_contract(ForegroundTaskExecutor(foreground_runner), request)


@pytest.mark.asyncio
async def test_foreground_executor_reports_running_and_supports_cancellation() -> None:
    barrier = AsyncStartBarrier()

    async def runner(request: TaskRequest) -> str:
        return await barrier.worker(request.task_id)

    executor = ForegroundTaskExecutor(runner)
    request = TaskRequest(
        task_id="executor-cancel",
        description="Wait until cancelled",
        subagent_type="tester",
    )
    await executor.start(request)
    await barrier.wait_for_started(1)

    assert (await executor.status(request.task_id)).status is TaskExecutionStatus.RUNNING
    await executor.cancel(request.task_id)

    assert (await executor.status(request.task_id)).status is TaskExecutionStatus.CANCELLED
    assert barrier.cancelled == [request.task_id]
    with pytest.raises(asyncio.CancelledError):
        await executor.result(request.task_id)


@pytest.mark.asyncio
async def test_foreground_update_is_explicitly_unsupported() -> None:
    release = asyncio.Event()

    async def runner(request: TaskRequest) -> str:
        await release.wait()
        return request.task_id

    executor = ForegroundTaskExecutor(runner)
    request = TaskRequest(
        task_id="executor-update",
        description="Cannot be steered mid-run",
        subagent_type="tester",
    )
    await executor.start(request)
    try:
        with pytest.raises(FrameworkContractError) as raised:
            await executor.update(request.task_id, "change direction")
        assert raised.value.error.code == "task.foreground_update_unsupported"
    finally:
        release.set()
        await executor.result(request.task_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    [
        lambda executor, request: executor.start(request),
        lambda executor, request: executor.status(request.task_id),
        lambda executor, request: executor.update(request.task_id, "steer"),
        lambda executor, request: executor.cancel(request.task_id),
        lambda executor, request: executor.result(request.task_id),
    ],
)
async def test_background_executor_is_isolated_as_experimental_and_unavailable(
    operation: Callable[..., object],
) -> None:
    executor = BackgroundTaskExecutor()
    request = TaskRequest(
        task_id="background-disabled",
        description="Do not launch a server",
        subagent_type="researcher",
    )

    assert executor.experimental is True
    with pytest.raises(FrameworkContractError) as raised:
        await operation(executor, request)  # type: ignore[misc]
    assert raised.value.error.code == "runtime.background_experimental"


@pytest.mark.asyncio
async def test_background_unavailability_does_not_change_foreground_behavior() -> None:
    background = BackgroundTaskExecutor()
    request = TaskRequest(
        task_id="foreground-still-works",
        description="Use the stable path",
        subagent_type="general-purpose",
    )

    with pytest.raises(FrameworkContractError):
        await background.start(request)

    async def runner(current: TaskRequest) -> str:
        return f"result:{current.task_id}"

    await assert_success_contract(ForegroundTaskExecutor(runner), request)
