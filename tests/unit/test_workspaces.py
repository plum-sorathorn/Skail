from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from rudder.runtime.workspaces import WorkspaceManager, WorkspaceMode


def _git(workspace: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=workspace, check=True, capture_output=True, text=True
    )


def _repository(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _git(workspace, "init")
    _git(workspace, "config", "user.email", "tests@example.invalid")
    _git(workspace, "config", "user.name", "Rudder tests")
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
    manager = WorkspaceManager(tmp_path / "rudder-data")

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

    selection = WorkspaceManager(tmp_path / "rudder-data").select(workspace, "worktree")

    assert selection.mode is WorkspaceMode.SHARED
    assert selection.reason == "workspace.git_unavailable"


def test_snapshots_are_content_addressed_and_preserve_their_original_inputs(
    tmp_path: Path,
) -> None:
    workspace = _repository(tmp_path)
    manager = WorkspaceManager(tmp_path / "rudder-data")

    first = manager.capture(workspace)
    (workspace / "tracked.txt").write_text("changed\n", encoding="utf-8")
    second = manager.capture(workspace)

    assert first.snapshot_id != second.snapshot_id
    assert (first.path / "files" / "tracked.txt").read_text(encoding="utf-8") == "base\n"
    assert (second.path / "files" / "tracked.txt").read_text(encoding="utf-8") == "changed\n"


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
        WorkspaceManager(tmp_path / "rudder-data").capture(workspace)
