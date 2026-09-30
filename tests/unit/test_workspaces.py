from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from skail.runtime.workspaces import WorkspaceManager, WorkspaceMode


def _git(workspace: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=workspace, check=True, capture_output=True, text=True
    )


def _repository(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _git(workspace, "init")
    _git(workspace, "config", "user.email", "tests@example.invalid")
    _git(workspace, "config", "user.name", "Skail tests")
    (workspace / "tracked.txt").write_text("base\n", encoding="utf-8")
    (workspace / ".gitignore").write_text("ignored.env\n", encoding="utf-8")
    _git(workspace, "add", "tracked.txt", ".gitignore")
    _git(workspace, "commit", "-m", "initial")
    return workspace


def test_snapshot_reproduces_dirty_and_untracked_inputs_without_mutating_workspace(
    tmp_path: Path,
) -> None:
    workspace = _repository(tmp_path)
    (workspace / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    (workspace / "untracked.txt").write_text("included\n", encoding="utf-8")
    (workspace / "ignored.env").write_text("do-not-copy\n", encoding="utf-8")
    manager = WorkspaceManager(tmp_path / "skail-data")

    snapshot = manager.capture(workspace)

    assert snapshot.mode is WorkspaceMode.WORKTREE
    assert snapshot.files["tracked.txt"].digest
    assert snapshot.files["untracked.txt"].digest
    assert "ignored.env" not in snapshot.files
    assert (workspace / "tracked.txt").read_text(encoding="utf-8") == "dirty\n"
    assert (workspace / "untracked.txt").read_text(encoding="utf-8") == "included\n"
    assert not snapshot.path.is_relative_to(workspace.resolve())
    assert (snapshot.path / "files" / "tracked.txt").read_text(encoding="utf-8") == "dirty\n"
    assert (snapshot.path / "files" / "untracked.txt").read_text(encoding="utf-8") == "included\n"


def test_worktree_mode_falls_back_to_shared_for_non_git_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    selection = WorkspaceManager(tmp_path / "skail-data").select(workspace, "worktree")

    assert selection.mode is WorkspaceMode.SHARED
    assert selection.reason == "workspace.git_unavailable"


def test_snapshots_are_content_addressed_and_preserve_their_original_inputs(
    tmp_path: Path,
) -> None:
    workspace = _repository(tmp_path)
    manager = WorkspaceManager(tmp_path / "skail-data")

    first = manager.capture(workspace)
    (workspace / "tracked.txt").write_text("changed\n", encoding="utf-8")
    second = manager.capture(workspace)

    assert first.snapshot_id != second.snapshot_id
    assert (first.path / "files" / "tracked.txt").read_text(encoding="utf-8") == "base\n"
    assert (second.path / "files" / "tracked.txt").read_text(encoding="utf-8") == "changed\n"


def test_materialized_worktree_preserves_tracked_deletions_from_a_dirty_snapshot(
    tmp_path: Path,
) -> None:
    workspace = _repository(tmp_path)
    (workspace / "tracked.txt").unlink()
    manager = WorkspaceManager(tmp_path / "skail-data")

    snapshot = manager.capture(workspace)
    isolated = manager.materialize(snapshot, "task-1")

    assert snapshot.files["tracked.txt"].deleted is True
    assert not (isolated.path / "tracked.txt").exists()
    assert not (workspace / "tracked.txt").exists()


def test_materialized_worktree_uses_snapshot_inputs_and_retains_changes(tmp_path: Path) -> None:
    workspace = _repository(tmp_path)
    (workspace / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    manager = WorkspaceManager(tmp_path / "skail-data")

    snapshot = manager.capture(workspace)
    isolated = manager.materialize(snapshot, "task-1")

    assert isolated.path != workspace
    assert (isolated.path / "tracked.txt").read_text(encoding="utf-8") == "dirty\n"
    (isolated.path / "result.txt").write_text("preserve\n", encoding="utf-8")
    assert manager.cleanup(isolated) is False
    assert isolated.path.exists()
    retained = (
        tmp_path
        / "skail-data"
        / "retained"
        / f"{snapshot.snapshot_id}-{isolated.task_id}.json"
    )
    assert retained.exists()
    assert not (isolated.path / "retained.json").exists()

    retry_workspace = manager.materialize(snapshot, "task-1")

    assert retry_workspace == isolated
    assert (retry_workspace.path / "tracked.txt").read_text(encoding="utf-8") == "dirty\n"
    assert (retry_workspace.path / "result.txt").read_text(encoding="utf-8") == "preserve\n"
    assert not retained.exists()


def test_materialize_rejects_a_retained_worktree_record_for_another_task(
    tmp_path: Path,
) -> None:
    workspace = _repository(tmp_path)
    manager = WorkspaceManager(tmp_path / "skail-data")
    snapshot = manager.capture(workspace)
    isolated = manager.materialize(snapshot, "task-1")
    (isolated.path / "result.txt").write_text("preserve\n", encoding="utf-8")
    assert manager.cleanup(isolated) is False
    record = tmp_path / "skail-data" / "retained" / f"{snapshot.snapshot_id}-task-1.json"
    payload = json.loads(record.read_text(encoding="utf-8"))
    payload["task_id"] = "task-2"
    record.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="workspace.retention_state_invalid"):
        manager.materialize(snapshot, "task-1")

    assert isolated.path.exists()
    assert (isolated.path / "result.txt").read_text(encoding="utf-8") == "preserve\n"


def test_snapshot_rejects_symlinked_workspace_input(tmp_path: Path) -> None:
    workspace = _repository(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    link = workspace / "linked.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation is unavailable")
    _git(workspace, "add", "linked.txt")

    with pytest.raises(ValueError, match="workspace.snapshot_symlink"):
        WorkspaceManager(tmp_path / "skail-data").capture(workspace)
