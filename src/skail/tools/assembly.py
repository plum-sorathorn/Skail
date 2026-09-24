from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

from deepagents.middleware.subagents import CompiledSubAgent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import interrupt

from skail.config.paths import workspace_state_dir
from skail.domain.security import identify_workspace
from skail.domain.usage import NormalizedUsage
from skail.runtime.deepagents_adapter import build_lead_agent, is_graph_interrupt
from skail.runtime.failure_monitor import FailureMonitor
from skail.runtime.interrupts import QuestionStore
from skail.runtime.leases import WorkspaceLeaseManager
from skail.runtime.redaction import RedactionRegistry
from skail.tools.approvals import ApprovalStore
from skail.tools.artifacts import ArtifactStore
from skail.tools.backend import CURRENT_TOOL_CALL_ID, PolicyFilesystemBackend
from skail.tools.execution import (
    CommandRequest,
    ExecutionPolicy,
    ExecutionSecurityContext,
)
from skail.tools.registry import SideEffect, ToolMetadata, ToolRegistry


class ToolArgValidationError(ValueError):
    """Recoverable tool-arg rejection with an actionable schema hint."""


_KEY_CAMEL = re.compile(r"(?<!^)(?=[A-Z])")

_GREP_FIELDS = ("pattern", "path", "glob", "max_count", "context_lines")
_GLOB_FIELDS = ("pattern", "path")
_LS_FIELDS = ("path",)
_READ_FIELDS = ("file_path", "offset", "limit")
_WRITE_FIELDS = ("file_path", "content")
_EDIT_FIELDS = ("file_path", "old_string", "new_string", "replace_all")

_GREP_ALIASES = {
    "query": "pattern",
    "search": "pattern",
    "text": "pattern",
    "regex": "pattern",
    "keyword": "pattern",
    "dir": "path",
    "directory": "path",
    "folder": "path",
    "cwd": "path",
    "filepath": "path",
    "file": "path",
    "include": "glob",
    "includes": "glob",
    "filepattern": "glob",
    "file_pattern": "glob",
    "globpattern": "glob",
    "glob_pattern": "glob",
    "maxresults": "max_count",
    "max_results": "max_count",
    "limit": "max_count",
    "count": "max_count",
    "context": "context_lines",
    "contextlines": "context_lines",
    "context_lines": "context_lines",
    "lines": "context_lines",
}

_GLOB_ALIASES = {
    "query": "pattern",
    "search": "pattern",
    "glob": "pattern",
    "globpattern": "pattern",
    "glob_pattern": "pattern",
    "include": "pattern",
    "includes": "pattern",
    "filepattern": "pattern",
    "file_pattern": "pattern",
    "dir": "path",
    "directory": "path",
    "folder": "path",
    "cwd": "path",
    "filepath": "path",
    "file": "path",
}

_LS_ALIASES = {
    "dir": "path",
    "directory": "path",
    "folder": "path",
    "cwd": "path",
    "filepath": "path",
    "file": "path",
}

_READ_ALIASES = {
    "path": "file_path",
    "filepath": "file_path",
    "file": "file_path",
    "filename": "file_path",
    "offset": "offset",
    "start": "offset",
    "limit": "limit",
    "count": "limit",
    "maxlines": "limit",
    "max_lines": "limit",
}

_NORMALIZABLE_TOOLS = {
    "grep": (_GREP_FIELDS, _GREP_ALIASES, "grep(pattern, path='.', glob=None)"),
    "glob": (_GLOB_FIELDS, _GLOB_ALIASES, "glob(pattern, path=None)"),
    "ls": (_LS_FIELDS, _LS_ALIASES, "ls(path='.')"),
    "read": (_READ_FIELDS, _READ_ALIASES, "read(file_path, offset=0, limit=2000)"),
    "read_file": (_READ_FIELDS, _READ_ALIASES, "read(file_path, offset=0, limit=2000)"),
}


def _normalize_key(raw: str) -> str:
    key = raw.strip().replace("-", "_").replace(" ", "_")
    key = _KEY_CAMEL.sub("_", key).lower()
    key = re.sub(r"__+", "_", key)
    return key


