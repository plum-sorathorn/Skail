from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NotRequired
from uuid import uuid4

from deepagents import create_deep_agent
from deepagents.middleware.subagents import CompiledSubAgent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph

from skail.agents.context import ContextAssembler
from skail.providers.base import ProviderAdapter
from skail.providers.fallback import FallbackBinding, ProviderFallbackPolicy
from skail.runtime.deepagents_adapter import ChildRunGate
from skail.runtime.errors import FrameworkContractError
from skail.runtime.model_middleware import AssignmentState, TaskBoundModelMiddleware


@dataclass(frozen=True)
class SpikeAssignment:
    assignment_id: str
    attempt_id: str
    model_id: str
    provider: str = "fake"
    reservation_id: str = "spike-reservation"


class SpikeTaskState(AssignmentState):
    skail_task_id: NotRequired[str]
    task_description: NotRequired[str]
    validation_trace: NotRequired[tuple[str, ...]]
    child_output: NotRequired[str]
    context_packet: NotRequired[object]


def build_compiled_task_subagent(
    *,
    name: str,
    description: str,
    assignment: SpikeAssignment,
    models: Mapping[str, BaseChatModel],
    construction_model: BaseChatModel | None = None,
    tools: Sequence[BaseTool | Callable[..., Any] | dict[str, Any]] = (),
    execution_gate: ChildRunGate | None = None,
    task_id_factory: Callable[[], str] | None = None,
    providers: Mapping[str, ProviderAdapter] | None = None,
    fallback_policy: ProviderFallbackPolicy | None = None,
    assignment_models: Mapping[str, str] | None = None,
    active_assignments: Mapping[str, FallbackBinding] | None = None,
    usage_callback: Callable[[str, object, str], None] | None = None,
) -> CompiledSubAgent:
    try:
        selected_model = models[assignment.model_id]
    except KeyError as exc:
        raise FrameworkContractError(
            "route.assigned_model_unavailable",
            "the spike assignment references an unavailable model",
            model=assignment.model_id,
        ) from exc

    recorded_assignments = dict(assignment_models or {})
    recorded_assignments[assignment.assignment_id] = assignment.model_id
    middleware = TaskBoundModelMiddleware(
        models,
        assignments=recorded_assignments,
        allow_delegation=False,
        providers=providers,
        fallback_policy=fallback_policy,
        active_assignments=active_assignments,
        usage_callback=usage_callback,
    )
    create_task_id = task_id_factory or (lambda: str(uuid4()))
    child = create_deep_agent(
        model=construction_model or selected_model,
        tools=tools,
        middleware=[middleware],
        state_schema=SpikeTaskState,
        name=f"{name}-profile",
    )

    def validate_task(state: SpikeTaskState) -> dict[str, Any]:
        task_description = _last_message_text(state.get("messages", []))
        if not task_description.strip():
            raise FrameworkContractError("task.invalid", "delegated task description is empty")
        task_id = create_task_id()
        return {
            "task_description": task_description,
            "skail_task_id": task_id,
            "validation_trace": ("validated",),
            "context_packet": ContextAssembler().assemble(
                task_id=task_id,
                objective=task_description,
                state="validated delegated task",
            ),
        }

    def assign_attempt(state: SpikeTaskState) -> dict[str, Any]:
        if state.get("validation_trace") != ("validated",):
            raise FrameworkContractError(
                "route.assignment_before_validation",
                "task assignment must follow validation",
            )
        return {
            "current_assignment_id": assignment.assignment_id,
            "locked_assignment_id": assignment.assignment_id,
            "assigned_model": assignment.model_id,
            "assigned_provider": assignment.provider,
            "reservation_id": assignment.reservation_id,
            "attempt_id": assignment.attempt_id,
            "validation_trace": ("validated", "assigned"),
        }

    def run_profile_agent(state: SpikeTaskState) -> dict[str, Any]:
        child_input, before = _prepare_child_input(state)
        child_result = child.invoke(child_input)
        return _child_update(child_result, before)

    async def arun_profile_agent(state: SpikeTaskState) -> dict[str, Any]:
        child_input, before = _prepare_child_input(state)

        async def invoke_child() -> Any:
            return await child.ainvoke(child_input)

        task_id = state.get("skail_task_id")
        if execution_gate is not None and isinstance(task_id, str):
            child_result = await execution_gate.run(task_id, invoke_child)
        else:
            child_result = await invoke_child()
        return _child_update(child_result, before)

    def _prepare_child_input(state: SpikeTaskState) -> tuple[Any, int]:
        if state.get("validation_trace") != ("validated", "assigned"):
            raise FrameworkContractError(
                "route.assignment_missing",
                "task execution cannot start before assignment",
            )
        before = len(state.get("messages", []))
        child_input: Any = dict(state)
        return child_input, before

    def _child_update(child_result: Mapping[str, Any], before: int) -> dict[str, Any]:
        child_messages = list(child_result.get("messages", []))
        new_messages = child_messages[before:]
        return {
            "messages": new_messages,
            "child_output": _last_ai_text(child_messages),
            "validation_trace": ("validated", "assigned", "executed"),
        }

    def return_result(state: SpikeTaskState) -> dict[str, Any]:
        if state.get("validation_trace") != ("validated", "assigned", "executed"):
            raise FrameworkContractError(
                "task.result_before_execution",
                "task result cannot be returned before execution",
            )
        return {
            "structured_response": {
                "schema_version": 1,
                "status": "succeeded",
                "assignment_id": assignment.assignment_id,
                "attempt_id": assignment.attempt_id,
                "model": assignment.model_id,
                "output": state.get("child_output", ""),
            }
        }

    graph = StateGraph(SpikeTaskState)
    graph.add_node("validate_task", validate_task)
    graph.add_node("assign_attempt", assign_attempt)
    graph.add_node("run_profile_agent", RunnableLambda(run_profile_agent, arun_profile_agent))
    graph.add_node("return_result", return_result)
    graph.add_edge(START, "validate_task")
    graph.add_edge("validate_task", "assign_attempt")
    graph.add_edge("assign_attempt", "run_profile_agent")
    graph.add_edge("run_profile_agent", "return_result")
    graph.add_edge("return_result", END)
    return CompiledSubAgent(name=name, description=description, runnable=graph.compile())


def _last_message_text(messages: Sequence[BaseMessage]) -> str:
    if not messages:
        return ""
    content = messages[-1].content
    return content if isinstance(content, str) else str(content)


def _last_ai_text(messages: Sequence[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and message.content:
            return message.content if isinstance(message.content, str) else str(message.content)
    return ""
