from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from rudder.runtime.redaction import RedactionRegistry
from rudder.tools.backend import CURRENT_TOOL_CALL_ID, PolicyFilesystemBackend
from rudder.tools.filesystem import FilesystemBoundary, PathBoundaryError


def test_workspace_rejects_absolute_traversal_and_symlink_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("hidden", encoding="utf-8")
    boundary = FilesystemBoundary(workspace, redactor=RedactionRegistry())
    with pytest.raises(PathBoundaryError):
        boundary.resolve("../outside/secret.txt")
    with pytest.raises(PathBoundaryError):
        boundary.resolve(outside / "secret.txt")
    link = workspace / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(PathBoundaryError):
        boundary.resolve("escape/secret.txt")


def test_explicit_canonical_grant_and_sensitive_read_policy(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    allowed = outside / "allowed.txt"
    allowed.write_text("ok", encoding="utf-8")
    (workspace / ".env").write_text("TOKEN=secret", encoding="utf-8")
    boundary = FilesystemBoundary(workspace, outside_grants=[allowed])
    assert boundary.read_text(allowed) == "ok"
    with pytest.raises(PermissionError, match="sensitive"):
        boundary.read_text(".env")


def test_write_records_task_tool_call_and_hashes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    boundary = FilesystemBoundary(workspace)
    first = boundary.write_text("a.txt", "before", task_id="task-1", tool_call_id="call-1")
    second = boundary.write_text("a.txt", "after", task_id="task-1", tool_call_id="call-2")
    assert first.before_hash is None
    assert second.before_hash == first.after_hash
    assert second.after_hash != second.before_hash


def test_deepagents_backend_enforces_sensitive_reads_and_records_writes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".env").write_text("TOKEN=canary", encoding="utf-8")
    backend = PolicyFilesystemBackend(
        workspace, redactor=RedactionRegistry(), task_id="task-1"
    )
    assert backend.read("/.env").error is not None
    assert backend.write("/safe.txt", "safe").error is None
    assert backend.boundary.changes[0].task_id == "task-1"
    assert backend.boundary.changes[0].before_hash is None
    token = CURRENT_TOOL_CALL_ID.set("actual-tool-call")
    try:
        assert backend.write("/second.txt", "safe").error is None
    finally:
        CURRENT_TOOL_CALL_ID.reset(token)
    assert backend.boundary.changes[-1].tool_call_id == "actual-tool-call"
    grep = backend.grep("TOKEN", "/")
    assert grep.matches == []
    git = workspace / ".git"
    git.mkdir()
    (git / "config").write_text("TOKEN=canary", encoding="utf-8")
    assert backend.read("/.git/config").error is not None
    assert backend.grep("TOKEN", "/").matches == []
    assert all(
        entry["path"] != "/.git" for entry in (backend.ls("/").entries or [])
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows junction contract")
def test_workspace_rejects_windows_junction_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("hidden", encoding="utf-8")
    junction = workspace / "junction"
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.skip("junction creation is unavailable")
    with pytest.raises(PathBoundaryError):
        FilesystemBoundary(workspace).resolve("junction/secret.txt")
