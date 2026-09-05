from __future__ import annotations

import pytest

from rudder.agents.profiles import builtin_profiles
from rudder.domain.ids import new_run_id
from rudder.domain.tasks import TaskRequest, TaskStatus
from rudder.runtime.task_registry import TaskRegistry
from rudder.runtime.task_validation import TaskValidationError, TaskValidator


def _validator(tmp_path) -> TaskValidator:
    return TaskValidator(
        profiles=builtin_profiles(),
        workspace_root=tmp_path,
        max_depth=1,
        background_enabled=False,
    )


def _spec(validator: TaskValidator, *, depends_on: tuple[str, ...] = ()):
    return validator.create_spec(
        TaskRequest(description="Inspect the task registry", depends_on=depends_on),
        run_id=new_run_id(),
        parent_task_id=None,
        parent_depth=0,
        workspace_revision="git:abc123",
    )


def test_registry_rejects_missing_dependencies_and_cycles_deterministically(tmp_path) -> None:
    validator = _validator(tmp_path)
    registry = TaskRegistry()
    first = _spec(validator)
    dependent = _spec(validator, depends_on=(first.task_id,))

    with pytest.raises(TaskValidationError, match="^task.dependency_missing$"):
        registry.register(dependent)

    cyclic_first = first.model_copy(
        update={"request": TaskRequest(description="first", depends_on=(dependent.task_id,))}
    )
    with pytest.raises(TaskValidationError, match="^task.dependency_cycle$"):
        registry.register_many((cyclic_first, dependent))


def test_registry_rejects_duplicate_normalized_fingerprints_in_one_batch(tmp_path) -> None:
    validator = _validator(tmp_path)
    run_id = new_run_id()
    first = validator.create_spec(
        TaskRequest(description="Inspect   routing", profile="explorer"),
        run_id=run_id,
        parent_task_id=None,
        parent_depth=0,
        workspace_revision="git:abc123",
    )
    duplicate = validator.create_spec(
        TaskRequest(description=" Inspect routing ", profile="explorer"),
        run_id=run_id,
        parent_task_id=None,
        parent_depth=0,
        workspace_revision="git:abc123",
    )

    with pytest.raises(TaskValidationError, match="^task.fingerprint_duplicate$"):
        TaskRegistry().register_many((first, duplicate))


def test_registry_tracks_dependencies_and_compare_and_set_task_state(tmp_path) -> None:
    validator = _validator(tmp_path)
    registry = TaskRegistry()
    first = _spec(validator)
    dependent = _spec(validator, depends_on=(first.task_id,))

    registry.register_many((first, dependent))
    assert registry.dependencies_for(dependent.task_id) == (first.task_id,)
    assert registry.transition(
        first.task_id,
        expected=TaskStatus.PROPOSED,
        target=TaskStatus.QUEUED,
    ).status is TaskStatus.QUEUED
    with pytest.raises(TaskValidationError, match="^task.state_conflict$"):
        registry.transition(
            first.task_id,
            expected=TaskStatus.PROPOSED,
            target=TaskStatus.QUEUED,
        )


def test_registry_rejects_a_terminally_unsuccessful_dependency(tmp_path) -> None:
    validator = _validator(tmp_path)
    registry = TaskRegistry()
    first = _spec(validator)
    registry.register(first)
    registry.transition(
        first.task_id,
        expected=TaskStatus.PROPOSED,
        target=TaskStatus.BLOCKED,
    )

    with pytest.raises(TaskValidationError, match="^task.dependency_unsuccessful$"):
        registry.register(_spec(validator, depends_on=(first.task_id,)))


def test_registry_derives_child_depth_from_a_registered_parent(tmp_path) -> None:
    validator = _validator(tmp_path)
    registry = TaskRegistry()
    parent = _spec(validator)
    forged_child = _spec(validator).model_copy(update={"parent_task_id": parent.task_id})
    registry.register(parent)

    with pytest.raises(TaskValidationError, match="^task.depth_invalid$"):
        registry.register(forged_child)


def test_exhausted_failed_fingerprint_blocks_a_third_automatic_attempt_or_task_loop(
    tmp_path,
) -> None:
    validator = _validator(tmp_path)
    registry = TaskRegistry()
    first = _spec(validator)
    registry.register(first)

    registry.transition(first.task_id, expected=TaskStatus.PROPOSED, target=TaskStatus.QUEUED)
    registry.transition(first.task_id, expected=TaskStatus.QUEUED, target=TaskStatus.RUNNING)
    registry.transition(first.task_id, expected=TaskStatus.RUNNING, target=TaskStatus.FAILED)
    assert registry.record_failed_automatic_attempt(first.task_id) == 1
    registry.transition(
        first.task_id,
        expected=TaskStatus.FAILED,
        target=TaskStatus.QUEUED,
        attempt_number=1,
    )
    registry.transition(first.task_id, expected=TaskStatus.QUEUED, target=TaskStatus.RUNNING)
    registry.transition(
        first.task_id,
        expected=TaskStatus.RUNNING,
        target=TaskStatus.RETURNED_TO_LEAD,
    )
    assert registry.record_failed_automatic_attempt(first.task_id) == 2

    repeated = _spec(validator)
    with pytest.raises(TaskValidationError, match="^task.fingerprint_exhausted$"):
        registry.register(repeated)


def test_duplicate_terminal_transition_records_a_diagnostic(tmp_path) -> None:
    validator = _validator(tmp_path)
    registry = TaskRegistry()
    first = _spec(validator)
    registry.register(first)
    registry.transition(first.task_id, expected=TaskStatus.PROPOSED, target=TaskStatus.BLOCKED)

    registry.transition(first.task_id, expected=TaskStatus.BLOCKED, target=TaskStatus.BLOCKED)

    assert registry.diagnostics == (("task.terminal_transition_duplicate", first.task_id),)


def test_task_registry_loads_failed_fingerprints_from_journal(tmp_path) -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    from rudder.sessions.journal import Journal

    journal = Journal(tmp_path / "journal.db")
    journal.migrate()
    now = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    session_id = "11111111-1111-4111-8111-111111111111"
    run_id = "22222222-2222-4222-8222-222222222222"
    task_id = "33333333-3333-4333-8333-333333333333"

    journal.create_session(session_id=session_id, title="test", created_at=now)
    journal.create_run(
        run_id=run_id,
        session_id=session_id,
        status="running",
        budget_limit_usd=Decimal("2.00"),
        created_at=now,
    )

    validator = _validator(tmp_path)
    spec = validator.create_spec(
        TaskRequest(description="Exhaust me"),
        run_id=new_run_id(),
        parent_task_id=None,
        parent_depth=0,
        workspace_revision="git:abc",
    )

    journal.create_task(
        task_id=task_id,
        run_id=run_id,
        description="Exhaust me",
        status="returned_to_lead",
        fingerprint=spec.fingerprint,
        idempotency_key="t1",
        created_at=now,
    )
    journal.create_attempt(
        attempt_id="44444444-4444-4444-8444-444444444441",
        task_id=task_id,
        number=1,
        status="failed",
        idempotency_key="a1",
        created_at=now,
    )
    journal.create_attempt(
        attempt_id="44444444-4444-4444-8444-444444444442",
        task_id=task_id,
        number=2,
        status="failed",
        idempotency_key="a2",
        created_at=now,
    )

    new_registry = TaskRegistry()
    new_registry.load_from_journal(journal, session_id)

    with pytest.raises(TaskValidationError, match="^task.fingerprint_exhausted$"):
        new_registry.register(spec)
