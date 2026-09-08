from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from rudder.domain.changesets import (
    ChangeSet,
    ChangeSetPath,
    ChangeSetStatus,
    ContentImage,
)
from rudder.domain.events import SecretRedactor
from rudder.sessions import Journal, JournalIdempotencyError

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
SESSION_ID = "11111111-1111-4111-8111-111111111111"
RUN_ID = "22222222-2222-4222-8222-222222222222"
TASK_ID = "33333333-3333-4333-8333-333333333333"
ATTEMPT_ID = "44444444-4444-4444-8444-444444444444"
CHANGESET_ID = "55555555-5555-4555-8555-555555555555"
OPERATION_ID = "66666666-6666-4666-8666-666666666666"
SNAPSHOT_ID = "a" * 64
HEAD = "b" * 40
DIGEST = "c" * 64


def _changeset(**updates: object) -> ChangeSet:
    values: dict[str, object] = {
        "schema_version": 1,
        "changeset_id": CHANGESET_ID,
        "task_id": TASK_ID,
        "attempt_id": ATTEMPT_ID,
        "snapshot_id": SNAPSHOT_ID,
        "base_head": HEAD,
        "declared_scope": ("src",),
        "paths": (
            ChangeSetPath(
                path="src/example.py",
                effect="modified",
                before=ContentImage(digest=DIGEST, size=1, artifact_ref="snapshot:file"),
                after=ContentImage(digest=DIGEST, size=1, artifact_ref="blob:file"),
            ),
        ),
    }
    values.update(updates)
    return ChangeSet.model_validate(values)


def _seed_attempt(journal: Journal) -> None:
    journal.create_session(session_id=SESSION_ID, title="Changeset", created_at=NOW)
    journal.create_run(
        run_id=RUN_ID,
        session_id=SESSION_ID,
        status="running",
        budget_limit_usd=Decimal("1.00"),
        created_at=NOW,
    )
    journal.create_task(
        task_id=TASK_ID,
        run_id=RUN_ID,
        description="Isolated write",
        status="running",
        idempotency_key="task:changeset",
        created_at=NOW,
    )
    journal.create_attempt(
        attempt_id=ATTEMPT_ID,
        task_id=TASK_ID,
        number=1,
        status="running",
        idempotency_key="attempt:changeset",
        created_at=NOW,
    )


def test_changeset_rejects_effects_outside_the_declared_scope() -> None:
    with pytest.raises(ValueError, match="changeset.path_outside_declared_scope"):
        _changeset(
            paths=(
                ChangeSetPath(
                    path="docs/unsafe.md",
                    effect="added",
                    after=ContentImage(digest=DIGEST, size=1, artifact_ref="blob:file"),
                ),
            )
        )


def test_changeset_requires_recoverable_images_for_each_effect() -> None:
    with pytest.raises(ValueError, match="changeset.effect_images_invalid"):
        _changeset(
            paths=(
                ChangeSetPath(path="src/example.py", effect="modified"),
            )
        )


def test_changeset_rejects_non_portable_paths_and_non_regular_effects() -> None:
    with pytest.raises(ValueError, match="changeset.path_invalid"):
        _changeset(declared_scope=("C:/unsafe",))
    with pytest.raises(ValueError):
        _changeset(
            paths=(
                ChangeSetPath(
                    path="src/example.py",
                    effect="modified",
                    file_type="symlink",  # type: ignore[arg-type]
                    before=ContentImage(digest=DIGEST, size=1, artifact_ref="snapshot:file"),
                    after=ContentImage(digest=DIGEST, size=1, artifact_ref="blob:file"),
                ),
            )
        )


def test_changeset_is_persisted_idempotently_and_rejects_conflicting_retries(
    tmp_path: Path,
) -> None:
    journal = Journal(tmp_path / "rudder.sqlite")
    journal.migrate()
    _seed_attempt(journal)
    changeset = _changeset()

    journal.record_changeset(changeset=changeset, idempotency_key="changeset:attempt")
    journal.record_changeset(changeset=changeset, idempotency_key="changeset:attempt")

    persisted = journal.get_changeset(CHANGESET_ID)
    assert persisted.changeset == changeset
    assert persisted.status is ChangeSetStatus.CAPTURED

    with pytest.raises(JournalIdempotencyError):
        journal.record_changeset(
            changeset=_changeset(changeset_id="66666666-6666-4666-8666-666666666666"),
            idempotency_key="changeset:attempt",
        )


def test_changeset_transition_replays_only_the_same_durable_operation(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "rudder.sqlite")
    journal.migrate()
    _seed_attempt(journal)
    journal.record_changeset(changeset=_changeset(), idempotency_key="changeset:attempt")

    journal.transition_changeset_status(
        changeset_id=CHANGESET_ID,
        expected=ChangeSetStatus.CAPTURED,
        target=ChangeSetStatus.APPLYING,
        operation_id=OPERATION_ID,
        updated_at=NOW,
    )
    journal.transition_changeset_status(
        changeset_id=CHANGESET_ID,
        expected=ChangeSetStatus.CAPTURED,
        target=ChangeSetStatus.APPLYING,
        operation_id=OPERATION_ID,
        updated_at=NOW,
    )
    assert journal.get_changeset(CHANGESET_ID).status is ChangeSetStatus.APPLYING

    with pytest.raises(JournalIdempotencyError):
        journal.transition_changeset_status(
            changeset_id=CHANGESET_ID,
            expected=ChangeSetStatus.APPLYING,
            target=ChangeSetStatus.BLOCKED,
            operation_id=OPERATION_ID,
            updated_at=NOW,
        )


def test_changeset_rejects_a_payload_that_redaction_would_mutate(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "rudder.sqlite", redactor=SecretRedactor(["blob:file"]))
    journal.migrate()
    _seed_attempt(journal)

    with pytest.raises(ValueError, match="changeset.payload_redacted"):
        journal.record_changeset(changeset=_changeset(), idempotency_key="changeset:attempt")
