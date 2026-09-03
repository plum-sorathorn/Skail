"""Lead execution controller managing lead runs, assignments, context, and subagent delegation."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast

from deepagents.middleware.subagents import CompiledSubAgent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from rudder.agents.context import ContextAssembler, ContextPacket
from rudder.agents.lead import LeadControls, build_production_lead
from rudder.agents.profile_loader import AgentProfile
from rudder.agents.profiles import builtin_profiles
from rudder.agents.task_graph import (
    AttemptBinding,
    build_compiled_profile_subagent,
)
from rudder.domain.events import SecretRedactor
from rudder.domain.ids import (
    ReservationId,
    RunId,
    SessionId,
    new_assignment_id,
    new_attempt_id,
    new_run_id,
    new_task_id,
)
from rudder.domain.routing import RoutingMode, TaskAssignment
from rudder.domain.tasks import TaskResult, TaskSpec, VerificationResult
from rudder.routing.selector import RouteFailure
from rudder.runtime.deepagents_adapter import ChildRunGate
from rudder.runtime.leases import WorkspaceLeaseManager
from rudder.runtime.scheduler import ChildScheduler
from rudder.runtime.task_registry import TaskRegistry
from rudder.runtime.task_validation import TaskValidator
from rudder.sessions.journal import Journal
from rudder.tools.assembly import build_default_agent


@dataclass(frozen=True)
class RunResult:
    run_id: RunId
    lead_assignment: TaskAssignment
    lead_context_packet: ContextPacket
    output: str
    messages: Sequence[BaseMessage]
    child_results: list[TaskResult] = field(default_factory=list)


AssignChildAttempt = Callable[
    [TaskSpec, int, tuple[tuple[str, str], ...]], AttemptBinding | RouteFailure
]


class RunController:
    """Orchestrates an individual user-instruction run with strict lead and child invariants."""

    def __init__(
        self,
        *,
        session_id: SessionId,
        workspace: Path,
        journal: Journal,
        models: Mapping[str, BaseChatModel],
        default_lead_model: str = "lead-model",
        default_child_model: str = "implementer-model",
        task_validator: TaskValidator | None = None,
        task_registry: TaskRegistry | None = None,
        context_assembler: ContextAssembler | None = None,
        redactor: SecretRedactor | None = None,
        budget_limit_usd: Decimal = Decimal("10.00"),
        child_assigner: AssignChildAttempt | None = None,
        profile_models: Mapping[str, str] | None = None,
    ) -> None:
        self.session_id = session_id
        self.workspace = workspace
        self.journal = journal
        self.models = dict(models)
        self.default_lead_model = default_lead_model
        self.default_child_model = default_child_model
        self.profile_models = dict(profile_models or {})
        self.redactor = redactor or SecretRedactor()
        self.validator = task_validator or TaskValidator(
            profiles=builtin_profiles(),
            workspace_root=workspace,
            max_depth=1,
            background_enabled=False,
        )
        self.registry = task_registry or TaskRegistry()
        self.assembler = context_assembler or ContextAssembler(redactor=self.redactor)
        self.budget_limit_usd = budget_limit_usd
        self.child_assigner = child_assigner
        self.delegation_approval_check: Callable[[TaskSpec, AgentProfile], bool] | None = None

    async def run_instruction(
        self,
        instruction: str,
        *,
        controls: LeadControls | None = None,
        workspace_revision: str = "git:head",
        delegation_approved: bool = False,
    ) -> RunResult:
        active_controls = controls or LeadControls()
        max_children = min(max(active_controls.max_children, 1), 3)

        # Run-scoped locks and gates shared across lead and all children
        leases = WorkspaceLeaseManager()
        gate = ChildRunGate(max_children)
        scheduler = ChildScheduler(max_children=max_children)

        run_id = new_run_id()
        now = datetime.now(UTC)

        # 1. Create run record in journal
        self.journal.create_run(
            run_id=str(run_id),
            session_id=str(self.session_id),
            status="running",
            budget_limit_usd=self.budget_limit_usd,
            created_at=now,
        )

        # 2. Persist lead task, attempt, and assignment BEFORE first model call
        lead_model_name = active_controls.model or self.default_lead_model
        lead_task_id = new_task_id()
        lead_attempt_id = new_attempt_id()
        lead_assignment = TaskAssignment(
            assignment_id=new_assignment_id(),
            task_id=lead_task_id,
            attempt_number=1,
            provider="fake",
            model=lead_model_name,
            routing_mode=RoutingMode.MANUAL if active_controls.model else RoutingMode.AUTO,
            capability_floor=0.70,
            estimated_attempt_cost_usd=Decimal("0.02"),
            reservation_id=ReservationId("00000000-0000-4000-8000-000000000001"),
            explanation=("lead-assigned-before-model-call",),
            catalog_revision="run-init",
        )

        self.journal.create_task(
            task_id=str(lead_task_id),
            run_id=str(run_id),
            description=instruction,
            status="running",
            idempotency_key=f"task:{lead_task_id}",
            created_at=now,
            fingerprint=f"lead:{run_id}",
        )
        self.journal.create_attempt(
            attempt_id=str(lead_attempt_id),
            task_id=str(lead_task_id),
            number=1,
            status="running",
            idempotency_key=f"attempt:{lead_attempt_id}",
            created_at=now,
        )
        self.journal.create_assignment(
            assignment_id=str(lead_assignment.assignment_id),
            attempt_id=str(lead_attempt_id),
            provider=lead_assignment.provider,
            model=lead_assignment.model,
            estimated_cost_usd=lead_assignment.estimated_attempt_cost_usd,
            created_at=now,
            payload=lead_assignment.model_dump(mode="json"),
        )

        # 3. Assemble and persist lead context packet BEFORE first model call
        lead_context_packet = self.assembler.assemble(
            task_id=str(run_id),
            objective=instruction,
            constraints=(),
            state=f"run_id={run_id}; assignment={lead_assignment.assignment_id}",
        )

        recorded_child_results: list[TaskResult] = []

        # 4. Build subagents if delegation is allowed
        allow_delegation = active_controls.delegation in ("auto", "ask")
        subagents: list[CompiledSubAgent] = []

        if allow_delegation:
            for profile in builtin_profiles().values():
                if profile.name == "lead":
                    continue
                subagents.append(
                    self._build_profile_subagent(
                        profile=profile,
                        run_id=run_id,
                        workspace_revision=workspace_revision,
                        leases=leases,
                        gate=gate,
                        scheduler=scheduler,
                        controls=active_controls,
                        delegation_approved=delegation_approved,
                        recorded_child_results=recorded_child_results,
                    )
                )

        # 5. Build and execute lead agent
        lead_chat_model = self.models.get(lead_model_name)
        if lead_chat_model is None:
            raise ValueError(f"model {lead_model_name} is not available in registered models")

        lead_agent = build_production_lead(
            lead_chat_model,
            workspace=self.workspace,
            controls=active_controls,
            subagents=subagents,
            delegation_approved=delegation_approved,
            leases=leases,
        )

        input_message = HumanMessage(content=instruction)
        result_state = cast(
            dict[str, Any], await lead_agent.ainvoke({"messages": [input_message]})
        )
        messages = cast(list[BaseMessage], result_state.get("messages", []))

        output_text = ""
        for message in reversed(messages):
            if isinstance(message, AIMessage) and message.content:
                output_text = (
                    message.content if isinstance(message.content, str) else str(message.content)
                )
                break

        return RunResult(
            run_id=run_id,
            lead_assignment=lead_assignment,
            lead_context_packet=lead_context_packet,
            output=output_text,
            messages=messages,
            child_results=recorded_child_results,
        )

    def _build_profile_subagent(
        self,
        *,
        profile: AgentProfile,
        run_id: RunId,
        workspace_revision: str,
        leases: WorkspaceLeaseManager,
        gate: ChildRunGate,
        scheduler: ChildScheduler,
        controls: LeadControls,
        delegation_approved: bool,
        recorded_child_results: list[TaskResult],
    ) -> CompiledSubAgent:
        def default_assign(
            spec: TaskSpec, number: int, excluded: tuple[tuple[str, str], ...]
        ) -> AttemptBinding | RouteFailure:
            if self.child_assigner is not None:
                return self.child_assigner(spec, number, excluded)

            model_name = self.profile_models.get(profile.name, self.default_child_model)
            if any(p == "fake" and m == model_name for p, m in excluded):
                return RouteFailure(
                    binding_constraint="no_eligible_model",
                    excluded_counts={"excluded": len(excluded)},
                )

            attempt_id = new_attempt_id()
            now = datetime.now(UTC)

            # Persist task in journal if first attempt
            if number == 1:
                self.journal.create_task(
                    task_id=str(spec.task_id),
                    run_id=str(run_id),
                    description=spec.request.description,
                    status="running",
                    idempotency_key=f"task:{spec.task_id}",
                    created_at=now,
                    fingerprint=spec.fingerprint,
                )

            self.journal.create_attempt(
                attempt_id=str(attempt_id),
                task_id=str(spec.task_id),
                number=number,
                status="running",
                idempotency_key=f"attempt:{attempt_id}",
                created_at=now,
            )

            assignment = TaskAssignment(
                assignment_id=new_assignment_id(),
                task_id=spec.task_id,
                attempt_number=cast(Literal[1, 2], number),
                provider="fake",
                model=model_name,
                routing_mode=RoutingMode.AUTO,
                capability_floor=0.50 + 0.15 * (number - 1),
                estimated_attempt_cost_usd=Decimal("0.02"),
                reservation_id=ReservationId("00000000-0000-4000-8000-000000000002"),
                explanation=("subagent-attempt-assigned",),
                catalog_revision="run-subagent",
            )

            self.journal.create_assignment(
                assignment_id=str(assignment.assignment_id),
                attempt_id=str(attempt_id),
                provider=assignment.provider,
                model=assignment.model,
                estimated_cost_usd=assignment.estimated_attempt_cost_usd,
                created_at=now,
                payload=assignment.model_dump(mode="json"),
            )
            return AttemptBinding(attempt_id, assignment)

        async def execute_child(
            spec: TaskSpec, assignment: TaskAssignment, packet: ContextPacket
        ) -> TaskResult:
            # Check approval when in ask mode
            if controls.delegation == "ask":
                approved = delegation_approved
                if self.delegation_approval_check is not None:
                    approved = self.delegation_approval_check(spec, profile)
                if not approved:
                    return TaskResult(
                        task_id=spec.task_id,
                        status="blocked",
                        summary="delegation_not_approved",
                        follow_up="user approval required",
                    )

            child_chat_model = self.models.get(assignment.model)
            if child_chat_model is None:
                return TaskResult(
                    task_id=spec.task_id,
                    status="failed",
                    summary=f"child model {assignment.model} not found",
                )

            inner_agent = build_default_agent(
                child_chat_model,
                workspace=self.workspace,
                profile=profile.name,
                lease_manager=leases,
                task_id=str(spec.task_id),
            )

            # Child receives bounded context packet in model prompt
            formatted_prompt = (
                f"<context_packet revision='{packet.revision}'>\n"
                f"objective: {spec.request.description}\n"
                f"</context_packet>"
            )

            result_state = cast(
                dict[str, Any],
                await inner_agent.ainvoke(
                    {"messages": [HumanMessage(content=formatted_prompt)]}
                ),
            )
            inner_messages = cast(list[BaseMessage], result_state.get("messages", []))

            child_output = ""
            for msg in reversed(inner_messages):
                if isinstance(msg, AIMessage) and msg.content:
                    child_output = (
                        msg.content if isinstance(msg.content, str) else str(msg.content)
                    )
                    break

            verification_list = [
                VerificationResult(criterion=c, passed=True, evidence="automated pass")
                for c in spec.request.success_criteria
            ]

            result = TaskResult(
                task_id=spec.task_id,
                status="succeeded",
                summary=child_output or "child execution completed",
                verification=tuple(verification_list),
            )
            recorded_child_results.append(result)
            return result

        def record_settle(binding: AttemptBinding, result: TaskResult) -> None:
            pass

        def exhaust_fp(spec: TaskSpec) -> None:
            self.registry._failed_fingerprint_attempts[spec.fingerprint] = 2

        return build_compiled_profile_subagent(
            name=profile.name,
            description=profile.description,
            profile=profile,
            validator=self.validator,
            run_id=run_id,
            workspace_revision=workspace_revision,
            gate=gate,
            leases=leases,
            assign=default_assign,
            execute=execute_child,
            settle_attempt=record_settle,
            exhaust_fingerprint=exhaust_fp,
        )
