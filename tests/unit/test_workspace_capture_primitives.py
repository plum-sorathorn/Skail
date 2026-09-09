from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

import pytest

from rudder.runtime.workspace_capture import (
    ImmutableArtifactStore,
    StableWorktreeScanner,
    WorkspaceCaptureError,
)


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
