from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field


@dataclass
class AsyncStartBarrier:
    """Records starts and holds tasks until a test releases them."""

    started: list[str] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._condition = asyncio.Condition()
        self._release: dict[str, asyncio.Event] = {}

    async def worker(self, task_id: str) -> str:
        release = self._release.setdefault(task_id, asyncio.Event())
        async with self._condition:
            self.started.append(task_id)
            self._condition.notify_all()
        try:
            await release.wait()
        except asyncio.CancelledError:
            async with self._condition:
                self.cancelled.append(task_id)
                self._condition.notify_all()
            raise
        async with self._condition:
            self.completed.append(task_id)
            self._condition.notify_all()
        return f"result:{task_id}"

    async def wait_for_started(self, count: int) -> None:
        async with self._condition:
            await self._condition.wait_for(lambda: len(self.started) >= count)

    async def wait_for_completed(self, count: int) -> None:
        async with self._condition:
            await self._condition.wait_for(lambda: len(self.completed) >= count)

    def release(self, task_id: str) -> None:
        self._release.setdefault(task_id, asyncio.Event()).set()

    def runner(self) -> Callable[[str], Awaitable[str]]:
        return self.worker
