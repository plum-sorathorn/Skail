"""Fail-closed primitives for later isolated-worktree changeset capture."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path


class WorkspaceCaptureError(ValueError):
    """A worktree cannot safely provide durable capture evidence."""


@dataclass(frozen=True)
class ScannedWorkspaceFile:
    path: str
    digest: str
    size: int


@dataclass(frozen=True)
class PublishedArtifact:
    digest: str
    size: int
    path: Path

    @property
    def reference(self) -> str:
        return f"sha256:{self.digest}"


class ImmutableArtifactStore:
    """Publishes content-addressed artifacts without overwriting prior evidence."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve(strict=False)

    def publish(self, content: bytes) -> PublishedArtifact:
        digest = hashlib.sha256(content).hexdigest()
        directory = self._root / "sha256"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / digest
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
        except FileExistsError:
            self._verify_existing(path, content)
        else:
            try:
                with os.fdopen(descriptor, "wb", closefd=True) as artifact:
                    artifact.write(content)
                    artifact.flush()
                    os.fsync(artifact.fileno())
                os.chmod(path, 0o444)
            except BaseException:
                # A partial artifact is intentionally left in place: future publication fails
                # closed rather than mistaking it for complete evidence.
                raise
        return PublishedArtifact(digest=digest, size=len(content), path=path)

    @staticmethod
    def _verify_existing(path: Path, expected: bytes) -> None:
        try:
            metadata = path.lstat()
        except OSError as error:
            raise WorkspaceCaptureError("workspace.artifact_corrupt") from error
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_nlink != 1
        ):
            raise WorkspaceCaptureError("workspace.artifact_corrupt")
        try:
            actual = path.read_bytes()
        except OSError as error:
            raise WorkspaceCaptureError("workspace.artifact_corrupt") from error
        if actual != expected:
            raise WorkspaceCaptureError("workspace.artifact_corrupt")


class StableWorktreeScanner:
    """Reads only bounded regular files whose identity is stable across the read."""

    def __init__(self, *, max_files: int, max_bytes: int) -> None:
        if max_files < 1 or max_bytes < 0:
            raise ValueError("workspace.capture_limits_invalid")
        self._max_files = max_files
        self._max_bytes = max_bytes

    def scan(self, worktree: Path) -> tuple[ScannedWorkspaceFile, ...]:
        self._assert_safe_directory(worktree)
        root = worktree.resolve(strict=True)
        if not root.is_dir():
            raise WorkspaceCaptureError("workspace.capture_root_invalid")
        files: list[ScannedWorkspaceFile] = []
        total_bytes = 0
        pending = [root]
        while pending:
            directory = pending.pop()
            self._assert_safe_directory(directory)
            try:
                entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
            except OSError as error:
                raise WorkspaceCaptureError("workspace.capture_scan_failed") from error
            for entry in entries:
                if entry.name == ".git":
                    self._assert_safe_entry(entry)
                    continue
                self._assert_safe_entry(entry)
                path = Path(entry.path)
                metadata = path.lstat()
                if stat.S_ISDIR(metadata.st_mode):
                    pending.append(path)
                    continue
                if not stat.S_ISREG(metadata.st_mode):
                    raise WorkspaceCaptureError("workspace.capture_non_regular")
                if metadata.st_nlink != 1:
                    raise WorkspaceCaptureError("workspace.capture_hard_link")
                if (
                    len(files) >= self._max_files
                    or total_bytes + metadata.st_size > self._max_bytes
                ):
                    raise WorkspaceCaptureError("workspace.capture_limit_exceeded")
                content = self._read_stable_regular_file(path, root, metadata)
                relative = path.relative_to(root).as_posix()
                files.append(
                    ScannedWorkspaceFile(
                        path=relative,
                        digest=hashlib.sha256(content).hexdigest(),
                        size=len(content),
                    )
                )
                total_bytes += len(content)
        return tuple(sorted(files, key=lambda item: item.path))

    @staticmethod
    def _assert_safe_directory(path: Path) -> None:
        try:
            metadata = path.lstat()
        except OSError as error:
            raise WorkspaceCaptureError("workspace.capture_scan_failed") from error
        if not stat.S_ISDIR(metadata.st_mode) or StableWorktreeScanner._is_reparse(metadata):
            raise WorkspaceCaptureError("workspace.capture_reparse_point")

    @staticmethod
    def _assert_safe_entry(entry: os.DirEntry[str]) -> None:
        try:
            metadata = Path(entry.path).lstat()
        except OSError as error:
            raise WorkspaceCaptureError("workspace.capture_scan_failed") from error
        if entry.is_symlink() or StableWorktreeScanner._is_reparse(metadata):
            raise WorkspaceCaptureError("workspace.capture_reparse_point")

    @staticmethod
    def _is_reparse(metadata: os.stat_result) -> bool:
        attributes = getattr(metadata, "st_file_attributes", 0)
        reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        return bool(reparse_point and attributes & reparse_point)

    @staticmethod
    def _read_stable_regular_file(
        path: Path, root: Path, expected: os.stat_result
    ) -> bytes:
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, os.O_RDONLY | no_follow)
        except OSError as error:
            raise WorkspaceCaptureError("workspace.capture_read_failed") from error
        with os.fdopen(descriptor, "rb", closefd=True) as source:
            opened = os.fstat(source.fileno())
            if not StableWorktreeScanner._same_regular_file(expected, opened):
                raise WorkspaceCaptureError("workspace.capture_changed_during_scan")
            content = source.read(expected.st_size + 1)
            closed = os.fstat(source.fileno())
        StableWorktreeScanner._assert_safe_ancestors(path, root)
        current = path.lstat()
        if len(content) != expected.st_size or not StableWorktreeScanner._same_regular_file(
            expected, closed
        ) or not StableWorktreeScanner._same_regular_file(expected, current):
            raise WorkspaceCaptureError("workspace.capture_changed_during_scan")
        return content

    @staticmethod
    def _assert_safe_ancestors(path: Path, root: Path) -> None:
        current = path.parent
        while True:
            StableWorktreeScanner._assert_safe_directory(current)
            if current == root:
                return
            current = current.parent

    @staticmethod
    def _same_regular_file(expected: os.stat_result, actual: os.stat_result) -> bool:
        return (
            stat.S_ISREG(actual.st_mode)
            and actual.st_nlink == 1
            and expected.st_dev == actual.st_dev
            and expected.st_ino == actual.st_ino
            and expected.st_size == actual.st_size
            and expected.st_mtime_ns == actual.st_mtime_ns
        )
