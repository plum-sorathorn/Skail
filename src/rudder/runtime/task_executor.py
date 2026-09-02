from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from rudder.runtime.errors import FrameworkContractError


class TaskExecutionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class TaskRequest:
    task_id: str
    description: str
    subagent_type: str


@dataclass(frozen=True)
class TaskHandle:
    task_id: str


@dataclass(frozen=True)
class TaskSnapshot:
    task_id: str
    status: TaskExecutionStatus


@dataclass(frozen=True)
class TaskExecutionResult:
    task_id: str
    value: Any


class TaskExecutor(Protocol):
    async def start(self, request: TaskRequest) -> TaskHandle: ...

    async def status(self, task_id: str) -> TaskSnapshot: ...

    async def update(self, task_id: str, message: str) -> None: ...

    async def cancel(self, task_id: str) -> None: ...

    async def result(self, task_id: str) -> TaskExecutionResult: ...


Runner = Callable[[TaskRequest], Awaitable[Any]]


class ForegroundTaskExecutor:
    """In-process foreground executor with whole-task cooperative cancellation."""

    def __init__(self, runner: Runner) -> None:
        self._runner = runner
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    async def start(self, request: TaskRequest) -> TaskHandle:
        if request.task_id in self._tasks:
            raise FrameworkContractError(
                "task.duplicate_id", "task ID is already registered", task_id=request.task_id
            )
        async def invoke() -> Any:
            return await self._runner(request)

        self._tasks[request.task_id] = asyncio.create_task(
            invoke(), name=f"rudder-task-{request.task_id}"
        )
        return TaskHandle(task_id=request.task_id)

    async def status(self, task_id: str) -> TaskSnapshot:
        task = self._get(task_id)
        if task.cancelled():
            status = TaskExecutionStatus.CANCELLED
        elif not task.done():
            status = TaskExecutionStatus.RUNNING
        elif task.exception() is None:
            status = TaskExecutionStatus.SUCCEEDED
        else:
            status = TaskExecutionStatus.FAILED
        return TaskSnapshot(task_id=task_id, status=status)

    async def update(self, task_id: str, message: str) -> None:
        self._get(task_id)
        raise FrameworkContractError(
            "task.foreground_update_unsupported",
            "foreground synchronous tasks cannot be steered individually",
            task_id=task_id,
        )

    async def cancel(self, task_id: str) -> None:
        task = self._get(task_id)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def result(self, task_id: str) -> TaskExecutionResult:
        return TaskExecutionResult(task_id=task_id, value=await self._get(task_id))

    def _get(self, task_id: str) -> asyncio.Task[Any]:
        try:
            return self._tasks[task_id]
        except KeyError as exc:
            raise FrameworkContractError(
                "task.unknown", "task ID is not registered", task_id=task_id
            ) from exc


class BackgroundTaskExecutor:
    """Explicit Phase 1 boundary for preview support that is not stable-enabled."""

    experimental = True

    async def start(self, request: TaskRequest) -> TaskHandle:
        raise self._unavailable(request.task_id)

    async def status(self, task_id: str) -> TaskSnapshot:
        raise self._unavailable(task_id)

    async def update(self, task_id: str, message: str) -> None:
        raise self._unavailable(task_id)

    async def cancel(self, task_id: str) -> None:
        raise self._unavailable(task_id)

    async def result(self, task_id: str) -> TaskExecutionResult:
        raise self._unavailable(task_id)

    @staticmethod
    def _unavailable(task_id: str) -> FrameworkContractError:
        return FrameworkContractError(
            "runtime.background_experimental",
            "background task execution is experimental and disabled",
            task_id=task_id,
        )
