from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from rudder.runtime.changeset_integration import ChangeSetIntegrator
from rudder.runtime.workspace_capture import (
    ImmutableArtifactStore,
    StableWorktreeScanner,
    WorkspaceCaptureError,
    capture_changeset,
    capture_managed_changeset,
)
from rudder.runtime.workspaces import WorkspaceManager
from rudder.sessions import Journal


def _git(workspace: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=workspace, check=True, capture_output=True, text=True)


def _repository(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _git(workspace, "init")
    _git(workspace, "config", "user.email", "tests@example.invalid")
    _git(workspace, "config", "user.name", "Rudder tests")
    (workspace / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(workspace, "add", "tracked.txt")
    _git(workspace, "commit", "-m", "initial")
    return workspace


def test_scanner_returns_regular_files_below_configured_limits(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "source.txt").write_text("source\n", encoding="utf-8")
    (worktree / ".git").mkdir()
    (worktree / ".git" / "ignored").write_text("metadata", encoding="utf-8")

    files = StableWorktreeScanner(max_files=2, max_bytes=20).scan(worktree)

    assert [(item.path, item.size) for item in files] == [
        ("source.txt", len((worktree / "source.txt").read_bytes()))
    ]


def test_scanner_rejects_hard_links_and_enforces_limits_before_reading(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    source = worktree / "source.txt"
    source.write_text("source\n", encoding="utf-8")
    try:
        os.link(source, worktree / "linked.txt")
    except OSError:
        pytest.skip("Hard-link creation is unavailable")

    with pytest.raises(WorkspaceCaptureError, match="workspace.capture_hard_link"):
        StableWorktreeScanner(max_files=10, max_bytes=100).scan(worktree)


def test_scanner_rejects_a_file_that_exceeds_the_byte_budget(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "large.txt").write_bytes(b"larger-than-budget")

    with pytest.raises(WorkspaceCaptureError, match="workspace.capture_limit_exceeded"):
        StableWorktreeScanner(max_files=1, max_bytes=1).scan(worktree)


def test_scanner_rejects_symlinked_entries(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    try:
        (worktree / "linked.txt").symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation is unavailable")

    with pytest.raises(WorkspaceCaptureError, match="workspace.capture_reparse_point"):
        StableWorktreeScanner(max_files=10, max_bytes=100).scan(worktree)


def test_artifact_publication_is_content_addressed_and_create_once(tmp_path: Path) -> None:
    store = ImmutableArtifactStore(tmp_path / "artifacts")
    content = b"after image\n"

    first = store.publish(content)
    second = store.publish(content)

    assert first == second
    assert first.digest == hashlib.sha256(content).hexdigest()
    assert first.path.read_bytes() == content
    assert stat.S_IMODE(first.path.stat().st_mode) & stat.S_IWUSR == 0


def test_artifact_publication_rejects_existing_digest_path_with_different_content(
    tmp_path: Path,
) -> None:
    content = b"after image\n"
    digest = hashlib.sha256(content).hexdigest()
    path = tmp_path / "artifacts" / "sha256" / digest
    path.parent.mkdir(parents=True)
    path.write_bytes(b"tampered")

    with pytest.raises(WorkspaceCaptureError, match="workspace.artifact_corrupt"):
        ImmutableArtifactStore(tmp_path / "artifacts").publish(content)


def test_capture_changeset_publishes_before_and_after_images(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    (snapshot / "files" / "src").mkdir(parents=True)
    (snapshot / "files" / "src" / "example.py").write_bytes(b"before")
    snapshot_id = "a" * 64
    head = "b" * 40
    (snapshot / "manifest.json").write_text(
        '{"snapshot_id":"' + snapshot_id + '","head":"' + head
        + '","files":{"src/example.py":{"digest":"' + hashlib.sha256(b"before").hexdigest()
        + '","size":6,"deleted":false}}}',
        encoding="utf-8",
    )
    worktree = tmp_path / "worktree"
    (worktree / "src").mkdir(parents=True)
    (worktree / "src" / "example.py").write_bytes(b"after")

    changeset = capture_changeset(
        changeset_id="55555555-5555-4555-8555-555555555555",
        task_id="33333333-3333-4333-8333-333333333333",
        attempt_id="44444444-4444-4444-8444-444444444444",
        snapshot_id=snapshot_id,
        snapshot_path=snapshot,
        base_head=head,
        declared_scope=("src",),
        worktree=worktree,
        scanner=StableWorktreeScanner(max_files=10, max_bytes=100),
        artifacts=ImmutableArtifactStore(tmp_path / "artifacts"),
    )

    assert changeset.paths[0].effect == "modified"
    assert changeset.paths[0].before is not None
    assert changeset.paths[0].after is not None


def test_capture_changeset_records_added_files_and_rejects_tampered_base(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    (snapshot / "files").mkdir(parents=True)
    snapshot_id = "a" * 64
    head = "b" * 40
    (snapshot / "manifest.json").write_text(
        '{"snapshot_id":"' + snapshot_id + '","head":"' + head + '","files":{}}',
        encoding="utf-8",
    )
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "added.txt").write_bytes(b"added")

    changeset = capture_changeset(
        changeset_id="55555555-5555-4555-8555-555555555556",
        task_id="33333333-3333-4333-8333-333333333333",
        attempt_id="44444444-4444-4444-8444-444444444445",
        snapshot_id=snapshot_id,
        snapshot_path=snapshot,
        base_head=head,
        declared_scope=("added.txt",),
        worktree=worktree,
        scanner=StableWorktreeScanner(max_files=10, max_bytes=100),
        artifacts=ImmutableArtifactStore(tmp_path / "artifacts"),
    )

    assert changeset.paths[0].effect == "added"
    assert changeset.paths[0].before is None

    (snapshot / "files" / "tracked.txt").write_bytes(b"tampered")
    (snapshot / "manifest.json").write_text(
        '{"snapshot_id":"' + snapshot_id + '","head":"' + head
        + '","files":{"tracked.txt":{"digest":"' + "0" * 64
        + '","size":1,"deleted":false}}}',
        encoding="utf-8",
    )
    with pytest.raises(WorkspaceCaptureError, match="workspace.capture_snapshot_invalid"):
        capture_changeset(
            changeset_id="55555555-5555-4555-8555-555555555557",
            task_id="33333333-3333-4333-8333-333333333333",
            attempt_id="44444444-4444-4444-8444-444444444446",
            snapshot_id=snapshot_id,
            snapshot_path=snapshot,
            base_head=head,
            declared_scope=("tracked.txt",),
            worktree=worktree,
            scanner=StableWorktreeScanner(max_files=10, max_bytes=100),
            artifacts=ImmutableArtifactStore(tmp_path / "artifacts"),
        )


def test_managed_capture_authenticates_worktree_and_persists_changeset(tmp_path: Path) -> None:
    workspace = _repository(tmp_path)
    manager = WorkspaceManager(tmp_path / "rudder-data")
    snapshot = manager.capture(workspace)
    isolated = manager.materialize(snapshot, "33333333-3333-4333-8333-333333333333")
    (isolated.path / "tracked.txt").write_text("after\n", encoding="utf-8")
    journal = Journal(tmp_path / "rudder.sqlite")
    now = datetime(2026, 9, 8, tzinfo=UTC)
    journal.migrate()
    journal.create_session(
        session_id="11111111-1111-4111-8111-111111111111",
        title="test",
        created_at=now,
    )
    journal.create_run(
        run_id="22222222-2222-4222-8222-222222222222",
        session_id="11111111-1111-4111-8111-111111111111",
        status="running",
        budget_limit_usd=Decimal("1"),
        created_at=now,
    )
    journal.create_task(
        task_id=isolated.task_id,
        run_id="22222222-2222-4222-8222-222222222222",
        description="write",
        status="running",
        idempotency_key="task",
        created_at=now,
    )
    journal.create_attempt(
        attempt_id="44444444-4444-4444-8444-444444444444",
        task_id=isolated.task_id,
        number=1,
        status="running",
        idempotency_key="attempt",
        created_at=now,
    )

    changeset = capture_managed_changeset(
        changeset_id="55555555-5555-4555-8555-555555555555",
        task_id=isolated.task_id,
        attempt_id="44444444-4444-4444-8444-444444444444",
        declared_scope=("tracked.txt",),
        snapshot=snapshot,
        workspace=isolated,
        manager=manager,
        scanner=StableWorktreeScanner(max_files=10, max_bytes=100),
        artifacts=ImmutableArtifactStore(tmp_path / "artifacts"),
        journal=journal,
        created_at=now,
    )

    assert journal.get_changeset(changeset.changeset_id).changeset == changeset
    assert (workspace / "tracked.txt").read_text(encoding="utf-8") == "base\n"

    status = ChangeSetIntegrator(
        journal=journal,
        artifacts=ImmutableArtifactStore(tmp_path / "artifacts"),
    ).integrate(changeset.changeset_id, workspace)

    assert status.value == "integrated"
    assert journal.get_changeset(changeset.changeset_id).status.value == "integrated"
    assert (workspace / "tracked.txt").read_text(encoding="utf-8") == "after\n"
