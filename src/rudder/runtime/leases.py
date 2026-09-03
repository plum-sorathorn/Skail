from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from threading import Condition, Event

from rudder.tools.registry import SideEffect


def write_capable(side_effects: tuple[SideEffect, ...]) -> bool:
    return any(effect is not SideEffect.READ_ONLY for effect in side_effects)


class WorkspaceLeaseManager:
    """A run-scoped, re-entrant owner lease shared by sync and async tool paths."""

    def __init__(self) -> None:
        self._condition = Condition()
        self._holder: str | None = None
        self._depth = 0

    @property
    def holder(self) -> str | None:
        with self._condition:
            return self._holder

    @asynccontextmanager
    async def acquire(self, owner: str) -> AsyncIterator[None]:
        cancelled = Event()
        acquired = False
        task = asyncio.create_task(asyncio.to_thread(self._acquire, owner, cancelled))
        try:
            acquired = await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled.set()
            with self._condition:
                self._condition.notify_all()
            acquired = await task
            if acquired:
                self.release(owner)
            raise
        if not acquired:
            raise asyncio.CancelledError
        try:
            yield
        finally:
            self.release(owner)

    @contextmanager
    def hold(self, owner: str) -> Iterator[None]:
        acquired = self._acquire(owner, Event())
        assert acquired
        try:
            yield
        finally:
            self.release(owner)

    def release(self, owner: str) -> None:
        with self._condition:
            if self._holder != owner:
                return
            self._depth -= 1
            if self._depth == 0:
                self._holder = None
                self._condition.notify_all()

    def recover_stale(self, owner: str) -> bool:
        with self._condition:
            if self._holder != owner:
                return False
            self._holder = None
            self._depth = 0
            self._condition.notify_all()
            return True

    def _acquire(self, owner: str, cancelled: Event) -> bool:
        with self._condition:
            self._condition.wait_for(
                lambda: cancelled.is_set() or self._holder in {None, owner}
            )
            if cancelled.is_set():
                return False
            self._holder = owner
            self._depth += 1
            return True
