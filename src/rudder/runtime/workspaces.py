"""Immutable workspace snapshots for future isolated writer execution."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath


class WorkspaceMode(StrEnum):
    SHARED = "shared"
    WORKTREE = "worktree"


@dataclass(frozen=True)
class SnapshotFile:
    digest: str
    size: int


@dataclass(frozen=True)
class WorkspaceSelection:
    mode: WorkspaceMode
    reason: str


@dataclass(frozen=True)
class WorkspaceSnapshot:
    snapshot_id: str
    root: Path
    path: Path
    head: str
    files: dict[str, SnapshotFile]
    mode: WorkspaceMode = WorkspaceMode.WORKTREE


class WorkspaceManager:
    """Captures non-ignored Git inputs without altering the source workspace."""

    def __init__(self, data_root: Path) -> None:
        self._data_root = data_root.resolve(strict=False)

    def select(self, workspace: Path, requested_mode: str) -> WorkspaceSelection:
        if requested_mode != WorkspaceMode.WORKTREE:
            return WorkspaceSelection(WorkspaceMode.SHARED, "workspace.shared_requested")
        try:
            self._git_context(workspace)
        except ValueError as error:
            return WorkspaceSelection(WorkspaceMode.SHARED, str(error))
        return WorkspaceSelection(WorkspaceMode.WORKTREE, "workspace.isolation_available")

    def capture(self, workspace: Path) -> WorkspaceSnapshot:
        root, head = self._git_context(workspace)
        try:
            self._data_root.relative_to(root)
        except ValueError:
            pass
        else:
            raise ValueError("workspace.snapshot_data_inside_workspace")

        files: dict[str, SnapshotFile] = {}
        paths = self._tracked_paths(root) | self._untracked_paths(root)
        snapshots_root = self._data_root / "workspace-snapshots"
        snapshots_root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix="snapshot-", dir=snapshots_root))
        try:
            files_root = temporary / "files"
            for relative_path in sorted(paths):
                source = self._source_path(root, relative_path)
                content = source.read_bytes()
                digest = hashlib.sha256(content).hexdigest()
                destination = files_root / Path(*PurePosixPath(relative_path).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                files[relative_path] = SnapshotFile(digest=digest, size=len(content))

            manifest = {
                "schema_version": 1,
                "root": str(root),
                "head": head,
                "files": {
                    path: {"digest": item.digest, "size": item.size}
                    for path, item in sorted(files.items())
                },
            }
            encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
            snapshot_id = hashlib.sha256(encoded).hexdigest()
            manifest["snapshot_id"] = snapshot_id
            (temporary / "manifest.json").write_text(
                json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
            )
            destination = snapshots_root / snapshot_id
            if destination.exists():
                shutil.rmtree(temporary)
            else:
                temporary.replace(destination)
            return WorkspaceSnapshot(snapshot_id, root, destination, head, files)
        except BaseException:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise

    def _git_context(self, workspace: Path) -> tuple[Path, str]:
        root = workspace.resolve(strict=True)
        try:
            git_root = Path(self._git(root, "rev-parse", "--show-toplevel")).resolve(strict=True)
            head = self._git(root, "rev-parse", "HEAD")
        except (OSError, subprocess.CalledProcessError) as error:
            raise ValueError("workspace.git_unavailable") from error
        if git_root != root:
            raise ValueError("workspace.git_root_mismatch")
        return root, head

    def _tracked_paths(self, root: Path) -> set[str]:
        return self._git_paths(root, "ls-files", "-z")

    def _untracked_paths(self, root: Path) -> set[str]:
        return self._git_paths(root, "ls-files", "--others", "--exclude-standard", "-z")

    def _git_paths(self, root: Path, *args: str) -> set[str]:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
        )
        return {
            value.decode("utf-8")
            for value in completed.stdout.split(b"\0")
            if value
        }

    def _source_path(self, root: Path, relative_path: str) -> Path:
        parts = PurePosixPath(relative_path).parts
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("workspace.snapshot_path_invalid")
        source = root.joinpath(*parts)
        if source.is_symlink():
            raise ValueError("workspace.snapshot_symlink")
        try:
            source.resolve(strict=True).relative_to(root)
        except (OSError, ValueError) as error:
            raise ValueError("workspace.snapshot_path_invalid") from error
        if not source.is_file():
            raise ValueError("workspace.snapshot_non_file")
        return source

    @staticmethod
    def _git(root: Path, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()
