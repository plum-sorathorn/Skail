from __future__ import annotations

import json
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

from rudder.runtime.deepagents_adapter import build_lead_agent
from rudder.runtime.failure_monitor import FailureMonitor
from rudder.runtime.interrupts import QuestionStore
from rudder.runtime.leases import WorkspaceLeaseManager
from rudder.runtime.redaction import RedactionRegistry
from rudder.tools.approvals import ApprovalStore
from rudder.tools.artifacts import ArtifactStore
from rudder.tools.backend import CURRENT_TOOL_CALL_ID, PolicyFilesystemBackend
from rudder.tools.execution import (
    CommandRequest,
    ExecutionPolicy,
    ExecutionSecurityContext,
)
from rudder.tools.registry import SideEffect, ToolMetadata, ToolRegistry


class ProfileToolVisibilityMiddleware(AgentMiddleware[Any, Any, Any]):
    def __init__(self, visible_names: frozenset[str]) -> None:
        self._visible_names = visible_names

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
            return ToolMessage(
                content="tool is not permitted for this profile",
                tool_call_id=request.tool_call["id"],
                status="error",
            )
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
            return ToolMessage(
                content="tool is not permitted for this profile",
                tool_call_id=request.tool_call["id"],
                status="error",
            )
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
        emit: Callable[[str, str], None],
        redactor: Any,
        model_response_observer: Callable[[ModelResponse[Any]], None] | None = None,
    ) -> None:
        self.model_name = model_name
        self.emit = emit
        self.monitor = FailureMonitor(redactor)
        self.model_response_observer = model_response_observer

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        self.emit("model.started", self.model_name)
        try:
            response = handler(request)
        except Exception:
            self.emit("model.failed", self.model_name)
            raise
        self.emit("model.completed", self.model_name)
        if self.model_response_observer is not None:
            self.model_response_observer(response)
        return response

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        self.emit("model.started", self.model_name)
        try:
            response = await handler(request)
        except Exception:
            self.emit("model.failed", self.model_name)
            raise
        self.emit("model.completed", self.model_name)
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
        signal = self.monitor.observe_call(name, request.tool_call.get("args", {}))
        if signal is not None:
            raise RuntimeError(signal)
        self.emit("tool.started", name)
        try:
            result = await handler(request)
        except Exception as exc:
            self.emit("tool.failed", name)
            signal = self.monitor.observe_error(exc)
            if signal is not None:
                raise RuntimeError(signal) from exc
            raise
        status = _tool_result_status(result)
        if status == "error":
            self.emit("tool.failed", name)
            signal = self.monitor.observe_error(getattr(result, "content", "tool error"))
            if signal is not None:
                raise RuntimeError(signal)
        elif status == "blocked":
            self.emit("tool.failed", name)
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
        signal = self.monitor.observe_call(name, request.tool_call.get("args", {}))
        if signal is not None:
            raise RuntimeError(signal)
        self.emit("tool.started", name)
        try:
            result = handler(request)
        except Exception as exc:
            self.emit("tool.failed", name)
            signal = self.monitor.observe_error(exc)
            if signal is not None:
                raise RuntimeError(signal) from exc
            raise
        status = _tool_result_status(result)
        if status == "error":
            self.emit("tool.failed", name)
            signal = self.monitor.observe_error(getattr(result, "content", "tool error"))
            if signal is not None:
                raise RuntimeError(signal)
        elif status == "blocked":
            self.emit("tool.failed", name)
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
                source="rudder/deepagents",
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
    runtime_event: Callable[[str, str], None] | None = None,
    runtime_model_name: str | None = None,
    model_response_observer: Callable[[ModelResponse[Any]], None] | None = None,
    allowed_write_paths: tuple[str, ...] = (),
    forbidden_host_paths: tuple[Path, ...] = (),
    execute_allowed: bool = True,
    system_prompt: str | None = None,
    session_id: str = "",
    run_id: str = "",
) -> Any:
    """Assemble pinned DeepAgents tools behind Rudder's workspace and shell policy."""

    registry = registry or default_registry()
    if profile not in {item for name in registry.names for item in registry.get(name).profiles}:
        raise ValueError(f"unknown tool profile: {profile}")
    policy = ExecutionPolicy(workspace, execution_context)
    redaction = redactor or RedactionRegistry()
    artifacts = ArtifactStore(workspace / ".rudder" / "artifacts", redaction)

    @tool("execute")
    def execute(command: str, arguments: tuple[str, ...] = ()) -> dict[str, Any]:
        """Execute a structured command under Rudder policy."""

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
        return question_store.answer(
            question.question_id, answer, graph_id=graph_id
        ).answer or ""

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
    if runtime_event is not None:
        activity_middleware.append(
            RuntimeActivityMiddleware(
                model_name=str(
                    runtime_model_name or getattr(model, "model_name", "unknown")
                ),
                emit=runtime_event,
                redactor=redaction,
                model_response_observer=model_response_observer,
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
        ),
        skills=skills,
        memory=memory,
        middleware=[
            ProfileToolVisibilityMiddleware(visible_names),
            *activity_middleware,
            *extra_middleware,
        ],
        checkpointer=checkpointer,
        system_prompt=system_prompt,
    )