def _coerce_int(value: object, *, field: str, tool_hint: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ToolArgValidationError(
            f"invalid {field}: expected int for {tool_hint}; got boolean"
        )
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if re.fullmatch(r"[+-]?\d+", stripped or ""):
            return int(stripped)
    raise ToolArgValidationError(
        f"invalid {field}: expected int for {tool_hint}; got {value!r}"
    )


def normalize_tool_args(name: object, args: object) -> dict[str, Any]:
    """Normalize read-only tool args (grep/glob/ls/read) before validation.

    Handles wrong-case keys, common aliases, JSON-string args, and safe
    defaults for optional fields. Raises ToolArgValidationError naming the
    expected schema for missing/invalid required fields. Safety-relevant
    denials are never normalized away; unknown tools pass through unchanged.
    """
    tool = str(name or "").strip().lower()
    if tool not in _NORMALIZABLE_TOOLS:
        if isinstance(args, dict):
            return dict(args)
        return {}
    fields, aliases, hint = _NORMALIZABLE_TOOLS[tool]
    if args is None:
        args = {}
    if isinstance(args, str):
        stripped = args.strip()
        try:
            decoded = json.loads(stripped) if stripped else {}
        except json.JSONDecodeError as exc:
            raise ToolArgValidationError(
                f"invalid args for {tool}: expected {hint}; got a string "
                f"that is not JSON ({exc.msg})"
            ) from exc
        if not isinstance(decoded, dict):
            raise ToolArgValidationError(
                f"invalid args for {tool}: expected {hint}; got JSON {type(decoded).__name__}"
            )
        args = decoded
    if not isinstance(args, dict):
        raise ToolArgValidationError(
            f"invalid args for {tool}: expected {hint}; got {type(args).__name__}"
        )
    raw: dict[str, Any] = dict(args)
    if len(raw) == 1:
        sole = next(iter(raw.values()))
        if isinstance(sole, str):
            stripped = sole.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    decoded = json.loads(stripped)
                except json.JSONDecodeError:
                    decoded = None
                if isinstance(decoded, dict):
                    raw = decoded
    normalized: dict[str, Any] = {}
    for raw_key, value in raw.items():
        if not isinstance(raw_key, str):
            continue
        key = _normalize_key(raw_key)
        key = aliases.get(key, key)
        if key not in fields:
            continue
        if isinstance(value, str):
            value = value.strip()
        normalized[key] = value
    if tool == "grep":
        pattern = normalized.get("pattern")
        if pattern is None or (isinstance(pattern, str) and not pattern):
            raise ToolArgValidationError(
                "invalid grep args: expected grep(pattern, path='.', glob=None); "
                "pattern is required and must be a non-empty string"
            )
        if not isinstance(pattern, str):
            raise ToolArgValidationError(
                "invalid grep args: expected grep(pattern, path='.', glob=None); "
                f"pattern must be a string, got {type(pattern).__name__}"
            )
        if normalized.get("path") in (None, ""):
            normalized.pop("path", None)
        if normalized.get("glob") in (None, ""):
            normalized.pop("glob", None)
        if "max_count" in normalized:
            coerced = _coerce_int(
                normalized["max_count"], field="max_count", tool_hint="grep"
            )
            if coerced is None:
                normalized.pop("max_count", None)
            else:
                normalized["max_count"] = coerced
        if "context_lines" in normalized:
            coerced = _coerce_int(
                normalized["context_lines"], field="context_lines", tool_hint="grep"
            )
            normalized["context_lines"] = 0 if coerced is None else coerced
        return normalized
    if tool == "glob":
        pattern = normalized.get("pattern")
        if pattern is None or (isinstance(pattern, str) and not pattern):
            raise ToolArgValidationError(
                "invalid glob args: expected glob(pattern, path=None); "
                "pattern is required and must be a non-empty string"
            )
        if not isinstance(pattern, str):
            raise ToolArgValidationError(
                "invalid glob args: expected glob(pattern, path=None); "
                f"pattern must be a string, got {type(pattern).__name__}"
            )
        if normalized.get("path") in (None, ""):
            normalized.pop("path", None)
        return normalized
    if tool == "ls":
        path = normalized.get("path")
        if path is None or (isinstance(path, str) and not path):
            return {"path": "."}
        if not isinstance(path, str):
            raise ToolArgValidationError(
                "invalid ls args: expected ls(path='.'); "
                f"path must be a string, got {type(path).__name__}"
            )
        return {"path": path}
    file_path = normalized.get("file_path")
    if file_path is None or (isinstance(file_path, str) and not file_path):
        raise ToolArgValidationError(
            "invalid read args: expected read(file_path, offset=0, limit=2000); "
            "file_path is required and must be a non-empty string"
        )
    if not isinstance(file_path, str):
        raise ToolArgValidationError(
            "invalid read args: expected read(file_path, offset=0, limit=2000); "
            f"file_path must be a string, got {type(file_path).__name__}"
        )
    result: dict[str, Any] = {"file_path": file_path}
    if normalized.get("offset") is not None:
        result["offset"] = _coerce_int(normalized["offset"], field="offset", tool_hint=tool)
    if normalized.get("limit") is not None:
        result["limit"] = _coerce_int(normalized["limit"], field="limit", tool_hint=tool)
    return result


def _normalize_request_args(request: ToolCallRequest) -> ToolCallRequest:
    try:
        normalized = normalize_tool_args(
            request.tool_call.get("name"), request.tool_call.get("args", {})
        )
    except ToolArgValidationError:
        return request
    original = request.tool_call.get("args", {})
    if isinstance(original, dict) and normalized == original:
        return request
    if not isinstance(normalized, dict):
        return request
    return request.override(
        tool_call={**request.tool_call, "args": normalized}
    )


def _validation_error_message(request: ToolCallRequest) -> str | None:
    try:
        normalize_tool_args(
            request.tool_call.get("name"), request.tool_call.get("args", {})
        )
    except ToolArgValidationError as exc:
        return str(exc)
    return None


_MAX_FAILURE_REASON_LENGTH = 500


def _failure_reason(value: object, redactor: Any) -> str:
    """Return a redacted, length-bounded reason for a tool failure event."""
    text = value if isinstance(value, str) else str(value)
    try:
        scrubbed = redactor.scrub(text) if hasattr(redactor, "scrub") else text
    except Exception:
        scrubbed = text
    if not isinstance(scrubbed, str):
        scrubbed = str(scrubbed)
    cleaned = scrubbed.strip()
    if not cleaned:
        return "tool error"
    return cleaned[:_MAX_FAILURE_REASON_LENGTH]


class ProfileToolVisibilityMiddleware(AgentMiddleware[Any, Any, Any]):
    def __init__(
        self,
        visible_names: frozenset[str],
        *,
        blocked_message: Callable[[str], str] | None = None,
    ) -> None:
        self._visible_names = visible_names
        self._blocked_message = blocked_message

    def _blocked_tool(self, name: str, call_id: str | None) -> ToolMessage:
        if self._blocked_message is not None:
            content = self._blocked_message(name)
        else:
            content = "tool is not permitted for this profile"
        return ToolMessage(content=content, tool_call_id=str(call_id or ""), status="error")

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        return handler(request.override(tools=self._filter(request.tools)))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        return await handler(request.override(tools=self._filter(request.tools)))

    def _filter(self, tools: Sequence[Any]) -> list[Any]:
        return [tool for tool in tools if _tool_name(tool) in self._visible_names]

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Any],
    ) -> ToolMessage | Any:
        if request.tool_call["name"] not in self._visible_names:
            return self._blocked_tool(request.tool_call["name"], request.tool_call["id"])
        token = CURRENT_TOOL_CALL_ID.set(request.tool_call["id"])
        try:
            return handler(request)
        finally:
            CURRENT_TOOL_CALL_ID.reset(token)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Any]],
    ) -> ToolMessage | Any:
        if request.tool_call["name"] not in self._visible_names:
            return self._blocked_tool(request.tool_call["name"], request.tool_call["id"])
        token = CURRENT_TOOL_CALL_ID.set(request.tool_call["id"])
        try:
            return await handler(request)
        finally:
            CURRENT_TOOL_CALL_ID.reset(token)


