from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypedDict, cast

from deepagents.graph import DeepAgentState
from deepagents.middleware.subagents import CompiledSubAgent
from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import END, START, StateGraph

from rudder.agents.context import ContextAssembler, ContextComponent, ContextPacket
from rudder.agents.profile_loader import AgentProfile
from rudder.agents.result_evaluator import evaluate_result
from rudder.domain.ids import AttemptId, RunId
from rudder.domain.routing import TaskAssignment
from rudder.domain.tasks import (
    AttemptStatus,
    AttemptSummary,
    TaskRequest,
    TaskResult,
    TaskSpec,
)
from rudder.routing.selector import RouteFailure
from rudder.runtime.deepagents_adapter import ChildRunGate
from rudder.runtime.escalation import bounded_handoff, escalation_floor
from rudder.runtime.leases import WorkspaceLeaseManager
from rudder.runtime.task_validation import TaskValidator


@dataclass(frozen=True)
class AttemptBinding:
    attempt_id: str
    assignment: TaskAssignment


AssignAttempt = Callable[
    [TaskSpec, int, tuple[tuple[str, str], ...]], AttemptBinding | RouteFailure
]
ExecuteAttempt = Callable[
    [TaskSpec, TaskAssignment, ContextPacket], Awaitable[TaskResult]
]


class TaskGraphState(TypedDict):
    spec: TaskSpec
    attempt_number: NotRequired[int]
    excluded_models: NotRequired[tuple[tuple[str, str], ...]]
    assignment: NotRequired[TaskAssignment]
    attempt_id: NotRequired[str]
    attempts: NotRequired[tuple[AttemptSummary, ...]]
    context_packet: NotRequired[ContextPacket]
    previous_result: NotRequired[TaskResult | None]
    result: NotRequired[TaskResult | None]


class ProfileTaskState(DeepAgentState):
    spec: NotRequired[TaskSpec]
    result: NotRequired[TaskResult]


