from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypedDict, cast

from deepagents.graph import DeepAgentState
from deepagents.middleware.subagents import CompiledSubAgent
from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from skail.agents.context import ContextAssembler, ContextComponent, ContextPacket
from skail.agents.profile_loader import AgentProfile
from skail.agents.result_evaluator import evaluate_result
from skail.domain.ids import AttemptId, RunId, new_task_id
from skail.domain.routing import TaskAssignment
from skail.domain.tasks import (
    AttemptStatus,
    AttemptSummary,
    TaskRequest,
    TaskResult,
    TaskSpec,
    TaskStatus,
)
from skail.routing.selector import RouteFailure
from skail.runtime.deepagents_adapter import ChildRunGate
from skail.runtime.escalation import bounded_handoff, escalation_floor
from skail.runtime.leases import WorkspaceLeaseManager
from skail.runtime.scheduler import ChildScheduler
from skail.runtime.task_registry import TaskRegistry
from skail.runtime.task_validation import TaskValidationError, TaskValidator


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
    validation_error: NotRequired[str]


def decode_task_request(description: str, *, profile: str) -> TaskRequest:
    """Decode Skail's optional structured packet carried by the standard task description."""
    stripped = description.strip()
    if stripped.startswith('"'):
        try:
            unwrapped = json.loads(stripped)
        except json.JSONDecodeError:
            unwrapped = None
        if isinstance(unwrapped, str):
            stripped = unwrapped.strip()
        elif isinstance(unwrapped, dict):
            stripped = json.dumps(unwrapped)
    if not stripped.startswith("{"):
        return TaskRequest(
            description=description,
            profile=profile,
            success_criteria=("Provide evidence for the completed task",),
        )
    try:
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            raise ValueError("task packet must be an object")
        alias = payload.pop("subagent_type", None)
        if "profile" in payload and alias is not None and payload["profile"] != alias:
            raise ValueError("task packet profile does not match subagent_type")
        if "profile" not in payload and alias is not None:
            payload["profile"] = alias
        if "profile" in payload and payload["profile"] != profile:
            raise ValueError("task packet profile does not match subagent_type")
        payload["profile"] = profile
        inner = payload.get("description")
        if isinstance(inner, str):
            inner_stripped = inner.strip()
            if inner_stripped.startswith("{"):
                try:
                    inner_payload = json.loads(inner_stripped)
                except json.JSONDecodeError:
                    inner_payload = None
                if isinstance(inner_payload, dict):
                    inner_payload.pop("subagent_type", None)
                    inner_payload.pop("profile", None)
                    payload = {**inner_payload, "profile": profile}
        return TaskRequest.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise TaskValidationError("task.description_packet_invalid") from exc