def _tool_name(value: Any) -> str | None:
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    if isinstance(value, dict):
        candidate = value.get("name")
        if isinstance(candidate, str):
            return candidate
        function = value.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            return str(function["name"])
    return None


def _is_decision_gate_rejection(name: str, result: object) -> bool:
    """True only for ToolMessages produced by the execution-decision gate.

    The gate emits `execution.decision_required` (operational tool before a
    decision), `execution.question_required` (work before a required answer),
    `execution.decision_exhausted` (terminal lock: repairs spent with no decision),
    or `decision.*` codes (rejected `execution_decision` calls) via
    `_decision_required`/`_decision_rejected` with status="error". Requiring
    both the tool-call context (a named tool passing through this middleware)
    and the strict stable-code prefix avoids misfiring on arbitrary provider
    text that merely mentions decisions. Kept here (rather than flipping the
    gate to status="blocked") because contract tests assert gate rejections
    surface with status=="error".
    """
    if not isinstance(name, str) or not name:
        return False
    content = getattr(result, "content", None)
    if isinstance(content, list):
        content = " ".join(str(part) for part in content)
    if not isinstance(content, str):
        return False
    text = content.strip()
    return (
        text.startswith("execution.decision_required")
        or text.startswith("execution.question_required")
        or text.startswith("execution.decision_exhausted")
        or text.startswith("execution.intent_conflict")
        or text.startswith("execution.agent_count_conflict")
        or text.startswith("execution.agent_scope_conflict")
        or text.startswith("decision.")
    )


