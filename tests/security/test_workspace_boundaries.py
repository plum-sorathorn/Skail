from __future__ import annotations

from pathlib import Path

import pytest

from rudder.runtime.redaction import RedactionRegistry
from rudder.tools.filesystem import FilesystemBoundary, PathBoundaryError


def test_adversarial_traversal_attempts_blocked(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("hidden", encoding="utf-8")

    boundary = FilesystemBoundary(workspace, redactor=RedactionRegistry())

    evil_paths = [
        "../outside/secret.txt",
        outside / "secret.txt",
        "sub/../../outside/secret.txt",
        "foo/bar/../../../outside/secret.txt",
    ]

    for p in evil_paths:
        with pytest.raises(PathBoundaryError):
            boundary.resolve(p)

    # For write resolution (non-strict)
    with pytest.raises(PathBoundaryError):
        boundary.resolve("../outside/new_file.txt", for_write=True)


def test_sensitive_files_read_prohibited(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    boundary = FilesystemBoundary(workspace, redactor=RedactionRegistry())

    sensitive_names = [
        ".env",
        "id_rsa",
        "cert.pem",
        "secret.key",
    ]

    for name in sensitive_names:
        f = workspace / name
        f.write_text("SUPER_SECRET_KEY=123456", encoding="utf-8")
        with pytest.raises(PermissionError, match="sensitive"):
            boundary.read_text(name)


def test_symlink_escape_adversarial(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    target_secret = outside / "secret.env"
    target_secret.write_text("SECRET=xyz", encoding="utf-8")

    link = workspace / "nested_link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks require administrator privileges on Windows")

    boundary = FilesystemBoundary(workspace)
    with pytest.raises(PathBoundaryError):
        boundary.resolve("nested_link/secret.env")


def test_outside_grant_requires_exact_canonical_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()

    allowed = outside / "shared.txt"
    allowed.write_text("allowed content", encoding="utf-8")
    forbidden = outside / "forbidden.txt"
    forbidden.write_text("forbidden content", encoding="utf-8")

    boundary = FilesystemBoundary(workspace, outside_grants=[allowed])
    # Exact granted file is accessible
    assert boundary.read_text(allowed) == "allowed content"

    # Sibling file in same outside dir is NOT accessible
    with pytest.raises(PathBoundaryError):
        boundary.resolve(forbidden)