def build_task_graph(
    *,
    profile: AgentProfile,
    assign: AssignAttempt,
    execute: ExecuteAttempt,
    context_assembler: ContextAssembler | None = None,
    persist_context: Callable[[ContextPacket], None] | None = None,
    settle_attempt: Callable[[AttemptBinding, TaskResult], None] | None = None,
    persist_result: Callable[[TaskResult], None] | None = None,
    exhaust_fingerprint: Callable[[TaskSpec], None] | None = None,
    gate: ChildRunGate,
    leases: WorkspaceLeaseManager,
    scheduler: ChildScheduler | None = None,
    task_registry: TaskRegistry | None = None,
    task_event: Callable[[TaskSpec, str, str | None, str | None], None] | None = None,
    resolve_spec: Callable[[str, str], TaskSpec | None] | None = None,
    require_preplanned: bool = False,
    serialize_writers: bool = True,
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
            if task_registry is not None:
                task_registry.transition(
                    spec.task_id,
                    expected=TaskStatus.QUEUED,
                    target=TaskStatus.BLOCKED,
                    attempt_number=number,
                )
            if task_event is not None:
                task_event(spec, result.status, None, result.summary)
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
        if spec.request.prerequisite_artifacts:
            artifact_references = "\n".join(spec.request.prerequisite_artifacts)
            references += (
                ContextComponent(
                    "prerequisite-artifacts",
                    "declared",
                    artifact_references,
                    "bounded prerequisite artifact references",
                    max(1, len(artifact_references) // 4),
                    "reference",
                ),
                ContextComponent(
                    "authorized-retrieval",
                    "runtime-policy",
                    "Retrieve listed references only through enabled Skail tools; "
                    "runtime policy rechecks access.",
                    "progressive retrieval boundary",
                    24,
                    "reference",
                ),
            )
        if spec.request.source_revisions:
            source_revisions = "\n".join(spec.request.source_revisions)
            references += (
                ContextComponent(
                    "source-revisions",
                    "declared",
                    source_revisions,
                    "source revisions for this task packet",
                    max(1, len(source_revisions) // 4),
                    "reference",
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
        number = state.get("attempt_number", 1)
        if task_registry is not None:
            task_registry.transition(
                spec.task_id,
                expected=TaskStatus.QUEUED,
                target=TaskStatus.RUNNING,
                attempt_number=number,
            )
        if task_event is not None:
            task_event(spec, "started", state.get("attempt_id"), None)

        async def invoke() -> TaskResult:
            raw = await execute(spec, assignment, packet)
            return evaluate_result(raw, required_criteria=spec.request.success_criteria)

        async def run_with_gate() -> TaskResult:
            if scheduler is not None:
                task_id_str = str(spec.task_id)
                if task_id_str not in scheduler._children:
                    scheduler.submit(
                        task_id_str,
                        priority=spec.request.priority,
                        depends_on=tuple(str(d) for d in spec.request.depends_on),
                    )
                if number == 2:
                    scheduler.retry(task_id_str)
                result = await scheduler.execute(
                    task_id_str, invoke, final_failure=(number == 2)
                )
            else:
                result = await gate.run(str(spec.task_id), invoke)
            return cast(TaskResult, result)

        try:
            if profile.write_capable and serialize_writers:
                async with leases.acquire(str(spec.task_id)):
                    operation: asyncio.Future[TaskResult] = asyncio.ensure_future(run_with_gate())
                    try:
                        result = await asyncio.shield(operation)
                    except asyncio.CancelledError:
                        await operation
                        raise
            else:
                result = await run_with_gate()
        except Exception as exc:
            result = TaskResult(
                task_id=spec.task_id,
                status="failed",
                summary=f"attempt execution failed: {exc}",
            )
            if scheduler is not None and str(spec.task_id) in scheduler._children and number == 2:
                try:
                    scheduler.finish(str(spec.task_id), succeeded=False)
                except Exception:
                    pass
        if result.task_id != spec.task_id:
            raise ValueError("task result identity mismatch")
        return {"result": result}

    def evaluate(state: TaskGraphState) -> dict[str, Any]:
        spec = state["spec"]
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
        if not result.attempts:
            result = result.model_copy(update={"attempts": attempts})
        terminal = result.status != "failed" or number == 2
        if terminal and persist_result is not None:
            persist_result(result)
        binding = AttemptBinding(state["attempt_id"], state["assignment"])
        if settle_attempt is not None:
            settle_attempt(binding, result)
        if task_registry is not None:
            target_task_status = {
                "succeeded": TaskStatus.SUCCEEDED,
                "failed": TaskStatus.RETURNED_TO_LEAD if number == 2 else TaskStatus.FAILED,
                "cancelled": TaskStatus.CANCELLED,
                "blocked": TaskStatus.BLOCKED,
                "budget_blocked": TaskStatus.BUDGET_BLOCKED,
                "returned_to_lead": TaskStatus.RETURNED_TO_LEAD,
            }.get(result.status, TaskStatus.FAILED)
            task_registry.transition(
                spec.task_id,
                expected=TaskStatus.RUNNING,
                target=target_task_status,
                attempt_number=number,
            )
        if task_event is not None:
            task_event(
                spec,
                "returned_to_lead" if result.status == "failed" and number == 2 else result.status,
                state.get("attempt_id"),
                result.summary,
            )
        if terminal:
            if result.status == "failed":
                result = result.model_copy(
                    update={"status": "returned_to_lead", "attempts": attempts}
                )
                if exhaust_fingerprint is not None:
                    exhaust_fingerprint(state["spec"])
            return {"result": result, "attempts": attempts}
        assignment = state["assignment"]
        if task_registry is not None:
            task_registry.transition(
                spec.task_id,
                expected=TaskStatus.FAILED,
                target=TaskStatus.QUEUED,
                attempt_number=1,
            )
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
    scheduler: ChildScheduler | None = None,
    task_registry: TaskRegistry | None = None,
    task_event: Callable[[TaskSpec, str, str | None, str | None], None] | None = None,
    resolve_spec: Callable[[str, str], TaskSpec | None] | None = None,
    persist_context: Callable[[ContextPacket], None] | None = None,
    settle_attempt: Callable[[AttemptBinding, TaskResult], None] | None = None,
    persist_result: Callable[[TaskResult], None] | None = None,
    exhaust_fingerprint: Callable[[TaskSpec], None] | None = None,
    require_preplanned: bool = False,
    serialize_writers: bool = True,
) -> CompiledSubAgent:
    lifecycle = build_task_graph(
        profile=profile,
        assign=assign,
        execute=execute,
        persist_context=persist_context,
        settle_attempt=settle_attempt,
        persist_result=persist_result,
        exhaust_fingerprint=exhaust_fingerprint,
        gate=gate,
        leases=leases,
        scheduler=scheduler,
        task_registry=task_registry,
        task_event=task_event,
        resolve_spec=resolve_spec,
        require_preplanned=require_preplanned,
        serialize_writers=serialize_writers,
    )

    def validate(state: ProfileTaskState) -> dict[str, Any]:
        description = _last_message_text(state.get("messages", []))
        spec = resolve_spec(description, profile.name) if resolve_spec is not None else None
        preplanned = spec is not None
        if spec is None:
            if require_preplanned:
                return {
                    "result": TaskResult(
                        task_id=new_task_id(),
                        status="blocked",
                        summary="Task validation rejected: task.admission_required",
                    ),
                    "validation_error": "task.admission_required",
                }
            try:
                request = decode_task_request(description, profile=profile.name)
                spec = validator.create_spec(
                    request,
                    run_id=run_id,
                    parent_task_id=None,
                    parent_depth=0,
                    workspace_revision=workspace_revision,
                )
            except TaskValidationError as exc:
                return {
                    "result": TaskResult(
                        task_id=new_task_id(),
                        status="blocked",
                        summary=f"Task validation rejected: {exc.code}",
                    ),
                    "validation_error": exc.code,
                }
        if task_registry is not None and not preplanned:
            try:
                task_registry.register(spec)
                task_registry.transition(
                    spec.task_id,
                    expected=TaskStatus.PROPOSED,
                    target=TaskStatus.QUEUED,
                    attempt_number=1,
                )
                if task_event is not None:
                    task_event(spec, "proposed", None, None)
                    task_event(spec, "queued", None, None)
            except TaskValidationError as exc:
                return {"spec": spec, "validation_error": exc.code}
        return {"spec": spec}

    async def execute_lifecycle(state: ProfileTaskState) -> dict[str, Any]:
        if "result" in state:
            result = state["result"]
            return {"messages": [AIMessage(content=result.model_dump_json())]}
        if "validation_error" in state:
            result = TaskResult(
                task_id=state["spec"].task_id,
                status="blocked",
                summary=f"Task validation rejected: {state['validation_error']}",
            )
            return {"result": result, "messages": [AIMessage(content=result.model_dump_json())]}
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