def _is_decision_requirement_rejection(result: object) -> bool:
    """True when an operational tool simply arrived before a decision."""

    content = getattr(result, "content", None)
    if isinstance(content, list):
        content = " ".join(str(part) for part in content)
    if not isinstance(content, str):
        return False
    return content.strip().startswith(
        ("execution.decision_required", "execution.question_required")
    )


def _tool_result_status(result: object) -> str | None:
    status = getattr(result, "status", None)
    content = getattr(result, "content", result)
    if status is None and isinstance(content, dict):
        status = content.get("status")
    if status is None and isinstance(content, str):
        try:
            decoded = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            decoded = None
        if isinstance(decoded, dict):
            status = decoded.get("status")
    if not isinstance(status, str):
        return None
    normalized = status.lower()
    if normalized in {"error", "failed", "failure"}:
        return "error"
    if normalized in {"blocked", "approval_required", "rejected", "denied"}:
        return "blocked"
    if normalized in {"completed", "succeeded", "success", "ok"}:
        return "success"
    return None


class RuntimeActivityMiddleware(AgentMiddleware[Any, Any, Any]):
    def __init__(
        self,
        *,
        model_name: str,
        emit: Callable[..., None],
        redactor: Any,
        model_response_observer: Callable[[ModelResponse[Any]], None] | None = None,
        usage_normalizer: Callable[[ModelResponse[Any]], NormalizedUsage | None] | None = None,
        model_call_guard: Callable[[], None] | None = None,
    ) -> None:
        self.model_name = model_name
        self.emit = emit
        self.monitor = FailureMonitor(redactor)
        self._redactor = redactor
        self.model_response_observer = model_response_observer
        self.usage_normalizer = usage_normalizer
        self.model_call_guard = model_call_guard

    def _emit_failure(self, name: str, reason_value: object) -> None:
        reason = _failure_reason(reason_value, self._redactor)
        try:
            self.emit("tool.failed", name, reason)
        except TypeError:
            self.emit("tool.failed", name)

    def _usage_for(self, response: ModelResponse[Any]) -> NormalizedUsage | None:
        """Best-effort usage extraction; telemetry failures never propagate."""
        if self.usage_normalizer is None:
            return None
        try:
            return self.usage_normalizer(response)
        except Exception:
            return None

    def _emit_model_completed(self, response: ModelResponse[Any]) -> None:
        usage = self._usage_for(response)
        if usage is None:
            self.emit("model.completed", self.model_name)
            return
        try:
            self.emit("model.completed", self.model_name, usage)
        except TypeError:
            self.emit("model.completed", self.model_name)

    @staticmethod
    def _response_has_tool_calls(response: ModelResponse[Any]) -> bool:
        """Whether the model response requests tool execution (loop continues)."""
        result = getattr(response, "result", None)
        if isinstance(result, (list, tuple)):
            return any(getattr(message, "tool_calls", None) for message in result)
        return bool(getattr(result, "tool_calls", None))

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        if self.model_call_guard is not None:
            self.model_call_guard()
        self.emit("model.started", self.model_name)
        try:
            response = handler(request)
        except Exception:
            self.emit("model.failed", self.model_name)
            raise
        self._emit_model_completed(response)
        if self._response_has_tool_calls(response):
            # The agent loop continues: reset only the error streak so the
            # repeated-call window still accumulates across model turns.
            self.monitor.observe_progress()
        else:
            self.monitor.observe_success()
        if self.model_response_observer is not None:
            self.model_response_observer(response)
        return response

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        if self.model_call_guard is not None:
            self.model_call_guard()
        self.emit("model.started", self.model_name)
        try:
            response = await handler(request)
        except Exception:
            self.emit("model.failed", self.model_name)
            raise
        self._emit_model_completed(response)
        if self._response_has_tool_calls(response):
            # The agent loop continues: reset only the error streak so the
            # repeated-call window still accumulates across model turns.
            self.monitor.observe_progress()
        else:
            self.monitor.observe_success()
        if self.model_response_observer is not None:
            self.model_response_observer(response)
        return response

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Any],
    ) -> ToolMessage | Any:
        return self._run_tool(request, handler)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Any]],
    ) -> ToolMessage | Any:
        name = request.tool_call["name"]
        hint = _validation_error_message(request)
        if hint is not None:
            self._emit_failure(name, hint)
            # Orphan (pre-handler) path: exempt the call from the repeated-call
            # window but still count the defect tool-scoped.
            self.monitor.observe_call(name, request.tool_call.get("args", {}), executed=False)
            self.monitor.observe_error(hint, tool=name)
            return ToolMessage(content=hint, tool_call_id=request.tool_call["id"], status="error")
        request = _normalize_request_args(request)
        signal = self.monitor.observe_call(name, request.tool_call.get("args", {}))
        if signal is not None:
            raise RuntimeError(signal)
        self.emit("tool.started", name)
        try:
            result = await handler(request)
        except Exception as exc:
            self.monitor.discard_call_window()
            if is_graph_interrupt(exc):
                self.monitor.observe_progress()
                raise
            self._emit_failure(name, exc)
            signal = self.monitor.observe_error(exc, tool=name)
            if signal is not None:
                raise RuntimeError(signal) from exc
            raise
        status = _tool_result_status(result)
        if status == "error":
            self.monitor.discard_call_window()
            self._emit_failure(name, getattr(result, "content", "tool error"))
            if _is_decision_gate_rejection(name, result):
                if _is_decision_requirement_rejection(result):
                    self.monitor.observe_error(
                        getattr(result, "content", "tool blocked"), blocked=True
                    )
                else:
                    signal = self.monitor.observe_error(
                        getattr(result, "content", "tool error"), tool=name
                    )
                    if signal is not None:
                        raise RuntimeError(signal)
            else:
                signal = self.monitor.observe_error(
                    getattr(result, "content", "tool error"), tool=name
                )
                if signal is not None:
                    raise RuntimeError(signal)
        elif status == "blocked":
            self.monitor.discard_call_window()
            self._emit_failure(name, getattr(result, "content", "tool blocked"))
            self.monitor.observe_error(getattr(result, "content", "tool blocked"), blocked=True)
        else:
            self.emit("tool.completed", name)
            self.monitor.observe_progress()
        return result

    def _run_tool(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Any],
    ) -> ToolMessage | Any:
        name = request.tool_call["name"]
        hint = _validation_error_message(request)
        if hint is not None:
            self._emit_failure(name, hint)
            # Orphan (pre-handler) path: exempt the call from the repeated-call
            # window but still count the defect tool-scoped.
            self.monitor.observe_call(name, request.tool_call.get("args", {}), executed=False)
            self.monitor.observe_error(hint, tool=name)
            return ToolMessage(content=hint, tool_call_id=request.tool_call["id"], status="error")
        request = _normalize_request_args(request)
        signal = self.monitor.observe_call(name, request.tool_call.get("args", {}))
        if signal is not None:
            raise RuntimeError(signal)
        self.emit("tool.started", name)
        try:
            result = handler(request)
        except Exception as exc:
            self.monitor.discard_call_window()
            if is_graph_interrupt(exc):
                self.monitor.observe_progress()
                raise
            self._emit_failure(name, exc)
            signal = self.monitor.observe_error(exc, tool=name)
            if signal is not None:
                raise RuntimeError(signal) from exc
            raise
        status = _tool_result_status(result)
        if status == "error":
            self.monitor.discard_call_window()
            self._emit_failure(name, getattr(result, "content", "tool error"))
            if _is_decision_gate_rejection(name, result):
                if _is_decision_requirement_rejection(result):
                    self.monitor.observe_error(
                        getattr(result, "content", "tool blocked"), blocked=True
                    )
                else:
                    signal = self.monitor.observe_error(
                        getattr(result, "content", "tool error"), tool=name
                    )
                    if signal is not None:
                        raise RuntimeError(signal)
            else:
                signal = self.monitor.observe_error(
                    getattr(result, "content", "tool error"), tool=name
                )
                if signal is not None:
                    raise RuntimeError(signal)
        elif status == "blocked":
            self.monitor.discard_call_window()
            self._emit_failure(name, getattr(result, "content", "tool blocked"))
            self.monitor.observe_error(getattr(result, "content", "tool blocked"), blocked=True)
        else:
            self.emit("tool.completed", name)
            self.monitor.observe_progress()
        return result


