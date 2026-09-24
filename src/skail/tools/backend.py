from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from contextvars import ContextVar
from pathlib import Path, PurePosixPath
from typing import Any, cast

from deepagents.backends import FilesystemBackend
from deepagents.backends.protocol import (
    EditResult,
    GlobResult,
    GrepMatch,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)

from skail.runtime.leases import WorkspaceLeaseManager
from skail.runtime.redaction import RedactionRegistry
from skail.tools.filesystem import FilesystemBoundary, PathBoundaryError

CURRENT_TOOL_CALL_ID: ContextVar[str | None] = ContextVar(
    "skail_tool_call_id", default=None
)


class PolicyFilesystemBackend(FilesystemBackend):
    """DeepAgents backend with Skail policy enforced at the dispatch boundary."""

    def __init__(
        self,
        root_dir: Path,
        *,
        redactor: RedactionRegistry,
        task_id: str,
        lease_manager: WorkspaceLeaseManager | None = None,
        allowed_write_paths: tuple[str, ...] = (),
        forbidden_host_paths: tuple[Path, ...] = (),
        state_dir: Path | None = None,
    ) -> None:
        super().__init__(root_dir=root_dir, virtual_mode=True)
        self.boundary = FilesystemBoundary(
            root_dir,
            redactor=redactor,
            forbidden_host_paths=forbidden_host_paths,
            state_dir=state_dir,
        )
        self.task_id = task_id
        self.lease_manager = lease_manager
        self.allowed_write_paths = tuple(
            (root_dir / path).resolve(strict=False) for path in allowed_write_paths
        )
        self._call_number = 0

    def _relative(self, path: str) -> str:
        self.boundary.assert_host_path_allowed(path)
        value = PurePosixPath(path)
        if ".." in value.parts or "~" in value.parts:
            raise PathBoundaryError("virtual path traversal is not permitted")
        return str(value).lstrip("/") or "."

    def _next_call(self) -> str:
        active = CURRENT_TOOL_CALL_ID.get()
        if active is not None:
            return active
        self._call_number += 1
        return f"filesystem-{self._call_number}"

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        try:
            relative = self._relative(file_path)
            path = self.boundary.resolve(relative)
            self.boundary._assert_not_sensitive(path)
        except (PermissionError, OSError) as error:
            return ReadResult(error=str(error))
        result = super().read(file_path, offset, limit)
        if result.file_data is not None and result.file_data.get("encoding") == "utf-8":
            result.file_data["content"] = self.boundary.redactor.scrub_text(
                str(result.file_data["content"])
            )
        return result

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        *,
        max_count: int | None = None,
        context_lines: int = 0,
    ) -> GrepResult:
        try:
            result = (
                self._grep_utf8(pattern, path, glob, max_count, context_lines)
                if not pattern.isascii()
                else super().grep(
                    pattern,
                    path,
                    glob,
                    max_count=max_count,
                    context_lines=context_lines,
                )
            )
        except UnicodeDecodeError:
            result = self._grep_utf8(pattern, path, glob, max_count, context_lines)
        if result.matches is None:
            return result
        safe: list[GrepMatch] = []
        content_by_path: dict[Path, list[str]] = {}
        for match in result.matches:
            try:
                candidate = self.boundary.resolve(self._relative(match["path"]))
                self.boundary._assert_not_sensitive(candidate)
            except (PermissionError, OSError):
                continue
            try:
                file_lines = content_by_path.get(candidate)
                if file_lines is None:
                    file_lines = self.boundary.read_text(candidate).splitlines()
                    content_by_path[candidate] = file_lines
            except (OSError, UnicodeDecodeError):
                continue
            line_number = int(match.get("line", 0))
            if 1 <= line_number <= len(file_lines):
                match["text"] = file_lines[line_number - 1]
            else:
                match["text"] = self.boundary.redactor.scrub_text(match["text"])
            for field in ("context_before", "context_after"):
                context = cast(list[dict[str, Any]], match.get(field, []))
                for line in context:
                    context_number = int(line.get("line", 0))
                    if 1 <= context_number <= len(file_lines):
                        line["text"] = file_lines[context_number - 1]
                    else:
                        line["text"] = self.boundary.redactor.scrub_text(line["text"])
            safe.append(match)
        result.matches = safe
        return result

    def _grep_utf8(
        self,
        pattern: str,
        path: str | None,
        glob: str | None,
        max_count: int | None,
        context_lines: int,
    ) -> GrepResult:
        try:
            root = self.boundary.resolve(self._relative(path or "."))
        except (OSError, PermissionError) as exc:
            return GrepResult(error=str(exc), matches=[])
        if not root.exists():
            return GrepResult(matches=[])
        candidates: list[dict[str, Any]]
        if root.is_file():
            candidates = [
                {"path": f"/{root.relative_to(self.boundary.workspace).as_posix()}"}
            ]
        else:
            glob_result = super().glob(glob or "*", path=path)
            if glob_result.matches is None:
                return GrepResult(error=glob_result.error, matches=[])
            candidates = [
                {"path": str(item["path"])}
                for item in glob_result.matches
                if not item.get("is_dir", False)
            ]

        matches: list[GrepMatch] = []
        truncated = False
        for item in candidates:
            try:
                relative = self._relative(str(item["path"]))
                candidate = self.boundary.resolve(relative)
                self.boundary._assert_not_sensitive(candidate)
                content = self.boundary.read_text(candidate)
            except (OSError, PermissionError, UnicodeDecodeError):
                continue
            for line_number, line in enumerate(content.splitlines(), start=1):
                if pattern not in line:
                    continue
                if max_count is not None and len(matches) >= max_count:
                    truncated = True
                    break
                matches.append(
                    {
                        "path": f"/{candidate.relative_to(self.boundary.workspace).as_posix()}",
                        "line": line_number,
                        "text": line,
                    }
                )
            if truncated:
                break

        error: str | None = None
        if context_lines:
            unreadable = self._add_grep_context(
                matches, context_lines, pattern, newline=None
            )
            if unreadable:
                error = (
                    f"Error: could not read context for {len(unreadable)} file(s): "
                    + ", ".join(sorted(unreadable))
                )
        return GrepResult(error=error, matches=matches, truncated=truncated)

    def write(self, file_path: str, content: str) -> WriteResult:
        try:
            relative = self._relative(file_path)
            self._assert_write_scope(relative)
            with self._lease():
                self.boundary.write_text(
                    relative, content, task_id=self.task_id, tool_call_id=self._next_call()
                )
        except (PermissionError, OSError) as error:
            return WriteResult(error=str(error))
        return WriteResult(path=file_path)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        try:
            relative = self._relative(file_path)
            self._assert_write_scope(relative)
            path = self.boundary.resolve(relative)
            self.boundary._assert_not_sensitive(path)
            content = path.read_text(encoding="utf-8")
            occurrences = content.count(old_string)
            if occurrences == 0:
                return EditResult(error="old_string was not found")
            if occurrences > 1 and not replace_all:
                return EditResult(error="old_string occurs multiple times")
            updated = content.replace(old_string, new_string, -1 if replace_all else 1)
            with self._lease():
                self.boundary.write_text(
                    relative, updated, task_id=self.task_id, tool_call_id=self._next_call()
                )
        except (PermissionError, OSError) as error:
            return EditResult(error=str(error))
        return EditResult(path=file_path, occurrences=occurrences)

    def ls(self, path: str) -> LsResult:
        result = super().ls(path)
        if result.entries is not None:
            result.entries = [entry for entry in result.entries if self._visible(entry["path"])]
        return result

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        result = super().glob(pattern, path)
        if result.matches is not None:
            result.matches = [entry for entry in result.matches if self._visible(entry["path"])]
        return result

    def _visible(self, virtual_path: str) -> bool:
        try:
            candidate = self.boundary.resolve(self._relative(virtual_path))
            self.boundary._assert_not_sensitive(candidate)
        except (PermissionError, OSError):
            return False
        return True

    def _assert_write_scope(self, relative: str) -> None:
        if not self.allowed_write_paths:
            return
        candidate = self.boundary.resolve(relative, for_write=True)
        for allowed in self.allowed_write_paths:
            try:
                candidate.relative_to(allowed)
                return
            except ValueError:
                continue
        raise PathBoundaryError("write is outside the delegated task scope")

    def _lease(self) -> AbstractContextManager[None]:
        if self.lease_manager is None:
            return nullcontext()
        return self.lease_manager.hold(self.task_id)
