"""Serialized, recovery-aware canonical changeset integration."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from skail.domain.changesets import ChangeSet, ChangeSetStatus, ContentImage
from skail.runtime.workspace_capture import ImmutableArtifactStore, WorkspaceCaptureError
from skail.sessions.journal import Journal


class ChangeSetIntegrationError(ValueError):
    """A captured changeset cannot safely be integrated."""


class ChangeSetIntegrator:
    """Applies one captured changeset only after durable intent is recorded."""

    def __init__(self, *, journal: Journal, artifacts: ImmutableArtifactStore) -> None:
        self._journal = journal
        self._artifacts = artifacts

    def integrate(self, changeset_id: str, workspace: Path) -> ChangeSetStatus:
        persisted = self._journal.get_changeset(changeset_id)
        changeset = persisted.changeset
        if persisted.status is not ChangeSetStatus.CAPTURED:
            raise ChangeSetIntegrationError("changeset.integration_status_invalid")
        root = workspace.resolve(strict=True)
        try:
            self._validate_base(changeset, root)
        except ChangeSetIntegrationError:
            self._transition(changeset, ChangeSetStatus.CAPTURED, ChangeSetStatus.BLOCKED)
            return ChangeSetStatus.BLOCKED
        self._journal.begin_changeset_apply(
            changeset=changeset,
            operation_id=str(uuid4()),
        )
        try:
            for item in changeset.paths:
                target = self._target(root, item.path)
                if item.after is None:
                    target.unlink()
                else:
                    self._write_image(target, item.after)
                self._journal.mark_changeset_file_applied(
                    changeset_id=changeset.changeset_id,
                    path=item.path,
                )
            self._validate_after(changeset, root)
        except (OSError, WorkspaceCaptureError, ChangeSetIntegrationError):
            self._transition(changeset, ChangeSetStatus.APPLYING, ChangeSetStatus.IN_DOUBT)
            return ChangeSetStatus.IN_DOUBT
        self._transition(changeset, ChangeSetStatus.APPLYING, ChangeSetStatus.INTEGRATED)
        return ChangeSetStatus.INTEGRATED

    def recover(self, changeset_id: str) -> ChangeSetStatus:
        persisted = self._journal.get_changeset(changeset_id)
        if persisted.status is ChangeSetStatus.APPLYING:
            self._transition(
                persisted.changeset, ChangeSetStatus.APPLYING, ChangeSetStatus.IN_DOUBT
            )
            return ChangeSetStatus.IN_DOUBT
        return persisted.status

    def _validate_base(self, changeset: ChangeSet, root: Path) -> None:
        for item in changeset.paths:
            self._assert_image(self._target(root, item.path), item.before)

    def _validate_after(self, changeset: ChangeSet, root: Path) -> None:
        for item in changeset.paths:
            self._assert_image(self._target(root, item.path), item.after)

    def _write_image(self, target: Path, image: ContentImage) -> None:
        content = self._artifacts.read(image)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._assert_safe_path(target)
        temporary = target.with_name(f".{target.name}.skail-{uuid4().hex}")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb", closefd=True) as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _target(root: Path, relative: str) -> Path:
        target = root.joinpath(*PurePosixPath(relative).parts)
        existing_parent = target.parent
        while not existing_parent.exists():
            existing_parent = existing_parent.parent
        try:
            existing_parent.resolve(strict=True).relative_to(root)
        except (OSError, ValueError) as error:
            raise ChangeSetIntegrationError("changeset.integration_path_invalid") from error
        return target

    @staticmethod
    def _assert_safe_path(target: Path) -> None:
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ChangeSetIntegrationError("changeset.integration_path_invalid")

    @staticmethod
    def _assert_image(path: Path, image: ContentImage | None) -> None:
        if image is None:
            if path.exists() or path.is_symlink():
                raise ChangeSetIntegrationError("changeset.integration_conflict")
            return
        if path.is_symlink() or not path.is_file():
            raise ChangeSetIntegrationError("changeset.integration_conflict")
        content = path.read_bytes()
        if len(content) != image.size or hashlib.sha256(content).hexdigest() != image.digest:
            raise ChangeSetIntegrationError("changeset.integration_conflict")

    def _transition(
        self, changeset: ChangeSet, expected: ChangeSetStatus, target: ChangeSetStatus
    ) -> None:
        self._journal.transition_changeset_status(
            changeset_id=changeset.changeset_id,
            expected=expected,
            target=target,
            operation_id=str(uuid4()),
            updated_at=datetime.now(UTC),
        )