def default_registry(*, version: str = "0.7.13") -> ToolRegistry:
    read_profiles = frozenset(
        {"lead", "general-purpose", "explorer", "implementer", "tester", "reviewer", "researcher"}
    )
    write_profiles = frozenset({"lead", "general-purpose", "implementer"})
    execute_profiles = frozenset({"lead", "general-purpose", "implementer", "tester", "reviewer"})
    declarations = (
        ("ls", SideEffect.READ_ONLY, read_profiles, "allow"),
        ("glob", SideEffect.READ_ONLY, read_profiles, "allow"),
        ("grep", SideEffect.READ_ONLY, read_profiles, "allow"),
        ("read_file", SideEffect.READ_ONLY, read_profiles, "allow"),
        ("write_file", SideEffect.WORKSPACE_WRITE, write_profiles, "policy"),
        ("edit_file", SideEffect.WORKSPACE_WRITE, write_profiles, "policy"),
        ("execute", SideEffect.UNKNOWN, execute_profiles, "policy"),
        ("write_todos", SideEffect.WORKSPACE_WRITE, frozenset({"lead"}), "allow"),
        ("task", SideEffect.UNKNOWN, frozenset({"lead"}), "policy"),
        ("skills", SideEffect.READ_ONLY, read_profiles, "allow"),
        ("memory", SideEffect.READ_ONLY, read_profiles, "allow"),
        ("ask_user", SideEffect.READ_ONLY, read_profiles, "allow"),
    )
    return ToolRegistry(
        [
            ToolMetadata(
                name=name,
                description=name.replace("_", " "),
                source="skail/deepagents",
                version=version,
                schema={"type": "object", "properties": {}},
                side_effect=effect,
                approval=approval,
                profiles=profiles,
            )
            for name, effect, profiles, approval in declarations
        ]
    )


