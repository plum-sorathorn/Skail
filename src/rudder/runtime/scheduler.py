from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from rudder.domain.ids import TaskId, ensure_uuid4, new_task_id
from rudder.domain.tasks import TaskResult
from rudder.runtime.deepagents_adapter import ChildRunGate


@dataclass(frozen=True)
class ScheduledChild:
    task_id: str
    priority: int
    creation_order: int
    depends_on: tuple[str, ...]
    awaiting_approval: bool


class ChildScheduler:
    """Deterministically orders ready child work ahead of the execution gate."""

    def __init__(self, *, max_children: int = 3) -> None:
        if not 1 <= max_children <= 3:
            raise ValueError("max_children must be between 1 and 3")
        self.max_children = max_children
        self.gate = ChildRunGate(max_children)
        self._children: dict[str, ScheduledChild] = {}
        self._completed: set[str] = set()
        self._failed: set[str] = set()
        self._running: set[str] = set()
        self._condition = asyncio.Condition()
        self.blocked: dict[str, str] = {}

    def submit(
        self,
        task_id: str,
        *,
        priority: int,
        depends_on: tuple[str, ...] = (),
        awaiting_approval: bool = False,
    ) -> None:
        if task_id in self._children:
            raise ValueError("scheduler duplicate task ID")
        if any(dependency not in self._children for dependency in depends_on):
            raise ValueError("scheduler dependency is missing")
        self._children[task_id] = ScheduledChild(
            task_id, priority, len(self._children), depends_on, awaiting_approval
        )
        self._wake_waiters()

    def finish(self, task_id: str, *, succeeded: bool) -> None:
        if task_id not in self._children:
            raise ValueError("scheduler task is unknown")
        if succeeded:
            self._completed.add(task_id)
            self._wake_waiters()
            return
        self._failed.add(task_id)
        self._block_dependents(task_id)
        self._wake_waiters()

    def cancel(self, task_id: str) -> None:
        if task_id not in self._children:
            raise ValueError("scheduler task is unknown")
        self._failed.add(task_id)
        self._block_dependents(task_id, reason="dependency_cancelled")
        self._wake_waiters()

    def approve(self, task_id: str) -> None:
        child = self._children[task_id]
        self._children[task_id] = ScheduledChild(
            child.task_id, child.priority, child.creation_order, child.depends_on, False
        )
        self._wake_waiters()

    def retry(self, task_id: str) -> None:
        if task_id not in self._children:
            raise ValueError("scheduler task is unknown")
        self._failed.discard(task_id)
        self._wake_waiters()

    def _wake_waiters(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._notify_waiters())

    async def _notify_waiters(self) -> None:
        async with self._condition:
            self._condition.notify_all()

    def ready(self) -> tuple[str, ...]:
        candidates = (
            child
            for child in self._children.values()
            if not child.awaiting_approval
            and child.task_id not in self._completed
            and child.task_id not in self._failed
            and child.task_id not in self._running
            and child.task_id not in self.blocked
            and all(dependency in self._completed for dependency in child.depends_on)
        )
        return tuple(
            child.task_id
            for child in sorted(
                candidates,
                key=lambda child: (-child.priority, child.creation_order),
            )
        )

    async def execute(
        self,
        task_id: str,
        operation: Callable[[], Awaitable[Any]],
        *,
        final_failure: bool = True,
    ) -> Any:
        if task_id not in self._children:
            raise ValueError("scheduler task is unknown")
        async with self._condition:
            await self._condition.wait_for(
                lambda: task_id in self.blocked
                or (
                    task_id in self.ready()
                    and self.ready().index(task_id)
                    < self.max_children - len(self._running)
                )
            )
            if task_id in self.blocked:
                return self._make_blocked_result(task_id, self.blocked[task_id])
            self._running.add(task_id)
        try:
            result = await self.gate.run(task_id, operation)
            succeeded = not isinstance(result, TaskResult) or result.status == "succeeded"
            if succeeded:
                self.finish(task_id, succeeded=True)
            elif final_failure or result.status != "failed":
                self.finish(task_id, succeeded=False)
            return result
        except BaseException:
            self.finish(task_id, succeeded=False)
            raise
        finally:
            async with self._condition:
                self._running.discard(task_id)
                self._condition.notify_all()

    async def run(
        self,
        operations: Mapping[str, Callable[[], Awaitable[Any]]],
    ) -> dict[str, Any | BaseException]:
        pending = set(operations)
        running: dict[asyncio.Task[Any], str] = {}
        results: dict[str, Any | BaseException] = {}
        while pending or running:
            # Propagate blocked results to any pending operations whose dependencies failed
            for blocked_id in list(pending & set(self.blocked)):
                reason = self.blocked[blocked_id]
                results[blocked_id] = self._make_blocked_result(blocked_id, reason)
                pending.remove(blocked_id)

            capacity = self.max_children - len(running)
            for task_id in self.ready():
                if capacity == 0:
                    break
                if task_id not in pending:
                    continue
                task = asyncio.create_task(
                    self.gate.run(task_id, operations[task_id]),
                    name=f"rudder-scheduled-{task_id}",
                )
                running[task] = task_id
                self._running.add(task_id)
                pending.remove(task_id)
                capacity -= 1
            if not running:
                # Any remaining pending operations that cannot run are blocked
                for remaining_id in list(pending):
                    reason = self.blocked.get(remaining_id, "dependency_unsuccessful")
                    results[remaining_id] = self._make_blocked_result(remaining_id, reason)
                    pending.remove(remaining_id)
                break
            done, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task_id = running.pop(task)
                self._running.discard(task_id)
                try:
                    res = task.result()
                    results[task_id] = res
                    is_success = True
                    if isinstance(res, TaskResult) and res.status != "succeeded":
                        is_success = False
                    self.finish(task_id, succeeded=is_success)
                except BaseException as error:
                    results[task_id] = error
                    self.finish(task_id, succeeded=False)
        return results

    def _block_dependents(self, task_id: str, *, reason: str = "dependency_unsuccessful") -> None:
        for child in self._children.values():
            if task_id in child.depends_on:
                self.blocked[child.task_id] = reason
                self._block_dependents(child.task_id, reason=reason)

    @staticmethod
    def _make_blocked_result(task_id: str, reason: str) -> Any:
        try:
            ensure_uuid4(task_id)
            valid_id = TaskId(task_id)
        except Exception:
            valid_id = new_task_id()
        return TaskResult(
            task_id=valid_id,
            status="blocked",
            summary=f"dependency_blocked: {reason}",
            follow_up="dependency did not succeed",
        )
