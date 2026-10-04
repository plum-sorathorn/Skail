from __future__ import annotations

import hashlib
import mimetypes
import os
import stat
from contextlib import AbstractContextManager, nullcontext
from contextvars import ContextVar
from pathlib import Path, PurePosixPath
from threading import RLock
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
from skail.tools.document_reader import (
    DOCUMENT_SUFFIXES,
    read_bom_text,
    read_document,
    read_image,
)
from skail.tools.filesystem import FilesystemBoundary, PathBoundaryError

CURRENT_TOOL_CALL_ID: ContextVar[str | None] = ContextVar(
    "skail_tool_call_id", default=None
)
MAX_FILE_DIGEST_BYTES = 256 * 1024 * 1024


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
        self._document_results: dict[str, ReadResult] = {}
        self._document_lock = RLock()

    def take_document_result(self, call_id: str) -> ReadResult | None:
        with self._document_lock:
            return self._document_results.pop(call_id, None)

    def _relative(self, path: str) -> str:
        self.boundary.assert_host_path_allowed(path)
        value = PurePosixPath(path)
        if ".." in value.parts or "~" in value.parts:
            raise PathBoundaryError("virtual path traversal is not permitted")
        return str(value).lstrip("/") or "."

    def file_digest(self, file_path: str) -> str:
        """Return a runtime-computed digest for a readable workspace file."""
        relative = self._relative(file_path)
        candidate = self.boundary.resolve(relative)
        self.boundary._assert_not_sensitive(candidate)
        try:
            before = candidate.lstat()
        except OSError as error:
            raise PathBoundaryError("file.evidence_unavailable") from error
        attributes = getattr(before, "st_file_attributes", 0)
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or bool(reparse and attributes & reparse)
            or before.st_size > MAX_FILE_DIGEST_BYTES
        ):
            raise PathBoundaryError("file.evidence_unavailable")
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(candidate, os.O_RDONLY | no_follow)
        except OSError as error:
            raise PathBoundaryError("file.evidence_unavailable") from error
        digest = hashlib.sha256()
        total_bytes = 0
        with os.fdopen(descriptor, "rb", closefd=True) as source:
            opened = os.fstat(source.fileno())
            identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            opened_identity = (
                opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns
            )
            if identity != opened_identity or not stat.S_ISREG(opened.st_mode):
                raise PathBoundaryError("file.evidence_unavailable")
            while True:
                chunk = source.read(min(64 * 1024, MAX_FILE_DIGEST_BYTES + 1 - total_bytes))
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_FILE_DIGEST_BYTES:
                    raise PathBoundaryError("file.evidence_unavailable")
                digest.update(chunk)
            closed = os.fstat(source.fileno())
        try:
            after = candidate.lstat()
            resolved_after = self.boundary.resolve(relative)
            self.boundary._assert_not_sensitive(resolved_after)
        except OSError as error:
            raise PathBoundaryError("file.evidence_unavailable") from error
        if (
            identity
            != (closed.st_dev, closed.st_ino, closed.st_size, closed.st_mtime_ns)
            or identity
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or resolved_after != candidate
            or not stat.S_ISREG(after.st_mode)
            or after.st_nlink != 1
        ):
            raise PathBoundaryError("file.evidence_unavailable")
        return digest.hexdigest()

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
        suffix = path.suffix.lower()
        if suffix in DOCUMENT_SUFFIXES:
            result = read_document(
                path, offset=offset, limit=limit, redactor=self.boundary.redactor
            )
            call_id = CURRENT_TOOL_CALL_ID.get()
            if call_id is not None and result.error is None and not result.no_lines_requested:
                with self._document_lock:
                    self._document_results[call_id] = result
            return result
        if suffix in {".zip", ".tar", ".gz", ".7z", ".rar"}:
            return ReadResult(error="Archive files require a separate archive inspection tool")
        if suffix in {".doc", ".xls", ".ppt", ".odt", ".ods", ".odp"}:
            return ReadResult(error="Convert this legacy document to DOCX, XLSX, or PPTX first")
        if suffix in {".mp3", ".wav", ".mp4", ".mov", ".avi"}:
            return ReadResult(error="Audio and video files require a separate media tool")
        media_type, _ = mimetypes.guess_type(path.name)
        if media_type is not None and media_type.startswith("image/") and suffix != ".svg":
            if media_type not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
                return ReadResult(error="Image format is unsupported; use PNG, JPEG, WebP, or GIF")
            return read_image(path)
        try:
            with path.open("rb") as source:
                bom = source.read(3)
        except OSError as error:
            return ReadResult(error=str(error))
        if bom.startswith((b"\xff\xfe", b"\xfe\xff")):
            return read_bom_text(
                path, offset=offset, limit=limit, redactor=self.boundary.redactor
            )
        result = super().read(file_path, offset, limit)
        if result.file_data is not None and result.file_data.get("encoding") == "utf-8":
            result.file_data["content"] = self.boundary.redactor.scrub_text(
                str(result.file_data["content"])
            )
        elif result.file_data is not None and result.file_data.get("encoding") == "base64":
            if media_type is None or not media_type.startswith("image/"):
                file_kind = "PDF" if media_type == "application/pdf" else "binary file"
                return ReadResult(
                    error=(
                        f"{file_kind} content cannot be read as text; "
                        "extract text with a suitable tool"
                    )
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