def build_default_agent(
    model: BaseChatModel,
    *,
    workspace: Path,
    profile: str,
    subagents: Sequence[CompiledSubAgent] | None = None,
    skills: list[str] | None = None,
    memory: list[str] | None = None,
    task_id: str = "lead",
    redactor: RedactionRegistry | None = None,
    approvals: ApprovalStore | None = None,
    question_store: QuestionStore | None = None,
    graph_id: str = "lead",
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    execution_context: ExecutionSecurityContext | None = None,
    registry: ToolRegistry | None = None,
    extension_tools: Sequence[Any] = (),
    lease_manager: WorkspaceLeaseManager | None = None,
    extra_middleware: Sequence[AgentMiddleware[Any, Any, Any]] = (),
    blocked_tool_message: Callable[[str], str] | None = None,
    runtime_event: Callable[..., None] | None = None,
    runtime_model_name: str | None = None,
      model_response_observer: Callable[[ModelResponse[Any]], None] | None = None,
      usage_normalizer: Callable[[ModelResponse[Any]], NormalizedUsage | None] | None = None,
      model_call_guard: Callable[[], None] | None = None,
    allowed_write_paths: tuple[str, ...] = (),
    forbidden_host_paths: tuple[Path, ...] = (),
    execute_allowed: bool = True,
    system_prompt: str | None = None,
    session_id: str = "",
    run_id: str = "",
    state_dir: Path | None = None,
) -> Any:
    """Assemble pinned DeepAgents tools behind Skail's workspace and shell policy."""

    registry = registry or default_registry()
    if profile not in {item for name in registry.names for item in registry.get(name).profiles}:
        raise ValueError(f"unknown tool profile: {profile}")
    policy = ExecutionPolicy(workspace, execution_context)
    redaction = redactor or RedactionRegistry()
    artifacts = ArtifactStore(
        (state_dir or workspace_state_dir(identify_workspace(workspace))) / "artifacts",
        redaction,
    )

    @tool("execute")
    def execute(command: str, arguments: tuple[str, ...] = ()) -> dict[str, Any]:
        """Execute a structured command under Skail policy."""

        if not execute_allowed:
            return {
                "status": "rejected",
                "returncode": None,
                "output": "execute is outside the delegated task permission or path scope",
                "artifact": None,
            }

        from contextlib import nullcontext

        lease = nullcontext() if lease_manager is None else lease_manager.hold(task_id)
        action_id = CURRENT_TOOL_CALL_ID.get() or ""
        request = CommandRequest(
            command, arguments, workspace, session_id=session_id, run_id=run_id,
            task_id=task_id, action_id=action_id,
        )
        with lease:
            result = policy.run(
                request,
                interactive=False,
                approvals=approvals,
            )
        if result.status == "approval_required":
            interrupt(
                {
                    "kind": "approval",
                    "type": "command_approval",
                    "command": command,
                    "arguments": arguments,
                    "cwd": str(workspace),
                    "session_id": session_id,
                    "run_id": run_id,
                    "task_id": task_id,
                    "action_id": action_id,
                }
            )
            with lease:
                result = policy.run(
                    request,
                    interactive=False,
                    approvals=approvals,
                )
        captured = artifacts.capture(
            "execute", {"stdout": result.stdout, "stderr": result.stderr}
        )
        return {
            "status": result.status,
            "returncode": result.returncode,
            "output": captured.excerpt,
            "artifact": None
            if captured.artifact_path is None
            else captured.artifact_path.name,
        }

    @tool("ask_user")
    def ask_user(
        prompt: str,
        reason: str,
        blocking_scope: str = "task",
        options: tuple[str, ...] = (),
    ) -> str:
        """Pause the current graph for a durable structured user answer."""

        if question_store is None:
            return "ask_user is unavailable without a durable question store"
        question = question_store.ask(
            graph_id=graph_id,
            task_id=None if task_id == "lead" else task_id,
            prompt=prompt,
            options=options,
            reason=reason,
            blocking_scope=blocking_scope,
            idempotency_key=(
                f"{graph_id}:{CURRENT_TOOL_CALL_ID.get() or prompt + ':' + reason}"
            ),
        )
        answer = interrupt(
            {
                "kind": "question",
                "question_id": question.question_id,
                "prompt": prompt,
                "options": options,
                "reason": reason,
                "task_id": question.task_id,
                "blocking_scope": blocking_scope,
            }
        )
        if not isinstance(answer, str):
            raise ValueError("question answer must be a string")
        answered = question_store.answer(question.question_id, answer, graph_id=graph_id)
        if runtime_event is not None:
            runtime_event("user.answer", question.question_id, answered.answer or "")
        return answered.answer or ""

    custom_tools: list[Any] = list(extension_tools)
    visible_names = frozenset(item.name for item in registry.visible_to(profile))
    visible_names |= frozenset(
        name for name in (_tool_name(item) for item in extension_tools) if name is not None
    )
    if subagents:
        visible_names |= {"task"}
    if "execute" in visible_names:
        custom_tools.append(execute)
    if "ask_user" in visible_names:
        custom_tools.append(ask_user)
    activity_middleware: list[AgentMiddleware[Any, Any, Any]] = []
    if (
        runtime_event is not None
        or model_response_observer is not None
        or model_call_guard is not None
    ):
        activity_middleware.append(
            RuntimeActivityMiddleware(
                model_name=str(
                    runtime_model_name or getattr(model, "model_name", "unknown")
                ),
                emit=runtime_event or (lambda *_args: None),
                redactor=redaction,
                model_response_observer=model_response_observer,
                usage_normalizer=usage_normalizer,
                model_call_guard=model_call_guard,
            )
        )
    return build_lead_agent(
        model,
        tools=custom_tools,
        subagents=subagents,
        backend=PolicyFilesystemBackend(
            workspace,
            redactor=redaction,
            task_id=task_id,
            lease_manager=lease_manager,
            allowed_write_paths=allowed_write_paths,
            forbidden_host_paths=forbidden_host_paths,
            state_dir=state_dir,
        ),
        skills=skills,
        memory=memory,
        middleware=[
            ProfileToolVisibilityMiddleware(visible_names, blocked_message=blocked_tool_message),
            *activity_middleware,
            *extra_middleware,
        ],
        checkpointer=checkpointer,
        system_prompt=system_prompt,
    )
