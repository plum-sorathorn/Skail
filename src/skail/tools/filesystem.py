from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from skail.runtime.redaction import RedactionRegistry
from skail.sessions.locking import process_file_lock


class PathBoundaryError(PermissionError):
    pass


@dataclass(frozen=True)
class FileChange:
    path: Path
    task_id: str
    tool_call_id: str
    before_hash: str | None
    after_hash: str


class FilesystemBoundary:
    def __init__(
        self,
        workspace: Path,
        *,
        outside_grants: list[Path] | tuple[Path, ...] = (),
        forbidden_host_paths: list[Path] | tuple[Path, ...] = (),
        redactor: RedactionRegistry | None = None,
        sensitive_patterns: tuple[str, ...] = (
            ".env", "*.pem", "*.key", "id_rsa", ".git", ".skail",
        ),
    ) -> None:
        self.workspace = workspace.resolve(strict=True)
        self.outside_grants = frozenset(path.resolve(strict=True) for path in outside_grants)
        self.forbidden_host_paths = tuple(
            path.resolve(strict=False) for path in forbidden_host_paths
        )
        self.redactor = redactor or RedactionRegistry()
        self.sensitive_patterns = sensitive_patterns
        self.changes: list[FileChange] = []

    def assert_host_path_allowed(self, raw: str | Path) -> None:
        supplied = Path(raw)
        if not supplied.is_absolute():
            return
        candidate = supplied.resolve(strict=False)
        for forbidden in self.forbidden_host_paths:
            try:
                candidate.relative_to(forbidden)
            except ValueError:
                continue
            raise PathBoundaryError("path targets a forbidden host workspace")

    def resolve(self, raw: str | Path, *, for_write: bool = False) -> Path:
        self.assert_host_path_allowed(raw)
        supplied = Path(raw)
        candidate = supplied if supplied.is_absolute() else self.workspace / supplied
        candidate = candidate.resolve(strict=not for_write)
        if candidate in self.outside_grants:
            return candidate
        try:
            candidate.relative_to(self.workspace)
        except ValueError as exc:
            raise PathBoundaryError("path escapes workspace and has no canonical grant") from exc
        return candidate

    def _assert_not_sensitive(self, path: Path) -> None:
        relative = path.relative_to(self.workspace)
        if any(self._matches_sensitive(relative, pattern) for pattern in self.sensitive_patterns):
            raise PermissionError("sensitive path requires explicit stronger handling")

    @staticmethod
    def _matches_sensitive(relative: Path, pattern: str) -> bool:
        if any(character in pattern for character in "*?["):
            return relative.match(pattern) or any(
                Path(part).match(pattern) for part in relative.parts
            )
        return pattern in relative.parts

    def read_text(self, raw: str | Path) -> str:
        path = self.resolve(raw)
        if path not in self.outside_grants:
            self._assert_not_sensitive(path)
        return self.redactor.scrub_text(path.read_text(encoding="utf-8"))

    def write_text(
        self, raw: str | Path, content: str, *, task_id: str, tool_call_id: str
    ) -> FileChange:
        lock_path = self.workspace / ".skail" / "filesystem-boundary.lock"
        with process_file_lock(lock_path):
            path = self.resolve(raw, for_write=True)
            self._assert_not_sensitive(path)
            before = path.read_bytes() if path.exists() else None
            path.parent.mkdir(parents=True, exist_ok=True)
            canonical_parent = path.parent.resolve(strict=True)
            canonical_parent.relative_to(self.workspace)
            temporary_name: str | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=canonical_parent,
                    delete=False,
                ) as temporary:
                    temporary.write(content)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                    temporary_name = temporary.name
                if path.parent.resolve(strict=True) != canonical_parent:
                    raise PathBoundaryError("write parent changed during authorization")
                os.replace(temporary_name, path)
                temporary_name = None
            finally:
                if temporary_name is not None:
                    Path(temporary_name).unlink(missing_ok=True)
            change = FileChange(
                path,
                task_id,
                tool_call_id,
                None if before is None else hashlib.sha256(before).hexdigest(),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        self.changes.append(change)
        return change
