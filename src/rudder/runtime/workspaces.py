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
    deleted: bool = False


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


@dataclass(frozen=True)
class IsolatedWorkspace:
    snapshot_id: str
    task_id: str
    path: Path
    branch: str


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
        tracked_paths = self._tracked_paths(root)
        paths = tracked_paths | self._untracked_paths(root)
        snapshots_root = self._data_root / "workspace-snapshots"
        snapshots_root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix="snapshot-", dir=snapshots_root))
        try:
            files_root = temporary / "files"
            for relative_path in sorted(paths):
                if relative_path in tracked_paths and not (root / relative_path).exists():
                    files[relative_path] = SnapshotFile(digest="", size=0, deleted=True)
                    continue
                source = self._source_path(root, relative_path)
                content = source.read_bytes()
                digest = hashlib.sha256(content).hexdigest()
                destination = files_root / Path(*PurePosixPath(relative_path).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                files[relative_path] = SnapshotFile(digest=digest, size=len(content))

            manifest = {
                "schema_version": 2,
                "root": str(root),
                "head": head,
                "files": {
                    path: {
                        "digest": item.digest,
                        "size": item.size,
                        "deleted": item.deleted,
                    }
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

    def materialize(self, snapshot: WorkspaceSnapshot, task_id: str) -> IsolatedWorkspace:
        allowed_task_characters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
        if not task_id or any(
            character not in allowed_task_characters for character in task_id
        ):
            raise ValueError("workspace.task_id_invalid")
        root, head = self._git_context(snapshot.root)
        if root != snapshot.root or head != snapshot.head:
            raise ValueError("workspace.snapshot_base_stale")
        worktrees_root = self._data_root / "worktrees"
        worktrees_root.mkdir(parents=True, exist_ok=True)
        path = (worktrees_root / f"{snapshot.snapshot_id[:12]}-{task_id}").resolve(strict=False)
        try:
            path.relative_to(worktrees_root.resolve())
        except ValueError as error:
            raise ValueError("workspace.worktree_path_invalid") from error
        if path.exists():
            raise ValueError("workspace.worktree_exists")
        branch = f"rudder/{snapshot.snapshot_id[:12]}/{task_id}"
        self._git(root, "worktree", "add", "--no-checkout", "-b", branch, str(path), snapshot.head)
        try:
            self._git(path, "reset", "--hard", snapshot.head)
            for relative_path, item in snapshot.files.items():
                destination = path.joinpath(*PurePosixPath(relative_path).parts)
                if item.deleted:
                    if destination.exists():
                        destination.unlink()
                    continue
                source = snapshot.path / "files" / Path(*PurePosixPath(relative_path).parts)
                if (
                    not source.is_file()
                    or hashlib.sha256(source.read_bytes()).hexdigest() != item.digest
                ):
                    raise ValueError("workspace.snapshot_corrupt")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            return IsolatedWorkspace(snapshot.snapshot_id, task_id, path, branch)
        except BaseException:
            self._git(root, "worktree", "remove", "--force", str(path))
            self._git(root, "branch", "-D", branch)
            raise

    def cleanup(self, workspace: IsolatedWorkspace) -> bool:
        self._validate_workspace_ownership(workspace)
        if not self._matches_snapshot(workspace):
            (workspace.path / "retained.json").write_text(
                json.dumps(
                    {
                        "reason": "workspace.unintegrated_changes",
                        "snapshot_id": workspace.snapshot_id,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            return False
        original_root = self._git(workspace.path, "rev-parse", "--git-common-dir")
        common = (workspace.path / original_root).resolve()
        self._git(common.parent, "worktree", "remove", "--force", str(workspace.path))
        self._git(common.parent, "branch", "-D", workspace.branch)
        return True

    def validate_capture_workspace(
        self, snapshot: WorkspaceSnapshot, workspace: IsolatedWorkspace
    ) -> None:
        """Fail closed unless this is the exact managed worktree for the snapshot."""
        self._validate_workspace_ownership(workspace)
        if (
            workspace.snapshot_id != snapshot.snapshot_id
            or snapshot.path != self._data_root / "workspace-snapshots" / snapshot.snapshot_id
            or snapshot.root != self._git_context(snapshot.root)[0]
        ):
            raise ValueError("workspace.capture_ownership_invalid")
        manifest = snapshot.path / "manifest.json"
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError) as error:
            raise ValueError("workspace.capture_ownership_invalid") from error
        if (
            payload.get("snapshot_id") != snapshot.snapshot_id
            or payload.get("head") != snapshot.head
        ):
            raise ValueError("workspace.capture_ownership_invalid")
        if self._git(workspace.path, "branch", "--show-current") != workspace.branch:
            raise ValueError("workspace.capture_ownership_invalid")
        if self._git(workspace.path, "ls-files", "--unmerged"):
            raise ValueError("workspace.capture_unmerged_index")
        staged = self._git(workspace.path, "ls-files", "--stage", "-z")
        if any(entry.startswith("160000 ") for entry in staged.split("\0") if entry):
            raise ValueError("workspace.capture_submodule")
        if " mode change " in self._git(workspace.path, "diff", "--summary", "HEAD"):
            raise ValueError("workspace.capture_mode_change")

    def retain(self, workspace: IsolatedWorkspace, reason: str) -> None:
        self._validate_workspace_ownership(workspace)
        (workspace.path / "retained.json").write_text(
            json.dumps({"reason": reason, "snapshot_id": workspace.snapshot_id}) + "\n",
            encoding="utf-8",
        )

    def _validate_workspace_ownership(self, workspace: IsolatedWorkspace) -> None:
        root = self._git_context(workspace.path)[0]
        expected_path = (
            self._data_root / "worktrees" / f"{workspace.snapshot_id[:12]}-{workspace.task_id}"
        ).resolve(strict=False)
        if root != expected_path or workspace.branch != (
            f"rudder/{workspace.snapshot_id[:12]}/{workspace.task_id}"
        ):
            raise ValueError("workspace.worktree_ownership_invalid")

    def _matches_snapshot(self, workspace: IsolatedWorkspace) -> bool:
        manifest_path = (
            self._data_root / "workspace-snapshots" / workspace.snapshot_id / "manifest.json"
        )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            files = manifest["files"]
        except (OSError, ValueError, KeyError, TypeError):
            return False
        if not isinstance(files, dict):
            return False
        actual_paths = self._tracked_paths(workspace.path) | self._untracked_paths(workspace.path)
        if actual_paths != set(files):
            return False
        for relative_path, expected in files.items():
            if not isinstance(expected, dict):
                return False
            source = workspace.path.joinpath(*PurePosixPath(relative_path).parts)
            if expected.get("deleted") is True:
                if source.exists():
                    return False
                continue
            try:
                content = self._source_path(workspace.path, relative_path).read_bytes()
            except ValueError:
                return False
            if hashlib.sha256(content).hexdigest() != expected.get("digest"):
                return False
        return True

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
