from __future__ import annotations

from typing import Any

from skail.runtime.task_executor import (
    TaskExecutionResult,
    TaskExecutionStatus,
    TaskHandle,
    TaskRequest,
    TaskSnapshot,
)


class FakeTaskExecutor:
    """Small deterministic implementation of Skail's TaskExecutor port."""

    def __init__(self, values: dict[str, Any]) -> None:
        self._values = values
        self._statuses: dict[str, TaskExecutionStatus] = {}
        self.updates: dict[str, list[str]] = {}

    async def start(self, request: TaskRequest) -> TaskHandle:
        self._statuses[request.task_id] = TaskExecutionStatus.SUCCEEDED
        self.updates[request.task_id] = []
        return TaskHandle(task_id=request.task_id)

    async def status(self, task_id: str) -> TaskSnapshot:
        return TaskSnapshot(task_id=task_id, status=self._statuses[task_id])

    async def update(self, task_id: str, message: str) -> None:
        self.updates[task_id].append(message)

    async def cancel(self, task_id: str) -> None:
        self._statuses[task_id] = TaskExecutionStatus.CANCELLED

    async def result(self, task_id: str) -> TaskExecutionResult:
        return TaskExecutionResult(task_id=task_id, value=self._values[task_id])

