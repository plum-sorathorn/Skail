from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path, PurePosixPath
from typing import Any, cast

from deepagents.backends import FilesystemBackend
from deepagents.backends.protocol import (
    EditResult,
    GlobResult,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)

from rudder.runtime.redaction import RedactionRegistry
from rudder.tools.filesystem import FilesystemBoundary, PathBoundaryError

CURRENT_TOOL_CALL_ID: ContextVar[str | None] = ContextVar(
    "rudder_tool_call_id", default=None
)


class PolicyFilesystemBackend(FilesystemBackend):
    """DeepAgents backend with Rudder policy enforced at the dispatch boundary."""

    def __init__(
        self,
        root_dir: Path,
        *,
        redactor: RedactionRegistry,
        task_id: str,
    ) -> None:
        super().__init__(root_dir=root_dir, virtual_mode=True)
        self.boundary = FilesystemBoundary(root_dir, redactor=redactor)
        self.task_id = task_id
        self._call_number = 0

    @staticmethod
    def _relative(path: str) -> str:
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
        result = super().grep(
            pattern,
            path,
            glob,
            max_count=max_count,
            context_lines=context_lines,
        )
        if result.matches is None:
            return result
        safe = []
        for match in result.matches:
            try:
                candidate = self.boundary.resolve(self._relative(match["path"]))
                self.boundary._assert_not_sensitive(candidate)
            except (PermissionError, OSError):
                continue
            match["text"] = self.boundary.redactor.scrub_text(match["text"])
            for field in ("context_before", "context_after"):
                lines = cast(list[dict[str, Any]], match.get(field, []))
                for line in lines:
                    line["text"] = self.boundary.redactor.scrub_text(line["text"])
            safe.append(match)
        result.matches = safe
        return result

    def write(self, file_path: str, content: str) -> WriteResult:
        relative = self._relative(file_path)
        try:
            self.boundary.write_text(
                relative,
                content,
                task_id=self.task_id,
                tool_call_id=self._next_call(),
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
        relative = self._relative(file_path)
        try:
            path = self.boundary.resolve(relative)
            self.boundary._assert_not_sensitive(path)
            content = path.read_text(encoding="utf-8")
            occurrences = content.count(old_string)
            if occurrences == 0:
                return EditResult(error="old_string was not found")
            if occurrences > 1 and not replace_all:
                return EditResult(error="old_string occurs multiple times")
            updated = content.replace(old_string, new_string, -1 if replace_all else 1)
            self.boundary.write_text(
                relative,
                updated,
                task_id=self.task_id,
                tool_call_id=self._next_call(),
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