def build_task_graph(
    *,
    profile: AgentProfile,
    assign: AssignAttempt,
    execute: ExecuteAttempt,
    context_assembler: ContextAssembler | None = None,
    persist_context: Callable[[ContextPacket], None] | None = None,
    settle_attempt: Callable[[AttemptBinding, TaskResult], None] | None = None,
    exhaust_fingerprint: Callable[[TaskSpec], None] | None = None,
    gate: ChildRunGate,
    leases: WorkspaceLeaseManager,
) -> Any:
    assembler = context_assembler or ContextAssembler()

    def validate(state: TaskGraphState) -> dict[str, Any]:
        if "spec" not in state:
            raise ValueError("task graph requires a validated task spec")
        return {
            "attempt_number": 1, "excluded_models": (), "attempts": (), "result": None
        }

    def assign_attempt(state: TaskGraphState) -> dict[str, Any]:
        spec = state["spec"]
        number = state["attempt_number"]
        excluded = state.get("excluded_models", ())
        binding = assign(spec, number, excluded)
        if isinstance(binding, RouteFailure):
            if binding.binding_constraint == "budget_unaffordable":
                result = TaskResult(
                    task_id=spec.task_id,
                    status="budget_blocked",
                    summary=binding.binding_constraint,
                )
            else:
                result = TaskResult(
                    task_id=spec.task_id,
                    status="blocked",
                    summary=binding.binding_constraint or "no eligible route",
                )
            return {
                "result": result
            }
        assignment = binding.assignment
        if assignment.task_id != spec.task_id or assignment.attempt_number != number:
            raise ValueError("assignment does not match task attempt")
        if number == 2 and "assignment" in state:
            required_floor = escalation_floor(state["assignment"].capability_floor)
            if (
                required_floor is not None
                and assignment.capability_floor is not None
                and assignment.capability_floor < required_floor
            ):
                raise ValueError("escalated assignment did not raise the capability floor")
        references: tuple[ContextComponent, ...] = ()
        previous = state.get("previous_result") or state.get("result")
        if previous is not None:
            handoff = bounded_handoff(
                summary=previous.summary,
                evidence=tuple(
                    item.evidence or item.criterion for item in previous.verification
                ),
                changed_paths=previous.changed_paths,
                verification=tuple(
                    f"{item.criterion}={item.passed}" for item in previous.verification
                ),
            )
            references = (
                ContextComponent(
                    "failure-handoff",
                    f"attempt-{number - 1}",
                    repr(handoff),
                    "evidence from the failed prior attempt",
                    max(1, len(repr(handoff)) // 4),
                ),
            )
        packet = assembler.assemble(
            task_id=str(spec.task_id),
            objective=spec.request.description,
            constraints=spec.request.success_criteria,
            state=f"attempt={number}; assignment={assignment.assignment_id}",
            references=references,
        )
        if persist_context is not None:
            persist_context(packet)
        return {
            "assignment": assignment,
            "attempt_id": binding.attempt_id,
            "context_packet": packet,
            "result": None,
        }

    async def run_attempt(state: TaskGraphState) -> dict[str, Any]:
        spec = state["spec"]
        assignment = state["assignment"]
        packet = state["context_packet"]

        async def invoke() -> TaskResult:
            if profile.write_capable:
                async with leases.acquire(str(spec.task_id)):
                    return await execute(spec, assignment, packet)
            return await execute(spec, assignment, packet)

        try:
            result = await gate.run(str(spec.task_id), invoke)
        except Exception as exc:
            result = TaskResult(
                task_id=spec.task_id,
                status="failed",
                summary=f"attempt execution failed: {exc}",
            )
        if result.task_id != spec.task_id:
            raise ValueError("task result identity mismatch")
        return {"result": evaluate_result(result, required_criteria=spec.request.success_criteria)}

    def evaluate(state: TaskGraphState) -> dict[str, Any]:
        result = state["result"]
        assert result is not None
        number = state["attempt_number"]
        status = {
            "succeeded": AttemptStatus.SUCCEEDED,
            "failed": AttemptStatus.FAILED,
            "cancelled": AttemptStatus.CANCELLED,
            "blocked": AttemptStatus.BLOCKED,
            "budget_blocked": AttemptStatus.BLOCKED,
            "returned_to_lead": AttemptStatus.FAILED,
        }[result.status]
        summary = AttemptSummary(
            attempt_id=AttemptId(state["attempt_id"]),
            number=cast(Literal[1, 2], number),
            status=status,
            model=state["assignment"].model,
        )
        attempts = (*state.get("attempts", ()), summary)
        binding = AttemptBinding(state["attempt_id"], state["assignment"])
        if settle_attempt is not None:
            settle_attempt(binding, result)
        if result.status != "failed" or number == 2:
            if result.status == "failed":
                result = result.model_copy(
                    update={"status": "returned_to_lead", "attempts": attempts}
                )
                if exhaust_fingerprint is not None:
                    exhaust_fingerprint(state["spec"])
            elif not result.attempts:
                result = result.model_copy(update={"attempts": attempts})
            return {"result": result, "attempts": attempts}
        assignment = state["assignment"]
        return {
            "attempt_number": 2,
            "excluded_models": ((assignment.provider, assignment.model),),
            "attempts": attempts,
            "previous_result": result,
            "result": None,
        }

    def after_assign(state: TaskGraphState) -> str:
        return "return_result" if state.get("result") is not None else "run_attempt"

    def after_evaluate(state: TaskGraphState) -> str:
        return "assign_attempt" if state.get("result") is None else "return_result"

    graph = StateGraph(TaskGraphState)
    graph.add_node("validate_task", validate)
    graph.add_node("assign_attempt", assign_attempt)
    graph.add_node("run_attempt", run_attempt)
    graph.add_node("evaluate_attempt", evaluate)
    graph.add_node("return_result", lambda state: {})
    graph.add_edge(START, "validate_task")
    graph.add_edge("validate_task", "assign_attempt")
    graph.add_conditional_edges("assign_attempt", after_assign)
    graph.add_edge("run_attempt", "evaluate_attempt")
    graph.add_conditional_edges("evaluate_attempt", after_evaluate)
    graph.add_edge("return_result", END)
    return graph.compile()


def build_compiled_profile_subagent(
    *,
    name: str,
    description: str,
    profile: AgentProfile,
    validator: TaskValidator,
    run_id: RunId,
    workspace_revision: str,
    assign: AssignAttempt,
    execute: ExecuteAttempt,
    gate: ChildRunGate,
    leases: WorkspaceLeaseManager,
    persist_context: Callable[[ContextPacket], None] | None = None,
    settle_attempt: Callable[[AttemptBinding, TaskResult], None] | None = None,
    exhaust_fingerprint: Callable[[TaskSpec], None] | None = None,
) -> CompiledSubAgent:
    lifecycle = build_task_graph(
        profile=profile,
        assign=assign,
        execute=execute,
        persist_context=persist_context,
        settle_attempt=settle_attempt,
        exhaust_fingerprint=exhaust_fingerprint,
        gate=gate,
        leases=leases,
    )

    def validate(state: ProfileTaskState) -> dict[str, Any]:
        request = TaskRequest(
            description=_last_message_text(state.get("messages", [])),
            profile=profile.name,
        )
        spec = validator.create_spec(
            request,
            run_id=run_id,
            parent_task_id=None,
            parent_depth=0,
            workspace_revision=workspace_revision,
        )
        return {"spec": spec}

    async def execute_lifecycle(state: ProfileTaskState) -> dict[str, Any]:
        output = await lifecycle.ainvoke({"spec": state["spec"]})
        result = output["result"]
        assert isinstance(result, TaskResult)
        return {"result": result, "messages": [AIMessage(content=result.model_dump_json())]}

    outer = StateGraph(ProfileTaskState)
    outer.add_node("validate_task", validate)
    outer.add_node("execute_lifecycle", execute_lifecycle)
    outer.add_edge(START, "validate_task")
    outer.add_edge("validate_task", "execute_lifecycle")
    outer.add_edge("execute_lifecycle", END)
    return CompiledSubAgent(name=name, description=description, runnable=outer.compile())


def _last_message_text(messages: Sequence[BaseMessage]) -> str:
    if not messages:
        return ""
    content = messages[-1].content
    return content if isinstance(content, str) else str(content)
