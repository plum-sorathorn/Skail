from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any

from rudder.domain.ids import TaskId
from rudder.domain.tasks import (
    TERMINAL_TASK_STATUSES,
    DomainTransitionError,
    TaskSpec,
    TaskStatus,
    transition_task,
)
from rudder.runtime.task_validation import TaskValidationError


@dataclass(frozen=True)
class RegisteredTask:
    spec: TaskSpec
    status: TaskStatus = TaskStatus.PROPOSED


class TaskRegistry:
    """Own task identity, dependency integrity, and compare-and-set lifecycle state."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._tasks: dict[TaskId, RegisteredTask] = {}
        self._failed_fingerprint_attempts: dict[str, int] = {}
        self._diagnostics: list[tuple[str, TaskId]] = []

    def register(self, spec: TaskSpec) -> RegisteredTask:
        return self.register_many((spec,))[0]

    def register_many(self, specs: tuple[TaskSpec, ...]) -> tuple[RegisteredTask, ...]:
        with self._lock:
            task_ids = tuple(spec.task_id for spec in specs)
            if len(set(task_ids)) != len(task_ids) or any(
                task_id in self._tasks for task_id in task_ids
            ):
                raise TaskValidationError("task.id_duplicate")
            fingerprints = tuple(spec.fingerprint for spec in specs)
            if any(
                self._failed_fingerprint_attempts.get(spec.fingerprint, 0) >= 2
                for spec in specs
            ):
                raise TaskValidationError("task.fingerprint_exhausted")
            combined = {task_id: task.spec for task_id, task in self._tasks.items()}
            combined.update({spec.task_id: spec for spec in specs})
            for spec in specs:
                if spec.task_id in spec.request.depends_on:
                    raise TaskValidationError("task.dependency_self")
                if any(dependency not in combined for dependency in spec.request.depends_on):
                    raise TaskValidationError("task.dependency_missing")
                if spec.parent_task_id is None and spec.depth != 1:
                    raise TaskValidationError("task.depth_invalid")
                if spec.parent_task_id is not None:
                    parent = combined.get(spec.parent_task_id)
                    if parent is None:
                        raise TaskValidationError("task.parent_missing")
                    if spec.depth != parent.depth + 1:
                        raise TaskValidationError("task.depth_invalid")
                if any(
                    self._tasks[dependency].status
                    in TERMINAL_TASK_STATUSES - {TaskStatus.SUCCEEDED}
                    for dependency in spec.request.depends_on
                    if dependency in self._tasks
                ):
                    raise TaskValidationError("task.dependency_unsuccessful")
            if _has_dependency_cycle(combined):
                raise TaskValidationError("task.dependency_cycle")
            existing_fingerprints = {
                registered.spec.fingerprint for registered in self._tasks.values()
            }
            if (
                len(set(fingerprints)) != len(fingerprints)
                or not set(fingerprints).isdisjoint(existing_fingerprints)
            ):
                raise TaskValidationError("task.fingerprint_duplicate")
            registered = tuple(RegisteredTask(spec) for spec in specs)
            self._tasks.update({task.spec.task_id: task for task in registered})
            return registered

    def get(self, task_id: TaskId) -> RegisteredTask:
        with self._lock:
            try:
                return self._tasks[task_id]
            except KeyError as error:
                raise TaskValidationError("task.unknown") from error

    def dependencies_for(self, task_id: TaskId) -> tuple[TaskId, ...]:
        return self.get(task_id).spec.request.depends_on

    def transition(
        self,
        task_id: TaskId,
        *,
        expected: TaskStatus,
        target: TaskStatus,
        attempt_number: int = 1,
    ) -> RegisteredTask:
        with self._lock:
            current = self.get(task_id)
            if current.status is not expected:
                raise TaskValidationError("task.state_conflict")
            if current.status is target and current.status in TERMINAL_TASK_STATUSES:
                self._diagnostics.append(("task.terminal_transition_duplicate", task_id))
                return current
            try:
                status = transition_task(current.status, target, attempt_number=attempt_number)
            except DomainTransitionError as error:
                raise TaskValidationError("task.transition_invalid") from error
            updated = RegisteredTask(spec=current.spec, status=status)
            self._tasks[task_id] = updated
            return updated

    def record_failed_automatic_attempt(self, task_id: TaskId) -> int:
        with self._lock:
            task = self.get(task_id)
            if task.status not in {TaskStatus.FAILED, TaskStatus.RETURNED_TO_LEAD}:
                raise TaskValidationError("task.attempt_not_failed")
            count = self._failed_fingerprint_attempts.get(task.spec.fingerprint, 0)
            if count >= 2:
                raise TaskValidationError("task.fingerprint_exhausted")
            count += 1
            self._failed_fingerprint_attempts[task.spec.fingerprint] = count
            return count

    def load_from_journal(self, journal: Any, session_id: str) -> None:
        with self._lock:
            with journal.transaction() as tx:
                attempt_rows = tx.connection.execute(
                    "SELECT t.fingerprint, COUNT(DISTINCT a.attempt_id) as failure_count "
                    "FROM tasks t "
                    "JOIN attempts a ON a.task_id = t.task_id "
                    "JOIN runs r ON r.run_id = t.run_id "
                    "WHERE r.session_id = ? AND a.status IN ('failed', 'interrupted') "
                    "GROUP BY t.fingerprint",
                    (session_id,),
                ).fetchall()
                for row in attempt_rows:
                    self._failed_fingerprint_attempts[row["fingerprint"]] = max(
                        self._failed_fingerprint_attempts.get(row["fingerprint"], 0),
                        int(row["failure_count"]),
                    )
                task_rows = tx.connection.execute(
                    "SELECT t.fingerprint, COUNT(t.task_id) as task_count "
                    "FROM tasks t "
                    "JOIN runs r ON r.run_id = t.run_id "
                    "WHERE r.session_id = ? AND t.status = 'returned_to_lead' "
                    "GROUP BY t.fingerprint",
                    (session_id,),
                ).fetchall()
                for row in task_rows:
                    self._failed_fingerprint_attempts[row["fingerprint"]] = max(
                        self._failed_fingerprint_attempts.get(row["fingerprint"], 0),
                        2,
                    )

    @property
    def diagnostics(self) -> tuple[tuple[str, TaskId], ...]:
        with self._lock:
            return tuple(self._diagnostics)


def _has_dependency_cycle(specs: dict[TaskId, TaskSpec]) -> bool:
    visiting: set[TaskId] = set()
    visited: set[TaskId] = set()

    def visit(task_id: TaskId) -> bool:
        if task_id in visiting:
            return True
        if task_id in visited:
            return False
        visiting.add(task_id)
        if any(visit(dependency) for dependency in specs[task_id].request.depends_on):
            return True
        visiting.remove(task_id)
        visited.add(task_id)
        return False

    return any(visit(task_id) for task_id in sorted(specs))
