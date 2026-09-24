"""Lead execution controller managing lead runs, assignments, context, and subagent delegation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import traceback
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

from deepagents.middleware.subagents import CompiledSubAgent
from langchain.agents.middleware import ModelResponse
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from skail.agents.context import ContextAssembler, ContextComponent, ContextPacket
from skail.agents.instructions import load_root_instructions
from skail.agents.lead import LeadControls, build_production_lead, resolve_lead_controls
from skail.agents.profile_loader import AgentProfile
from skail.agents.profiles import builtin_profiles
from skail.agents.result_evaluator import parse_child_result
from skail.agents.task_graph import (
    AttemptBinding,
    build_compiled_profile_subagent,
    decode_task_request,
)
from skail.config.paths import workspace_state_dir
from skail.domain.changesets import ChangeSetStatus
from skail.domain.decisions import ExecutionMode
from skail.domain.events import (
    DiagnosticPayload,
    EventEnvelope,
    EventPayload,
    InterruptKind,
    LifecyclePayload,
    ModelPayload,
    SecretRedactor,
    TaskPayload,
    ToolPayload,
    UserPayload,
)
from skail.domain.ids import (
    AttemptId,
    InvocationId,
    RunId,
    SessionId,
    TaskId,
    new_attempt_id,
    new_event_id,
    new_invocation_id,
    new_run_id,
    new_task_id,
)
from skail.domain.plans import (
    EffectScope,
    ExecutionPlan,
    PlanNode,
    PlanNodeKind,
    PlanNodeState,
    PlanRevision,
)
from skail.domain.routing import RoutingMode, TaskAssignment
from skail.domain.security import ProjectTrustLevel, identify_workspace
from skail.domain.tasks import (
    TERMINAL_TASK_STATUSES,
    ArtifactRef,
    AttemptStatus,
    TaskRequest,
    TaskResult,
    TaskSpec,
    TaskStatus,
)
from skail.domain.usage import NormalizedUsage
from skail.providers.base import ProviderAdapter
from skail.providers.fallback import FallbackBinding
from skail.providers.models import CapabilityVector, ModelProfile, ProviderSupportLevel
from skail.routing.assignment import (
    AccountingReconciliationRequired,
    AssignmentRequest,
    AssignmentService,
    AssignmentUsageSettler,
    BatchAssignmentResult,
    PersistedAssignmentRegistry,
    RoutingSnapshot,
    config_revision,
)
from skail.routing.budget import BudgetLedger
from skail.routing.estimates import AttemptEstimateInput, estimate_attempt_cost
from skail.routing.requirements import RequirementBuilder, TaskRisk
from skail.routing.selector import RouteCandidate, RouteFailure, describe_route_failure
from skail.runtime.changeset_integration import ChangeSetIntegrator
from skail.runtime.decisions import (
    ExecutionDecisionGate,
    ExecutionDecisionMiddleware,
    execution_decision_tool,
)
from skail.runtime.deepagents_adapter import ChildRunGate, resume_agent
from skail.runtime.event_bus import EventBus
from skail.runtime.failure_monitor import RunModelCallBudget
from skail.runtime.interrupts import QuestionStore
from skail.runtime.leases import WorkspaceLeaseManager
from skail.runtime.model_middleware import TaskBoundModelMiddleware
from skail.runtime.presentation import model_content_to_text, structured_output_for_jsonl
from skail.runtime.redaction import RedactionRegistry
from skail.runtime.scheduler import ChildScheduler
from skail.runtime.task_registry import TaskRegistry
from skail.runtime.task_validation import TaskValidationError, TaskValidator
from skail.runtime.workspace_capture import (
    ImmutableArtifactStore,
    StableWorktreeScanner,
    WorkspaceCaptureError,
    capture_managed_changeset,
)
from skail.runtime.workspaces import (
    WorkspaceManager,
    WorkspaceMode,
    WorkspaceSelection,
    WorkspaceSnapshot,
)
from skail.sessions.checkpoints import CheckpointStore
from skail.sessions.journal import Journal, PersistedPlan
from skail.tools.approvals import ApprovalStore
from skail.tools.assembly import build_default_agent
from skail.tools.execution import CommandRequest, ExecutionPolicy, ExecutionSecurityContext

DEFAULT_CONFIG_SNAPSHOT: dict[str, Any] = {"routing": {"mode": "auto"}}
_TOOL_RESULT_ALLOWANCE_TOKENS = 1_024
_DEFAULT_OUTPUT_ALLOWANCE_TOKENS = 2_048
MAX_MODEL_CALLS_PER_RUN = 32


@dataclass(frozen=True)
class RunResult:
    run_id: RunId
    lead_assignment: TaskAssignment | None
    lead_context_packet: ContextPacket
    output: str
    messages: Sequence[BaseMessage]
    child_results: list[TaskResult] = field(default_factory=list)
    status: str = "completed"
    interrupted: bool = False
    child_wall_seconds: float = 0.0
    child_peak_active: int = 0
    child_count: int = 0
    pending_interrupt: dict[str, Any] | None = None


@dataclass(frozen=True)
class _PendingRun:
    run_id: RunId
    instruction: str
    controls: LeadControls
    workspace_revision: str
    delegation_approved: bool
    lead_task_id: TaskId
    lead_attempt_id: AttemptId
    lead_assignment: TaskAssignment
    lead_context_packet: ContextPacket
    checkpoint_thread_id: str | None = None


@dataclass(frozen=True)
class _PlannedNodeDispatch:
    plan_id: str
    node_id: str
    profile: AgentProfile
    spec: TaskSpec


AssignChildAttempt = Callable[
    [TaskSpec, int, tuple[tuple[str, str], ...]], AttemptBinding | RouteFailure
]

_LOGGER = logging.getLogger(__name__)
_MESSAGE_SEQUENCE_ERROR = "Message as a sequence"


def _exception_chain(exc: BaseException) -> list[BaseException]:
    """Return exc followed by its __cause__/__context__ ancestors, cycle-safe."""
    chain: list[BaseException] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _is_message_sequence_error(exc: BaseException) -> bool:
    """Whether exc or its cause/context chain is the known message-conversion error."""
    return any(_MESSAGE_SEQUENCE_ERROR in str(item) for item in _exception_chain(exc))


def _describe_message_shapes(messages: object) -> str:
    """Summarize lead-state message shapes to localize message conversion failures."""
    if not isinstance(messages, (list, tuple)):
        return f"messages={type(messages).__name__}"
    if not messages:
        return "messages=<empty>"
    parts: list[str] = []
    for index, element in enumerate(messages):
        if isinstance(element, (list, tuple)):
            first = type(element[0]).__name__ if element else "<empty>"
            parts.append(f"{index}:{type(element).__name__}(len={len(element)},first={first})")
        else:
            parts.append(f"{index}:{type(element).__name__}")
    return f"messages[{len(messages)}]=[{'; '.join(parts)}]"


async def _collect_message_sequence_diagnostics(
    lead_agent: Any, invoke_config: RunnableConfig
) -> str:
    """Read-only best-effort lead-state dump; diagnostic failures never propagate."""
    try:
        state = await lead_agent.aget_state(invoke_config)
        values = getattr(state, "values", None)
        messages = values.get("messages") if isinstance(values, dict) else None
        return _describe_message_shapes(messages if messages is not None else [])
    except Exception:
        return "message-shape diagnostics unavailable"


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
        redaction: RedactionRegistry | None = None,
        redactor: SecretRedactor | None = None,
        checkpoints: CheckpointStore | None = None,
        budget_limit_usd: Decimal | None = None,
        budget_warning_percent: int = 80,
        child_assigner: AssignChildAttempt | None = None,
        profile_models: Mapping[str, str] | None = None,
        fixed_profile_models: Mapping[str, str] | None = None,
        ledger: BudgetLedger | None = None,
        assignment_service: AssignmentService | None = None,
        persisted_registry: PersistedAssignmentRegistry | None = None,
        usage_settler: AssignmentUsageSettler | None = None,
        providers: Mapping[str, ProviderAdapter] | None = None,
        candidates_fn: Callable[[], RoutingSnapshot] | None = None,
        catalog_revision: str = "catalog-v1",
        config_snapshot: Mapping[str, Any] | None = None,
        event_observer: Callable[[EventEnvelope], None] | None = None,
        invocation_id: InvocationId | None = None,
        approvals: ApprovalStore | None = None,
        question_store: QuestionStore | None = None,
        project_trusted: bool = False,
        workspace_mode: str = "shared",
        workspace_manager: WorkspaceManager | None = None,
        state_dir: Path | None = None,
    ) -> None:
        self.session_id = session_id
        self.workspace = workspace
        self.state_dir = (
            state_dir.resolve(strict=False)
            if state_dir is not None
            else workspace_state_dir(identify_workspace(workspace))
        )
        self.journal = journal
        self.models = dict(models)
        self.default_lead_model = default_lead_model
        self.default_child_model = default_child_model
        self.profile_models = dict(profile_models or {})
        self.fixed_profile_models = dict(fixed_profile_models or {})
        self.redaction = redaction or RedactionRegistry()
        self.redactor = redactor or self.redaction
        self.checkpoints = checkpoints
        self.invocation_id = invocation_id or new_invocation_id()
        self.events = EventBus(self.journal)
        if event_observer is not None:
            self.events.add_listener(event_observer)
        self.approvals = approvals
        self.question_store = question_store
        self.project_trusted = project_trusted
        self.workspace_mode = workspace_mode
        self.workspace_manager = workspace_manager or WorkspaceManager(
            self.journal.path.parent / "workspaces"
        )
        self.workspace_selection = WorkspaceSelection(
            WorkspaceMode.SHARED, "workspace.shared_requested"
        )
        self._workspace_snapshot: WorkspaceSnapshot | None = None
        self.validator = task_validator or TaskValidator(
            profiles=builtin_profiles(),
            workspace_root=workspace,
            max_depth=1,
            background_enabled=False,
        )
        self._requirements = RequirementBuilder()
        self.registry = task_registry or TaskRegistry()
        root_instructions = load_root_instructions(
            workspace=self.workspace,
            trust=(
                ProjectTrustLevel.TRUSTED
                if project_trusted
                else ProjectTrustLevel.UNTRUSTED
            ),
            redactor=self.redaction,
        )
        self.assembler = context_assembler or ContextAssembler(
            redactor=self.redactor,
            base_references=root_instructions,
        )
        if context_assembler is not None:
            self.assembler.base_references = root_instructions
        self.budget_limit_usd = budget_limit_usd
        self.child_assigner = child_assigner
        self.delegation_approval_check: Callable[[TaskSpec, AgentProfile], bool] | None = None

        self._all_models: dict[str, BaseChatModel] = {}
        for key, chat_model in self.models.items():
            self._all_models[key] = chat_model
            if ":" not in key:
                self._all_models[f"injected:{key}"] = chat_model

        self.providers: dict[str, ProviderAdapter] = dict(providers or {})

        self.ledger = ledger or BudgetLedger(
            self.journal,
            warning_percent=Decimal(budget_warning_percent) / Decimal("100"),
        )
        self.assignment_service = assignment_service or AssignmentService(
            self.journal, self.ledger, invocation_id=self.invocation_id
        )
        self.assignment_service.invocation_id = self.invocation_id
        self.assignment_service.event_observer = self.events.publish_persisted_nowait
        self.persisted_registry = persisted_registry or PersistedAssignmentRegistry(self.journal)
        self.usage_settler = usage_settler or AssignmentUsageSettler(
            self.journal, self.ledger, self.providers
        )
        self.candidates_fn = candidates_fn
        self.catalog_revision = catalog_revision
        self.config_snapshot = dict(config_snapshot or {})
        self._pending_run: _PendingRun | None = None
        self._pending_interrupt_payload: dict[str, Any] | None = None
        self._planned_specs: dict[tuple[str, str], deque[TaskSpec]] = {}
        self._planned_assignments: dict[str, AttemptBinding | RouteFailure] = {}
        self._planned_node_dispatches: list[_PlannedNodeDispatch] = []
        self._plan_nodes_by_task: dict[str, tuple[str, str]] = {}
        self._lead_allowance_ids: list[str] = []
        self._plan_revision_evidence: dict[str, frozenset[str]] = {}
        self._plan_revision_checkpoints: dict[str, str] = {}
        self._restored_decision: Any | None = None
        self._resume_lead_on_recovery = True
        self._run_model_call_budgets: dict[str, RunModelCallBudget] = {}

    @property
    def pending_interrupt(self) -> dict[str, Any] | None:
        return self._pending_interrupt_payload

    @property
    def restored_decision(self) -> Any | None:
        return self._restored_decision

    def _has_pending_question(self) -> bool:
        if self.question_store is None:
            return False
        snapshot = self.journal.get_session_snapshot(str(self.session_id))
        for run in snapshot.runs:
            if run.status != "blocked":
                continue
            graph_ids = [f"{self.session_id}:{run.run_id}:lead"]
            graph_ids.extend(
                f"{self.session_id}:{run.run_id}:{task.task_id}"
                for task in snapshot.tasks
                if task.run_id == run.run_id
            )
            if any(self.question_store.pending(graph_id) for graph_id in graph_ids):
                return True
        return False

    def _record_model_usage(self, assignment_id: str, response: object, call_id: str = "") -> None:
        self.usage_settler.record_call(assignment_id, response, call_id=call_id)

    def _model_call_budget_for_run(self, run_id: RunId) -> RunModelCallBudget:
        key = str(run_id)
        budget = self._run_model_call_budgets.get(key)
        if budget is None:
            snapshot = self.journal.get_session_snapshot(str(self.session_id))
            calls_started = sum(
                event.run_id == key and event.type == "model.started"
                for event in snapshot.events
            )
            budget = RunModelCallBudget(
                max_calls=MAX_MODEL_CALLS_PER_RUN,
                calls_started=calls_started,
            )
            self._run_model_call_budgets[key] = budget
        return budget

    def _checkpoint_thread_id(self, run_id: RunId) -> str:
        return f"{self.session_id}:{run_id}"

    def _finalize_child_budgets(self, run_id: RunId, lead_task_id: TaskId) -> None:
        """Release settled/unstarted child funds while retaining ambiguous calls."""
        snapshot = self.journal.get_session_snapshot(str(self.session_id))
        run_task_ids = {
            task.task_id
            for task in snapshot.tasks
            if task.run_id == str(run_id) and task.task_id != str(lead_task_id)
        }
        attempt_task = {
            attempt.attempt_id: attempt.task_id
            for attempt in snapshot.attempts
            if attempt.task_id in run_task_ids
        }
        for persisted in snapshot.assignments:
            if persisted.attempt_id not in attempt_task:
                continue
            assignment = TaskAssignment.model_validate(persisted.payload)
            try:
                self._finalize_assignment_budget(assignment)
            except AccountingReconciliationRequired:
                continue

    def _validate_evidence_ref(self, reference: ArtifactRef) -> bool:
        return self._validate_evidence_at(reference, self.workspace)

    @staticmethod
    def _validate_evidence_at(reference: ArtifactRef, workspace: Path) -> bool:
        if reference.kind not in {"file", "artifact"} or not reference.digest:
            return False
        candidate = (workspace / reference.path).resolve(strict=False)
        try:
            relative = candidate.relative_to(workspace.resolve())
        except ValueError:
            return False
        if any(part in {".git", ".skail"} or part == ".env" for part in relative.parts):
            return False
        if not candidate.is_file():
            return False
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        return digest == reference.digest

    def _validate_source_ref(self, reference: str) -> bool:
        return self._validate_source_at(reference, self.workspace)

    @staticmethod
    def _validate_source_at(reference: str, workspace: Path) -> bool:
        path_text, separator, line_text = reference.rpartition(":")
        if not separator or not line_text.isdigit():
            return False
        candidate = (workspace / path_text).resolve(strict=False)
        try:
            relative = candidate.relative_to(workspace.resolve())
        except ValueError:
            return False
        if any(part in {".git", ".skail"} or part == ".env" for part in relative.parts):
            return False
        if not candidate.is_file():
            return False
        line_number = int(line_text)
        return 1 <= line_number <= len(candidate.read_text(encoding="utf-8").splitlines())

    def _compaction_references(self) -> tuple[ContextComponent, ...]:
        snapshot = self.journal.get_session_snapshot(str(self.session_id))
        for stored in reversed(snapshot.context_packets):
            payload = stored.payload
            if payload.get("kind") != "compaction":
                continue
            return tuple(
                ContextComponent(**component)
                for component in payload.get("components", ())
                if isinstance(component, Mapping)
            )
        return ()

    def _has_calls(self, assignment_id: str) -> bool:
        with self.journal._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM assignment_call_usage WHERE assignment_id=?",
                (assignment_id,),
            ).fetchone()
            return bool(row and row[0] > 0)

    def _finalize_assignment_budget(self, assignment: TaskAssignment) -> None:
        assignment_id = str(assignment.assignment_id)
        self.usage_settler.complete_unmeasured_calls(assignment_id)
        with self.journal._connect() as connection:
            uncertain = connection.execute(
                "SELECT 1 FROM provider_calls WHERE assignment_id=? "
                "AND status='ambiguous' LIMIT 1",
                (assignment_id,),
            ).fetchone()
        if uncertain is not None:
            error_class = self._ambiguous_error_class(self.journal, assignment_id)
            detail = self._ambiguous_error_detail(self.journal, assignment_id)
            detail_suffix = f": {detail}" if detail is not None else ""
            raise AccountingReconciliationRequired(
                f"provider usage is uncertain ({error_class}); "
                f"reservation remains held{detail_suffix}"
            )
        if self._has_calls(assignment_id):
            self.usage_settler.settle_attempt(assignment_id)
            return
        with self.journal._connect() as connection:
            completed = connection.execute(
                "SELECT 1 FROM provider_calls WHERE assignment_id=? "
                "AND status='completed' LIMIT 1",
                (assignment_id,),
            ).fetchone()
        if completed is not None:
            self.usage_settler.settle_attempt(assignment_id)
        else:
            self.ledger.release(str(assignment.reservation_id))

    @staticmethod
    def _ambiguous_error_class(journal: Any, assignment_id: str) -> str:
        """Return the redacted original exception class for an ambiguous call.

        Reads the `ClassName: detail` prefix written by `mark_ambiguous`. The
        class name is always code-defined, never a secret, so surfacing it is
        safe; raw error text is never included. Falls back to "unknown" when
        the summary is missing or unparseable.
        """
        with journal._connect() as connection:
            row = connection.execute(
                "SELECT error_summary FROM provider_calls WHERE assignment_id=? "
                "AND status='ambiguous' LIMIT 1",
                (assignment_id,),
            ).fetchone()
        if row is None:
            return "unknown"
        summary = row[0] if not isinstance(row, dict) else row.get("error_summary")
        if not isinstance(summary, str) or not summary:
            return "unknown"
        head = summary.split(":", 1)[0].strip()
        if not head.replace("_", "").isalnum() or len(head) > 64:
            return "unknown"
        return head

    @staticmethod
    def _ambiguous_error_detail(journal: Any, assignment_id: str) -> str | None:
        """Return the stored, size-bounded ambiguity detail after the class.

        Reads the `ClassName: detail` summary written by `mark_ambiguous` and
        returns only the detail portion; the class prefix is parsed separately
        by `_ambiguous_error_class`. Returns None when the summary is missing,
        unparseable, or carries no detail.
        """
        with journal._connect() as connection:
            row = connection.execute(
                "SELECT error_summary FROM provider_calls WHERE assignment_id=? "
                "AND status='ambiguous' LIMIT 1",
                (assignment_id,),
            ).fetchone()
        if row is None:
            return None
        summary = row[0] if not isinstance(row, dict) else row.get("error_summary")
        if not isinstance(summary, str) or ":" not in summary:
            return None
        detail = summary.split(":", 1)[1].strip()
        return detail or None

    def _release_lead_allowances(self) -> None:
        for reservation_id in self._lead_allowance_ids:
            self.ledger.release(reservation_id)
        self._lead_allowance_ids.clear()

    def _routing_config_snapshot(self, mode: RoutingMode) -> dict[str, Any]:
        snapshot = deepcopy(self.config_snapshot)
        snapshot.setdefault("routing", {})["mode"] = mode.value
        return snapshot

    def subscribe_events(self, listener: Callable[[EventEnvelope], None]) -> None:
        self.events.add_listener(listener)

    def _estimate_snapshot(
        self,
        snapshot: RoutingSnapshot,
        *,
        packet: ContextPacket,
        profile: AgentProfile,
        minimum_output_tokens: int,
    ) -> RoutingSnapshot:
        """Attach a task-packet estimate to each candidate without assuming cache reuse."""
        candidates: list[RouteCandidate] = []
        for candidate in snapshot.candidates:
            output_allowance = max(
                minimum_output_tokens,
                min(
                    candidate.profile.max_output_tokens or _DEFAULT_OUTPUT_ALLOWANCE_TOKENS,
                    _DEFAULT_OUTPUT_ALLOWANCE_TOKENS,
                ),
            )
            estimate = estimate_attempt_cost(
                AttemptEstimateInput(
                    context_tokens=packet.estimated_tokens,
                    tool_result_tokens=(_TOOL_RESULT_ALLOWANCE_TOKENS if profile.tools else 0),
                    output_tokens=output_allowance,
                    expected_calls=profile.expected_calls,
                    input_usd_per_million=candidate.profile.input_usd_per_million,
                    output_usd_per_million=candidate.profile.output_usd_per_million,
                    cached_input_usd_per_million=candidate.profile.cached_input_usd_per_million,
                )
            )
            candidates.append(
                candidate.model_copy(
                    update={
                        "estimated_cost_usd": estimate.cost_usd,
                        "estimate_assumptions": (
                            *estimate.assumptions,
                            f"expected_calls_prior=profile:{profile.name}",
                            "cache_assumption=no_cache_reuse",
                        ),
                    }
                )
            )
        return snapshot.model_copy(update={"candidates": tuple(candidates)})

    def _get_candidates(
        self,
        *,
        for_lead: bool = False,
        target_lead_model: str | None = None,
        routing_mode: RoutingMode = RoutingMode.AUTO,
    ) -> RoutingSnapshot:
        if self.candidates_fn is not None:
            snapshot = self.candidates_fn()
            if for_lead and target_lead_model and target_lead_model != "auto":
                provider, model = (
                    target_lead_model.split(":", 1)
                    if ":" in target_lead_model
                    else ("injected", target_lead_model)
                )
                matching = tuple(
                    candidate
                    for candidate in snapshot.candidates
                    if candidate.profile.provider == provider
                    and candidate.profile.model == model
                )
                return snapshot.model_copy(update={"candidates": matching})
            return snapshot

        effective_lead_model = target_lead_model or self.default_lead_model
        clean_lead_model = (
            effective_lead_model.split(":", 1)[1]
            if ":" in effective_lead_model
            else effective_lead_model
        )
        clean_child_model = (
            self.default_child_model.split(":", 1)[1]
            if ":" in self.default_child_model
            else self.default_child_model
        )
        candidates: list[RouteCandidate] = []
        for key in self.models:
            provider = "injected"
            model_name = key
            if ":" in key:
                provider, model_name = key.split(":", 1)
            is_lead = model_name == clean_lead_model
            if for_lead and not is_lead and len(self.models) > 1:
                continue
            if (
                not for_lead
                and is_lead
                and (len(self.models) > 1 or clean_child_model != clean_lead_model)
            ):
                continue
            profile = ModelProfile(
                provider=provider,
                model=model_name,
                support_level=ProviderSupportLevel.NATIVE,
                input_usd_per_million=Decimal("1.00"),
                output_usd_per_million=Decimal("2.00"),
                context_tokens=128_000,
                max_output_tokens=8_192,
                supports_tools=True,
                supports_structured_output=True,
                capability=CapabilityVector(
                    coding=0.90,
                    reasoning=0.90,
                    tool_reliability=0.90,
                    latency=0.1,
                ),
                auto_eligible=True,
                manual_selectable=True,
            )
            candidates.append(
                RouteCandidate(
                    profile=profile,
                    estimated_cost_usd=None,
                    estimate_assumptions=("estimate_pending_task_packet",),
                    configured=True,
                    healthy=True,
                    enabled=True,
                )
            )

        if not for_lead:
            if (
                self.default_child_model not in self.models
                and f"injected:{self.default_child_model}" not in self.models
            ):
                provider = "injected"
                model_name = self.default_child_model
                if ":" in self.default_child_model:
                    provider, model_name = self.default_child_model.split(":", 1)
                profile = ModelProfile(
                    provider=provider,
                    model=model_name,
                    support_level=ProviderSupportLevel.NATIVE,
                    input_usd_per_million=Decimal("1.00"),
                    output_usd_per_million=Decimal("2.00"),
                    context_tokens=128_000,
                    max_output_tokens=8_192,
                    supports_tools=True,
                    supports_structured_output=True,
                    capability=CapabilityVector(
                        coding=0.55,
                        reasoning=0.55,
                        tool_reliability=0.55,
                        latency=0.1,
                    ),
                    auto_eligible=True,
                    manual_selectable=True,
                )
                candidates.append(
                    RouteCandidate(
                        profile=profile,
                        estimated_cost_usd=None,
                        estimate_assumptions=("estimate_pending_task_packet",),
                        configured=True,
                        healthy=True,
                        enabled=True,
                    )
                )

        return RoutingSnapshot(
            catalog_revision=self.catalog_revision,
            config_revision=config_revision({"routing": {"mode": routing_mode.value}}),
            health_revision="health-v1",
            candidates=tuple(candidates),
        )

    async def run_instruction(
        self,
        instruction: str,
        *,
        run_id: RunId | None = None,
        controls: LeadControls | None = None,
        workspace_revision: str = "git:head",
        delegation_approved: bool = False,
    ) -> RunResult:
        if self._pending_run is None and self.checkpoints is not None:
            self.restore_interrupted()
        if self._pending_run is not None or self._has_pending_question():
            raise RuntimeError(
                "run.pending_interrupt: answer or cancel the waiting question "
                "before starting a new run"
            )
        active_controls = resolve_lead_controls(instruction, controls)
        if self.checkpoints is not None:
            self.checkpoints.initialize()
            async with self.checkpoints.saver(str(self.session_id)) as saver:
                await saver.setup()
                return await self._run_instruction_impl(
                    instruction,
                    run_id=run_id,
                      controls=active_controls,
                    workspace_revision=workspace_revision,
                    delegation_approved=delegation_approved,
                    saver=saver,
                )
        return await self._run_instruction_impl(
            instruction,
            run_id=run_id,
              controls=active_controls,
            workspace_revision=workspace_revision,
            delegation_approved=delegation_approved,
            saver=None,
        )

    def _emit_event(
        self,
        *,
        run_id: RunId,
        type: str,
        payload: EventPayload,
        task_id: TaskId | None = None,
        attempt_id: AttemptId | None = None,
    ) -> EventEnvelope:
        with self.journal.transaction() as tx:
            return self._append_event(
                tx,
                run_id=run_id,
                type=type,
                payload=payload,
                task_id=task_id,
                attempt_id=attempt_id,
            )

    def _append_event(
        self,
        tx: Any,
        *,
        run_id: RunId,
        type: str,
        payload: EventPayload,
        task_id: TaskId | None = None,
        attempt_id: AttemptId | None = None,
    ) -> EventEnvelope:
        persisted = tx.connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM events WHERE run_id=?",
            (str(run_id),),
        ).fetchone()[0]
        event = EventEnvelope(
            event_id=new_event_id(),
            session_id=self.session_id,
            run_id=run_id,
            invocation_id=self.invocation_id,
            task_id=task_id,
            attempt_id=attempt_id,
            sequence=int(persisted) + 1,
            occurred_at=datetime.now(UTC),
            type=type,
            payload=payload,
        )
        if self.redactor:
            event = self.redactor.scrub(event)
        tx.append_event(event)
        self.events.publish_after_commit(tx, event)
        return event

    def _build_lead_for_run(
        self,
        *,
        run_id: RunId,
        controls: LeadControls,
        workspace_revision: str,
        delegation_approved: bool,
        recorded_child_results: list[TaskResult],
        leases: WorkspaceLeaseManager,
        gate: ChildRunGate,
        scheduler: ChildScheduler,
        saver: Any,
        lead_assignment: TaskAssignment,
        lead_task_id: TaskId,
        lead_attempt_id: AttemptId,
        lead_context_packet: ContextPacket | None = None,
        restored_decision: Any | None = None,
    ) -> Any:
        delegation_approved = delegation_approved or controls.delegation == "auto"
        allow_delegation = controls.delegation in ("auto", "ask")
        model_call_budget = self._model_call_budget_for_run(run_id)
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
                          controls=controls,
                          delegation_approved=delegation_approved,
                          recorded_child_results=recorded_child_results,
                          model_call_budget=model_call_budget,
                      )
                )
        lead_model_key = f"{lead_assignment.provider}:{lead_assignment.model}"
        lead_chat_model = self._all_models.get(lead_model_key)
        if lead_chat_model is None:
            raise ValueError(f"model {lead_assignment.model} is not available in registered models")
        assignments, active = self.persisted_registry.runtime_bindings()
        lead_middleware = TaskBoundModelMiddleware(
            self._all_models,
            assignments=assignments,
            allow_delegation=allow_delegation,
            providers=self.providers,
            usage_callback=self._record_model_usage,
            call_begin=self.usage_settler.begin_call,
            call_ambiguous=self.usage_settler.mark_ambiguous,
            active_assignments=active,
            redactor=self.redaction,
        )
        authorized_effects = {EffectScope.READ}
        if controls.write_allowed in (None, True):
            authorized_effects.add(EffectScope.WORKSPACE_WRITE)

        def validate_plan(plan: ExecutionPlan) -> None:
            for node in plan.nodes:
                if node.kind is PlanNodeKind.AGENT:
                    request = _task_request_for_plan_node(node)
                    profile = builtin_profiles()[request.profile]
                    if controls.write_allowed in {False} and profile.write_capable:
                        raise TaskValidationError("plan.node_write_disallowed")
                    self.validator.normalize(request, parent_depth=0)
                elif node.kind is PlanNodeKind.TOOL:
                    _validate_plan_tool_node(node)

        active_plan_id: str | None = None

        def admit_plan(plan: ExecutionPlan) -> None:
            nonlocal active_plan_id
            validate_plan(plan)
            persisted = self.journal.admit_plan(
                run_id=str(run_id),
                plan=plan,
                event_observer=self.events.publish_persisted_nowait,
                authorized_effects=frozenset(authorized_effects),
            )
            active_plan_id = persisted.plan_id
            self._admit_ready_plan_agents(
                persisted,
                run_id=run_id,
                controls=controls,
                workspace_revision=workspace_revision,
                lead_assignment=lead_assignment,
                scheduler=scheduler,
            )

        def revise_plan(revision: PlanRevision, plan: ExecutionPlan) -> None:
            if active_plan_id is None:
                raise TaskValidationError("plan.revision_without_active_plan")
            validate_plan(plan)
            allowed_evidence = self._plan_revision_evidence.get(active_plan_id, frozenset())
            if not revision.evidence_refs or not set(revision.evidence_refs) <= allowed_evidence:
                raise TaskValidationError("plan.revision_evidence_unavailable")
            checkpoint = self._plan_revision_checkpoints.get(active_plan_id)
            if checkpoint is not None and checkpoint in {
                *revision.replaced_local_ids,
                *revision.cancelled_local_ids,
            }:
                raise TaskValidationError("plan.active_checkpoint_immutable")
            self.journal.revise_plan(
                plan_id=active_plan_id,
                revision=revision,
                plan=plan,
                event_observer=self.events.publish_persisted_nowait,
                authorized_effects=frozenset(authorized_effects),
            )

        decision_gate = ExecutionDecisionGate(
            admit_plan=admit_plan,
            revise_plan=revise_plan,
            persist_decision=lambda decision: self.journal.record_execution_decision(
                run_id=str(run_id), decision=decision
            ),
            restored_decision=restored_decision,
            required_mode=(ExecutionMode.DIRECT if controls.direct_only else None),
            required_agent_count=controls.required_agent_count,
        )

        def observe_response(response: ModelResponse[Any]) -> None:
            decision_gate.prepare_response(response)
            self._admit_task_batch(
                response,
                run_id=run_id,
                controls=controls,
                workspace_revision=workspace_revision,
                lead_assignment=lead_assignment,
                scheduler=scheduler,
                decision_gate=decision_gate,
            )

        lead_provider = lead_assignment.provider

        def usage_normalizer(response: ModelResponse[Any]) -> NormalizedUsage | None:
            # D-12(1): reuse the settler's accounting normalization verbatim;
            # this stays telemetry-only (record_call remains the journaled
            # source of truth).
            return AssignmentUsageSettler._normalize_response(
                self.usage_settler.providers[lead_provider], response
            )

        return build_production_lead(
            lead_chat_model,
            workspace=self.workspace,
            controls=controls,
            subagents=subagents,
            delegation_approved=delegation_approved,
            isolate_lead_writes=self._workspace_snapshot is not None,
            leases=leases,
            extra_middleware=[lead_middleware, ExecutionDecisionMiddleware(decision_gate)],
            extension_tools=[execution_decision_tool(decision_gate)],
            redactor=self.redaction,
            checkpointer=saver,
            approvals=self.approvals,
            question_store=self.question_store,
            runtime_event=self._activity_emitter(
                run_id=run_id,
                task_id=lead_task_id,
                attempt_id=lead_attempt_id,
            ),
            runtime_model_name=lead_assignment.model,
              model_response_observer=observe_response,
              usage_normalizer=usage_normalizer,
              model_call_guard=model_call_budget.begin_call,
            session_id=str(self.session_id),
            run_id=str(run_id),
            state_dir=self.state_dir,
            context_prompt=(
                _format_context_packet(lead_context_packet)
                if lead_context_packet is not None
                else None
            ),
        )

    def _resolve_planned_spec(self, description: str, profile: str) -> TaskSpec | None:
        queue = self._planned_specs.get((profile, description))
        if not queue:
            return None
        return queue.popleft()

    def _admit_ready_plan_agents(
        self,
        persisted: PersistedPlan,
        *,
        run_id: RunId,
        controls: LeadControls,
        workspace_revision: str,
        lead_assignment: TaskAssignment,
        scheduler: ChildScheduler,
    ) -> None:
        """Bind an admitted plan's initial ready agent frontier to child task records."""
        if controls.delegation == "off":
            return
        nodes = {node.local_id: node for node in persisted.plan.nodes}
        planned: list[tuple[PlanNode, str, TaskSpec, AgentProfile, AttemptId]] = []
        for ready in self.journal.ready_plan_nodes(persisted.plan_id):
            node = nodes[ready.local_id]
            if node.kind is not PlanNodeKind.AGENT:
                continue
            if self.journal.plan_node_task_binding(ready.node_id) is not None:
                continue
            request = _task_request_for_plan_node(node)
            request = request.model_copy(
                update={
                    "source_revisions": (
                        *request.source_revisions,
                        f"plan:{persisted.plan_id}:revision:{persisted.plan.revision}",
                    ),
                    "attempt_lineage": (
                        f"plan:{persisted.plan_id}:{node.task_lineage or node.local_id}"
                    ),
                }
            )
            profile = builtin_profiles()[request.profile]
            if controls.write_allowed is False and profile.write_capable:
                raise TaskValidationError("plan.node_write_disallowed")
            spec = self.validator.create_spec(
                request,
                run_id=run_id,
                parent_task_id=None,
                parent_depth=0,
                workspace_revision=workspace_revision,
                risk=controls.risk,
            )
            planned.append((node, ready.node_id, spec, profile, new_attempt_id()))
        if not planned:
            return
        self.registry.load_from_journal(self.journal, str(self.session_id))
        self.registry.register_many(tuple(item[2] for item in planned))

        now = datetime.now(UTC)
        requests: list[AssignmentRequest] = []
        for node, node_id, spec, profile, attempt_id in planned:
            self.journal.transition_plan_node_state(
                plan_id=persisted.plan_id,
                node_id=node_id,
                expected=PlanNodeState.READY,
                target=PlanNodeState.LAUNCHING,
                event_observer=self.events.publish_persisted_nowait,
            )
            self.registry.transition(
                spec.task_id,
                expected=TaskStatus.PROPOSED,
                target=TaskStatus.QUEUED,
                attempt_number=1,
            )
            self.journal.create_task(
                task_id=str(spec.task_id),
                run_id=str(run_id),
                description=spec.request.description,
                status="queued",
                idempotency_key=f"task:{spec.task_id}",
                created_at=now,
                fingerprint=spec.fingerprint,
            )
            self.journal.create_attempt(
                attempt_id=str(attempt_id),
                task_id=str(spec.task_id),
                number=1,
                status="assigned",
                idempotency_key=f"attempt:{attempt_id}",
                created_at=now,
            )
            self.journal.bind_plan_node_task(
                node_id=node_id,
                task_id=str(spec.task_id),
                attempt_id=str(attempt_id),
            )
            scheduler.submit(str(spec.task_id), priority=spec.request.priority)
            self._planned_specs.setdefault(
                (profile.name, spec.request.description), deque()
            ).append(spec)
            self._plan_nodes_by_task[str(spec.task_id)] = (persisted.plan_id, node_id)
            self._planned_node_dispatches.append(
                _PlannedNodeDispatch(persisted.plan_id, node_id, profile, spec)
            )
            self._emit_event(
                run_id=run_id,
                type="task.proposed",
                payload=TaskPayload(status="proposed", profile=profile.name),
                task_id=spec.task_id,
            )
            self._emit_event(
                run_id=run_id,
                type="task.queued",
                payload=TaskPayload(status="queued", profile=profile.name),
                task_id=spec.task_id,
            )
            configured_model = self.fixed_profile_models.get(
                profile.name, self.profile_models.get(profile.name)
            )
            if configured_model is None and controls.model:
                configured_model = controls.model
            policy = spec.request.model_policy
            if policy is not None and policy.model is not None:
                configured_model = (
                    f"{policy.provider}:{policy.model}" if policy.provider else policy.model
                )
            mode = RoutingMode.MANUAL if configured_model else controls.routing_mode
            manual_model: tuple[str, str] | None = None
            if configured_model:
                provider, model = "injected", configured_model
                if ":" in configured_model:
                    provider, model = configured_model.split(":", 1)
                manual_model = (provider, model)
            requirements = self._requirements.for_assignment(
                spec.requirements,
                role=profile.role,
                risk=controls.risk,
                mode=mode,
                role_hard_min=profile.role_floor,
            )
            requests.append(
                AssignmentRequest(
                    session_id=self.session_id,
                    run_id=run_id,
                    task_id=spec.task_id,
                    attempt_id=attempt_id,
                    attempt_number=1,
                    catalog_revision=self.catalog_revision,
                    requirements=requirements,
                    config_snapshot=self._routing_config_snapshot(controls.routing_mode),
                    manual_model=manual_model,
                    task_limit_usd=spec.request.budget_usd,
                )
            )

        specs_by_id = {str(spec.task_id): spec for _, _, spec, _, _ in planned}
        profiles_by_task = {str(spec.task_id): profile for _, _, spec, profile, _ in planned}

        def batch_candidates(request: AssignmentRequest) -> RoutingSnapshot:
            spec = specs_by_id[str(request.task_id)]
            profile = profiles_by_task[str(request.task_id)]
            packet = self.assembler.assemble(
                task_id=str(spec.task_id),
                objective=spec.request.description,
                constraints=spec.request.success_criteria,
                state="attempt=1; assignment=pending",
            )
            snapshot = self._estimate_snapshot(
                self._get_candidates(
                    for_lead=False,
                    target_lead_model=controls.model or self.default_lead_model,
                    routing_mode=controls.routing_mode,
                ),
                packet=packet,
                profile=profile,
                minimum_output_tokens=request.requirements.minimum_output_tokens,
            )
            policy = spec.request.model_policy
            if policy is None or policy.provider is None:
                return snapshot
            return snapshot.model_copy(
                update={
                    "candidates": tuple(
                        candidate
                        for candidate in snapshot.candidates
                        if candidate.profile.provider == policy.provider
                    )
                }
            )

        result = self.assignment_service.assign_batch(
            tuple(requests),
            batch_candidates,
            lead_allowance_usd=lead_assignment.estimated_attempt_cost_usd,
        )
        if result.lead_reservation_id:
            self._lead_allowance_ids.append(result.lead_reservation_id)
        assignments = {str(item.task_id): item for item in result.assignments}
        for _, _, spec, _, attempt_id in planned:
            assignment = assignments.get(str(spec.task_id))
            self._planned_assignments[str(spec.task_id)] = (
                AttemptBinding(str(attempt_id), assignment)
                if assignment is not None
                else _route_failure_for_task(result, str(spec.task_id))
            )

    async def _finalize_completion(
        self,
        *,
        run_id: RunId,
        workspace_revision: str,
        leases: WorkspaceLeaseManager,
        gate: ChildRunGate,
        scheduler: ChildScheduler,
        controls: LeadControls,
        delegation_approved: bool,
        lead_assignment: TaskAssignment,
        lead_agent: Any,
        lead_attempt_id: AttemptId,
        invoke_config: RunnableConfig,
        recorded_child_results: list[TaskResult],
    ) -> tuple[dict[str, Any] | None, bool]:
        """Single coordinator finalization path for initial and resumed runs."""
        completed_state = await self._dispatch_admitted_plan_agents(
            run_id=run_id,
            workspace_revision=workspace_revision,
            leases=leases,
            gate=gate,
            scheduler=scheduler,
            controls=controls,
            delegation_approved=delegation_approved,
            lead_assignment=lead_assignment,
            lead_agent=lead_agent,
            lead_attempt_id=lead_attempt_id,
            invoke_config=invoke_config,
            recorded_child_results=recorded_child_results,
        )
        return completed_state

    def _gated_noop_requires_blocked(
        self,
        *,
        run_id: RunId,
        recorded_child_results: Sequence[TaskResult],
    ) -> bool:
        """Detect the gated no-op signature: rejections, no decision, no work.

        True only when (a) at least one operational tool call was rejected
        with ``execution.decision_required``, (b) no execution decision was
        ever admitted for the run, and (c) no operational tool ever completed
        and no child work ran. A pure final answer (zero tool events) returns
        False so P1 (ADR 0006:24) still completes successfully.
        """
        if recorded_child_results:
            return False
        if self.journal.get_execution_decision(str(run_id)) is not None:
            return False
        saw_required_rejection = False
        saw_completion = False
        for event in self.journal.events_after(run_id=str(run_id)):
            if event.type == "tool.completed":
                saw_completion = True
            elif event.type == "tool.failed":
                payload = event.payload
                reason = payload.reason if isinstance(payload, ToolPayload) else None
                if isinstance(reason, str) and reason.startswith(
                    "execution.decision_required"
                ):
                    saw_required_rejection = True
        return saw_required_rejection and not saw_completion

    async def _dispatch_admitted_plan_agents(
        self,
        *,
        run_id: RunId,
        workspace_revision: str,
        leases: WorkspaceLeaseManager,
        gate: ChildRunGate,
        scheduler: ChildScheduler,
        controls: LeadControls,
        delegation_approved: bool,
        lead_assignment: TaskAssignment,
        lead_agent: Any,
        lead_attempt_id: AttemptId,
        invoke_config: RunnableConfig,
        recorded_child_results: list[TaskResult],
    ) -> tuple[dict[str, Any] | None, bool]:
        """Run the persisted ready frontier, releasing dependents at each completion."""
        running: dict[asyncio.Task[Any], tuple[str, str]] = {}
        dispatched = 0
        latest_lead_state: dict[str, Any] | None = None
        checkpoint_blocked = False

        async def start_ready_tools() -> None:
            for persisted in self.journal.plans_for_run(str(run_id)):
                nodes = {node.local_id: node for node in persisted.plan.nodes}
                for ready in self.journal.ready_plan_nodes(persisted.plan_id):
                    node = nodes[ready.local_id]
                    if node.kind is not PlanNodeKind.TOOL:
                        continue
                    self.journal.transition_plan_node_state(
                        plan_id=persisted.plan_id,
                        node_id=ready.node_id,
                        expected=PlanNodeState.READY,
                        target=PlanNodeState.LAUNCHING,
                        event_observer=self.events.publish_persisted_nowait,
                    )
                    self.journal.begin_plan_node_execution(
                        node_id=ready.node_id, execution_key=f"tool:{ready.node_id}"
                    )

                    async def execute_tool(
                        *,
                        plan_id: str = persisted.plan_id,
                        node_id: str = ready.node_id,
                        plan_node: PlanNode = node,
                    ) -> None:
                        self.journal.transition_plan_node_state(
                            plan_id=plan_id,
                            node_id=node_id,
                            expected=PlanNodeState.LAUNCHING,
                            target=PlanNodeState.RUNNING,
                            event_observer=self.events.publish_persisted_nowait,
                        )
                        result = await self._run_plan_tool_node(
                            run_id=run_id,
                            node_id=node_id,
                            node=plan_node,
                            controls=controls,
                            leases=leases,
                            scheduler=scheduler,
                        )
                        self._settle_plan_node(plan_id, node_id, result.model_dump(mode="json"))

                    task = asyncio.create_task(
                        execute_tool(), name=f"skail-plan-tool-{ready.node_id}"
                    )
                    running[task] = (persisted.plan_id, ready.node_id)

        async def admit_ready_agents() -> None:
            for persisted in self.journal.plans_for_run(str(run_id)):
                self._admit_ready_plan_agents(
                    persisted,
                    run_id=run_id,
                    controls=controls,
                    workspace_revision=workspace_revision,
                    lead_assignment=lead_assignment,
                    scheduler=scheduler,
                )

        async def run_ready_checkpoint() -> bool:
            nonlocal latest_lead_state, checkpoint_blocked
            for persisted in self.journal.plans_for_run(str(run_id)):
                nodes = {node.local_id: node for node in persisted.plan.nodes}
                for ready in self.journal.ready_plan_nodes(persisted.plan_id):
                    node = nodes[ready.local_id]
                    if node.kind is not PlanNodeKind.CHECKPOINT:
                        continue
                    evidence_refs = self._checkpoint_evidence_refs(
                        persisted,
                        node,
                        recorded_child_results,
                    )
                    self._plan_revision_evidence[persisted.plan_id] = frozenset(evidence_refs)
                    self._plan_revision_checkpoints[persisted.plan_id] = node.local_id
                    self.journal.transition_plan_node_state(
                        plan_id=persisted.plan_id,
                        node_id=ready.node_id,
                        expected=PlanNodeState.READY,
                        target=PlanNodeState.LAUNCHING,
                        event_observer=self.events.publish_persisted_nowait,
                    )
                    self.journal.begin_plan_node_execution(
                        node_id=ready.node_id,
                        execution_key=(
                            f"checkpoint:{ready.node_id}:revision:{persisted.plan.revision}"
                        ),
                    )
                    self.journal.transition_plan_node_state(
                        plan_id=persisted.plan_id,
                        node_id=ready.node_id,
                        expected=PlanNodeState.LAUNCHING,
                        target=PlanNodeState.RUNNING,
                        event_observer=self.events.publish_persisted_nowait,
                    )
                    checkpoint_payload = {
                        "type": "skail.plan_checkpoint",
                        "plan_id": persisted.plan_id,
                        "expected_revision": persisted.plan.revision,
                        "checkpoint": node.model_dump(mode="json"),
                        "current_plan": persisted.plan.model_dump(mode="json"),
                        "evidence_refs": evidence_refs,
                        "instruction": (
                            "Reconsider the plan from this evidence. Call execution_decision "
                            "with a complete next-revision plan and PlanRevision metadata."
                        ),
                    }
                    latest_lead_state = cast(
                        dict[str, Any],
                        await lead_agent.ainvoke(
                            {
                                "messages": [
                                    SystemMessage(
                                        content=json.dumps(
                                            checkpoint_payload,
                                            sort_keys=True,
                                            separators=(",", ":"),
                                        )
                                    )
                                ],
                                "attempt_id": str(lead_attempt_id),
                            },
                            config=invoke_config,
                        ),
                    )
                    revised = self.journal.get_plan(persisted.plan_id)
                    if revised.plan.revision <= persisted.plan.revision:
                        self._settle_plan_node(
                            persisted.plan_id,
                            ready.node_id,
                            {
                                "status": "blocked",
                                "summary": "plan.checkpoint_revision_required",
                            },
                        )
                        checkpoint_blocked = True
                    else:
                        self._settle_plan_node(
                            persisted.plan_id,
                            ready.node_id,
                            {
                                "status": "succeeded",
                                "summary": "checkpoint admitted an evidence-backed revision",
                            },
                        )
                    self._plan_revision_evidence.pop(persisted.plan_id, None)
                    self._plan_revision_checkpoints.pop(persisted.plan_id, None)
                    return True
            return False

        try:
            while True:
                while dispatched < len(self._planned_node_dispatches):
                    dispatch = self._planned_node_dispatches[dispatched]
                    dispatched += 1
                    execution = self.journal.begin_plan_node_execution(
                        node_id=dispatch.node_id,
                        execution_key=f"task:{dispatch.spec.task_id}",
                    )
                    if execution.status == "settled":
                        continue
                    subagent = self._build_profile_subagent(
                        profile=dispatch.profile,
                        run_id=run_id,
                        workspace_revision=workspace_revision,
                        leases=leases,
                        gate=gate,
                        scheduler=scheduler,
                        controls=controls,
                        delegation_approved=delegation_approved,
                        recorded_child_results=recorded_child_results,
                        model_call_budget=self._model_call_budget_for_run(run_id),
                    )
                    task = asyncio.create_task(
                        subagent["runnable"].ainvoke(
                            {"messages": [HumanMessage(content=dispatch.spec.request.description)]}
                        ),
                        name=f"skail-plan-agent-{dispatch.node_id}",
                    )
                    running[task] = (dispatch.plan_id, dispatch.node_id)
                await start_ready_tools()
                if not running:
                    checkpoint_ran = await run_ready_checkpoint()
                    if checkpoint_blocked:
                        break
                    if checkpoint_ran:
                        await admit_ready_agents()
                        continue
                    await admit_ready_agents()
                    if dispatched == len(self._planned_node_dispatches):
                        break
                    continue
                done, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    await task
                    running.pop(task)
                await admit_ready_agents()
        finally:
            for task in running:
                task.cancel()
            await asyncio.gather(*running, return_exceptions=True)
            for plan_id, node_id in running.values():
                self._cancel_plan_node(plan_id, node_id)
        checkpoint_blocked = checkpoint_blocked or any(
            state is not PlanNodeState.SUCCEEDED
            for persisted in self.journal.plans_for_run(str(run_id))
            for state in persisted.node_states.values()
        )
        return latest_lead_state, checkpoint_blocked

    def _checkpoint_evidence_refs(
        self,
        persisted: PersistedPlan,
        checkpoint: PlanNode,
        results: Sequence[TaskResult],
    ) -> tuple[str, ...]:
        results_by_task = {str(result.task_id): result for result in results}
        references: list[str] = []
        for dependency in checkpoint.depends_on:
            dependency_node_id = persisted.node_ids[dependency]
            references.append(f"plan-node:{dependency}:succeeded")
            binding = self.journal.plan_node_task_binding(dependency_node_id)
            result = None if binding is None else results_by_task.get(binding.task_id)
            if result is None:
                continue
            for artifact in result.artifacts:
                if artifact.digest:
                    references.append(f"{artifact.kind}:{artifact.path}:{artifact.digest}")
            for verification in result.verification:
                evidence = verification.evidence_ref
                if verification.passed and evidence is not None and evidence.digest:
                    references.append(f"{evidence.kind}:{evidence.path}:{evidence.digest}")
        return tuple(dict.fromkeys(references))

    async def _run_plan_tool_node(
        self,
        *,
        run_id: RunId,
        node_id: str,
        node: PlanNode,
        controls: LeadControls,
        leases: WorkspaceLeaseManager,
        scheduler: ChildScheduler,
    ) -> TaskResult:
        features = dict(node.task_features)
        if set(features) - {"tool", "command", "arguments", "priority"}:
            return TaskResult(
                task_id=TaskId(node_id),
                status="blocked",
                summary="plan.tool_features_invalid",
            )
        if features.get("tool") != "execute" or not isinstance(features.get("command"), str):
            return TaskResult(
                task_id=TaskId(node_id),
                status="blocked",
                summary="plan.tool_unauthorized",
            )
        arguments = features.get("arguments", ())
        if not isinstance(arguments, (list, tuple)) or not all(
            isinstance(item, str) for item in arguments
        ):
            return TaskResult(
                task_id=TaskId(node_id),
                status="blocked",
                summary="plan.tool_features_invalid",
            )
        policy = ExecutionPolicy(
            self.workspace,
            ExecutionSecurityContext(
                trusted_project=self.project_trusted,
                workspace_write_allowed=controls.write_allowed in (None, True),
                write_lease_held=node.effect_scope is not EffectScope.READ,
            ),
        )
        request = CommandRequest(
            features["command"],
            tuple(arguments),
            self.workspace,
            session_id=str(self.session_id),
            run_id=str(run_id),
            task_id=node_id,
            action_id=f"plan-tool:{node_id}",
        )

        async def operation() -> TaskResult:
            if node.effect_scope is EffectScope.READ:
                result = await asyncio.to_thread(
                    policy.run, request, interactive=False, approvals=self.approvals
                )
            else:
                async with leases.acquire(node_id):
                    result = await asyncio.to_thread(
                        policy.run, request, interactive=False, approvals=self.approvals
                    )
            status: Literal["succeeded", "blocked"] = (
                "succeeded"
                if result.status == "completed" and result.returncode == 0
                else "blocked"
            )
            if result.status == "approval_required":
                self._pending_interrupt_payload = {
                    "kind": "approval",
                    "type": "plan_tool_approval",
                    "plan_id": next(
                        persisted.plan_id
                        for persisted in self.journal.plans_for_run(str(run_id))
                        if node_id in persisted.node_ids.values()
                    ),
                    "node_id": node_id,
                    "command": request.executable,
                    "arguments": list(request.arguments),
                    "cwd": str(request.cwd),
                    "session_id": request.session_id,
                    "run_id": request.run_id,
                    "task_id": request.task_id,
                    "action_id": request.action_id,
                }
            return TaskResult(
                task_id=TaskId(node_id),
                status=status,
                summary=f"tool execute {result.status}",
                verification_authority="runtime",
            )

        scheduler.submit(node_id, priority=int(features.get("priority", 0)))
        return cast(TaskResult, await scheduler.execute(node_id, operation))

    def _settle_plan_node(self, plan_id: str, node_id: str, result: dict[str, Any]) -> None:
        self.journal.settle_plan_node_execution(node_id=node_id, result=result)
        persisted = self.journal.get_plan(plan_id)
        local_id = next(
            (local for local, value in persisted.node_ids.items() if value == node_id),
            None,
        )
        if local_id is None:
            return
        state = persisted.node_states[local_id]
        status = result.get("status")
        target = {
            "succeeded": PlanNodeState.SUCCEEDED,
            "cancelled": PlanNodeState.CANCELLED,
            "blocked": PlanNodeState.BLOCKED,
            "budget_blocked": PlanNodeState.BLOCKED,
        }.get(status if isinstance(status, str) else "", PlanNodeState.FAILED)
        if state is PlanNodeState.LAUNCHING and target is not PlanNodeState.BLOCKED:
            self.journal.transition_plan_node_state(
                plan_id=plan_id,
                node_id=node_id,
                expected=PlanNodeState.LAUNCHING,
                target=PlanNodeState.RUNNING,
                event_observer=self.events.publish_persisted_nowait,
            )
            state = PlanNodeState.RUNNING
        if state in {PlanNodeState.LAUNCHING, PlanNodeState.RUNNING}:
            self.journal.transition_plan_node_state(
                plan_id=plan_id,
                node_id=node_id,
                expected=state,
                target=target,
                event_observer=self.events.publish_persisted_nowait,
            )

    def _cancel_plan_node(self, plan_id: str, node_id: str) -> None:
        self._settle_plan_node(plan_id, node_id, {"status": "cancelled"})
        binding = self.journal.plan_node_task_binding(node_id)
        if binding is not None:
            self.journal.update_attempt_status(
                attempt_id=binding.attempt_id, status=AttemptStatus.CANCELLED
            )
            self.journal.update_task_status(task_id=binding.task_id, status=TaskStatus.CANCELLED)

    def _admit_task_batch(
        self,
        response: ModelResponse[Any],
        *,
        run_id: RunId,
        controls: LeadControls,
        workspace_revision: str,
        lead_assignment: TaskAssignment,
        scheduler: ChildScheduler,
        decision_gate: ExecutionDecisionGate,
    ) -> None:
        if (
            controls.delegation == "off"
            or decision_gate.decision is None
            or decision_gate.decision.mode is not ExecutionMode.DIRECT
        ):
            return
        calls = [
            call
            for message in response.result
            if isinstance(message, AIMessage)
            for call in message.tool_calls
            if call.get("name") == "task"
            and isinstance(call.get("id"), str)
            and decision_gate.allows("task", call["id"])
        ]
        if not calls:
            return
        planned: list[tuple[TaskSpec, str, AgentProfile, AttemptId]] = []
        for call in calls:
            args = call.get("args", {})
            if not isinstance(args, Mapping):
                continue
            description = str(args.get("description", ""))
            profile_name = str(
                args.get("subagent_type", args.get("profile", "general-purpose"))
            )
            profile = builtin_profiles().get(profile_name)
            if profile is None:
                continue
            if controls.write_allowed in {False} and profile.write_capable:
                continue
            try:
                request = decode_task_request(description, profile=profile_name)
                spec = self.validator.create_spec(
                    request,
                    run_id=run_id,
                    parent_task_id=None,
                    parent_depth=0,
                    workspace_revision=workspace_revision,
                    risk=controls.risk,
                )
            except TaskValidationError:
                continue
            planned.append((spec, description, profile, new_attempt_id()))
        if not planned:
            return
        try:
            self.registry.register_many(tuple(item[0] for item in planned))
        except TaskValidationError:
            return

        existing_plans = self.journal.plans_for_run(str(run_id))
        existing_plan = existing_plans[0] if existing_plans else None
        first_index = 1 if existing_plan is None else len(existing_plan.plan.nodes) + 1
        added_nodes = tuple(
            PlanNode(
                local_id=f"compat-task-{index}",
                kind=PlanNodeKind.AGENT,
                objective=spec.request.description,
                acceptance_criteria=spec.request.success_criteria,
                effect_scope=(
                    EffectScope.WORKSPACE_WRITE if profile.write_capable else EffectScope.READ
                ),
                task_features={"profile": profile.name},
                task_lineage=f"compat:{spec.task_id}",
            )
            for index, (spec, _, profile, _) in enumerate(planned, start=first_index)
        )
        authorized_effects = frozenset(
            {EffectScope.READ, EffectScope.WORKSPACE_WRITE}
            if controls.write_allowed in (None, True)
            else {EffectScope.READ}
        )
        if existing_plan is None:
            compatibility_plan = self.journal.admit_plan(
                run_id=str(run_id),
                plan=ExecutionPlan(
                    schema_version=1,
                    policy_version="adaptive-v1",
                    revision=1,
                    nodes=added_nodes,
                ),
                event_observer=self.events.publish_persisted_nowait,
                authorized_effects=authorized_effects,
            )
        else:
            next_revision = existing_plan.plan.revision + 1
            compatibility_plan = self.journal.revise_plan(
                plan_id=existing_plan.plan_id,
                revision=PlanRevision(
                    expected_revision=existing_plan.plan.revision,
                    added_nodes=added_nodes,
                    justification="Admit standard task calls through the canonical plan.",
                    evidence_refs=tuple(f"tool-call:{call['id']}" for call in calls),
                ),
                plan=existing_plan.plan.model_copy(
                    update={
                        "revision": next_revision,
                        "nodes": (*existing_plan.plan.nodes, *added_nodes),
                    }
                ),
                event_observer=self.events.publish_persisted_nowait,
                authorized_effects=authorized_effects,
            )

        for spec, _, _, _ in planned:
            for dependency in spec.request.depends_on:
                dependency_key = str(dependency)
                if dependency_key not in scheduler._children:
                    registered = self.registry.get(dependency)
                    scheduler.submit(dependency_key, priority=registered.spec.request.priority)
                    if registered.status is TaskStatus.SUCCEEDED:
                        scheduler.finish(dependency_key, succeeded=True)
                    elif registered.status in TERMINAL_TASK_STATUSES:
                        scheduler.finish(dependency_key, succeeded=False)
            scheduler.submit(
                str(spec.task_id),
                priority=spec.request.priority,
                depends_on=tuple(str(item) for item in spec.request.depends_on),
            )

        now = datetime.now(UTC)
        requests: list[AssignmentRequest] = []
        for index, (spec, description, profile, attempt_id) in enumerate(
            planned, start=first_index
        ):
            self.registry.transition(
                spec.task_id,
                expected=TaskStatus.PROPOSED,
                target=TaskStatus.QUEUED,
                attempt_number=1,
            )
            self.journal.create_task(
                task_id=str(spec.task_id),
                run_id=str(run_id),
                description=spec.request.description,
                status="queued",
                idempotency_key=f"task:{spec.task_id}",
                created_at=now,
                fingerprint=spec.fingerprint,
            )
            self.journal.create_attempt(
                attempt_id=str(attempt_id),
                task_id=str(spec.task_id),
                number=1,
                status="assigned",
                idempotency_key=f"attempt:{attempt_id}",
                created_at=now,
            )
            local_id = f"compat-task-{index}"
            node_id = compatibility_plan.node_ids[local_id]
            self.journal.bind_plan_node_task(
                node_id=node_id,
                task_id=str(spec.task_id),
                attempt_id=str(attempt_id),
            )
            self.journal.transition_plan_node_state(
                plan_id=compatibility_plan.plan_id,
                node_id=node_id,
                expected=PlanNodeState.READY,
                target=PlanNodeState.LAUNCHING,
                event_observer=self.events.publish_persisted_nowait,
            )
            self.journal.begin_plan_node_execution(
                node_id=node_id,
                execution_key=f"task:{spec.task_id}",
            )
            self._plan_nodes_by_task[str(spec.task_id)] = (
                compatibility_plan.plan_id,
                node_id,
            )
            model_policy = spec.request.model_policy
            configured_model = self.fixed_profile_models.get(
                profile.name, self.profile_models.get(profile.name)
            )
            if configured_model is None and controls.model:
                configured_model = controls.model
            if model_policy is not None and model_policy.model is not None:
                configured_model = (
                    f"{model_policy.provider}:{model_policy.model}"
                    if model_policy.provider
                    else model_policy.model
                )
            mode = RoutingMode.MANUAL if configured_model else controls.routing_mode
            manual_model: tuple[str, str] | None = None
            if configured_model:
                provider, model = "injected", configured_model
                if ":" in configured_model:
                    provider, model = configured_model.split(":", 1)
                manual_model = (provider, model)
            requirements = self._requirements.for_assignment(
                spec.requirements,
                role=profile.role,
                risk=controls.risk,
                mode=mode,
                role_hard_min=profile.role_floor,
            )
            requests.append(
                AssignmentRequest(
                    session_id=self.session_id,
                    run_id=run_id,
                    task_id=spec.task_id,
                    attempt_id=attempt_id,
                    attempt_number=1,
                    catalog_revision=self.catalog_revision,
                    requirements=requirements,
                    config_snapshot=self._routing_config_snapshot(controls.routing_mode),
                    manual_model=manual_model,
                    task_limit_usd=spec.request.budget_usd,
                )
            )
            self._planned_specs.setdefault((profile.name, description), deque()).append(spec)
            self._emit_event(
                run_id=run_id,
                type="task.proposed",
                payload=TaskPayload(status="proposed", profile=profile.name),
                task_id=spec.task_id,
            )
            self._emit_event(
                run_id=run_id,
                type="task.queued",
                payload=TaskPayload(status="queued", profile=profile.name),
                task_id=spec.task_id,
            )

        specs_by_id = {str(item[0].task_id): item[0] for item in planned}
        profiles_by_task = {str(spec.task_id): profile for spec, _, profile, _ in planned}

        def batch_candidates(request: AssignmentRequest) -> RoutingSnapshot:
            spec = specs_by_id[str(request.task_id)]
            profile = profiles_by_task[str(request.task_id)]
            packet = self.assembler.assemble(
                task_id=str(spec.task_id),
                objective=spec.request.description,
                constraints=spec.request.success_criteria,
                state="attempt=1; assignment=pending",
            )
            snapshot = self._get_candidates(
                for_lead=False,
                target_lead_model=controls.model or self.default_lead_model,
                routing_mode=controls.routing_mode,
            )
            snapshot = self._estimate_snapshot(
                snapshot,
                packet=packet,
                profile=profile,
                minimum_output_tokens=request.requirements.minimum_output_tokens,
            )
            policy = spec.request.model_policy
            if policy is None or policy.provider is None:
                return snapshot
            return snapshot.model_copy(
                update={
                    "candidates": tuple(
                        candidate
                        for candidate in snapshot.candidates
                        if candidate.profile.provider == policy.provider
                    )
                }
            )

        result = self.assignment_service.assign_batch(
            tuple(requests),
            batch_candidates,
            lead_allowance_usd=lead_assignment.estimated_attempt_cost_usd,
        )
        if result.lead_reservation_id:
            self._lead_allowance_ids.append(result.lead_reservation_id)
        bindings = {str(item.task_id): item for item in result.assignments}
        for spec, _, _, attempt_id in planned:
            assignment = bindings.get(str(spec.task_id))
            self._planned_assignments[str(spec.task_id)] = (
                AttemptBinding(str(attempt_id), assignment)
                if assignment is not None
                else _route_failure_for_task(result, str(spec.task_id))
            )

    def _activity_emitter(
        self,
        *,
        run_id: RunId,
        task_id: TaskId,
        attempt_id: AttemptId,
    ) -> Callable[..., None]:
        def emit(
            event_type: str, subject: str, reason: str | NormalizedUsage | None = None
        ) -> None:
            suffix = event_type.split(".", 1)[1]
            payload: EventPayload
            if event_type.startswith("model."):
                # D-12(1): telemetry only. Usage rides the third positional
                # slot; counts/decimals and the authority constant are safe,
                # non-secret.
                usage = reason if isinstance(reason, NormalizedUsage) else None
                payload = ModelPayload(
                    model=subject,
                    input_tokens=usage.input_tokens if usage is not None else None,
                    output_tokens=usage.output_tokens if usage is not None else None,
                    cost_usd=(
                        float(usage.cost_usd)
                        if usage is not None and usage.cost_usd is not None
                        else None
                    ),
                    usage_authority=usage.authority.value if usage is not None else None,
                )
            elif event_type.startswith("user."):
                content = (
                    self.redaction.scrub_text(reason)[:500]
                    if isinstance(reason, str)
                    else None
                )
                payload = UserPayload(
                    action=suffix,
                    kind=(
                        InterruptKind.QUESTION
                        if suffix in {"question", "answer"}
                        else None
                    ),
                    interrupt_id=subject,
                    content=content,
                )
            else:
                clean_reason: str | None = None
                if isinstance(reason, str) and reason:
                    clean_reason = self.redaction.scrub_text(reason)[:500]
                payload = ToolPayload(
                    tool=subject, status=suffix, reason=clean_reason
                )
            self._emit_event(
                run_id=run_id,
                type=event_type,
                payload=payload,
                task_id=task_id,
                attempt_id=attempt_id,
            )

        return emit

    async def _run_instruction_impl(
        self,
        instruction: str,
        *,
        run_id: RunId | None = None,
        controls: LeadControls | None = None,
        workspace_revision: str = "git:head",
        delegation_approved: bool = False,
        saver: Any = None,
    ) -> RunResult:
        active_controls = controls or LeadControls()
        self._planned_specs.clear()
        self._planned_assignments.clear()
        self._planned_node_dispatches.clear()
        self._plan_nodes_by_task.clear()
        self._lead_allowance_ids.clear()
        self._plan_revision_evidence.clear()
        self._plan_revision_checkpoints.clear()
        max_children = min(max(active_controls.max_children, 1), 3)

        # Run-scoped locks and gates shared across lead and all children
        leases = WorkspaceLeaseManager()
        gate = ChildRunGate(max_children)
        scheduler = ChildScheduler(max_children=max_children)

        run_id = run_id or new_run_id()
        now = datetime.now(UTC)

        self.workspace_selection = self.workspace_manager.select(
            self.workspace, self.workspace_mode
        )
        self._workspace_snapshot = None
        if (
            active_controls.delegation == "off"
            and self.workspace_selection.mode is WorkspaceMode.WORKTREE
        ):
            self.workspace_selection = WorkspaceSelection(
                WorkspaceMode.SHARED,
                "workspace.isolation_unavailable: delegation-off",
            )
        if self.workspace_selection.mode is WorkspaceMode.WORKTREE:
            try:
                self._workspace_snapshot = self.workspace_manager.capture(self.workspace)
            except ValueError as error:
                self.workspace_selection = WorkspaceSelection(WorkspaceMode.SHARED, str(error))
        if self._workspace_snapshot is not None:
            workspace_revision = f"snapshot:{self._workspace_snapshot.snapshot_id}"

        async def _save_checkpoint(
            boundary: str,
            status: str = "committed",
            live_idempotency_keys: tuple[str, ...] | None = None,
            extra_payload: Mapping[str, Any] | None = None,
        ) -> None:
            if self.checkpoints is None or saver is None:
                return
            thread_id = self._checkpoint_thread_id(run_id)
            t = await saver.aget_tuple({"configurable": {"thread_id": thread_id}})
            if t and t.config and "configurable" in t.config:
                cid = t.config["configurable"].get("checkpoint_id")
                if cid:
                    self.checkpoints.record(
                        session_id=str(self.session_id),
                        thread_id=thread_id,
                        checkpoint_id=cid,
                        idempotency_key=f"run:{run_id}:{boundary}:{cid}",
                        status=status,
                        payload={
                            "run_id": str(run_id),
                            "boundary": boundary,
                            "status": status,
                            **dict(extra_payload or {}),
                        },
                        created_at=datetime.now(UTC),
                        live_idempotency_keys=live_idempotency_keys,
                    )

        # 1. Create run record in journal
        self.journal.create_run(
            run_id=str(run_id),
            session_id=str(self.session_id),
            status="running",
            budget_limit_usd=self.budget_limit_usd,
            created_at=now,
        )
        self._emit_event(
            run_id=run_id,
            type="run.started",
            payload=LifecyclePayload(status="started"),
        )
        self._emit_event(
            run_id=run_id,
            type="diagnostic.workspace",
            payload=DiagnosticPayload(
                code=self.workspace_selection.reason,
                summary="Workspace execution mode selected.",
                details={
                    "mode": self.workspace_selection.mode.value,
                    "snapshot_id": (
                        self._workspace_snapshot.snapshot_id
                        if self._workspace_snapshot is not None
                        else None
                    ),
                },
            ),
        )

        # 2. Persist lead task and attempt BEFORE assignment
        lead_model_name = active_controls.model or self.default_lead_model
        lead_task_id = new_task_id()
        lead_attempt_id = new_attempt_id()

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

        # 3. Route lead model through AssignmentService and BudgetLedger
        lead_provider = "injected"
        lead_model = lead_model_name
        if ":" in lead_model_name:
            lead_provider, lead_model = lead_model_name.split(":", 1)

        lead_mode = RoutingMode.MANUAL if active_controls.model else active_controls.routing_mode
        lead_profile = builtin_profiles()["lead"]
        lead_reqs = self._requirements.build(
            role=lead_profile.role,
            risk=active_controls.risk,
            mode=lead_mode,
            role_hard_min=lead_profile.role_floor,
            required_tools=bool(lead_profile.tools),
            required_structured_output=lead_profile.response_schema is not None,
        )
        lead_config_snapshot = self._routing_config_snapshot(active_controls.routing_mode)
        lead_request = AssignmentRequest(
            session_id=self.session_id,
            run_id=run_id,
            task_id=lead_task_id,
            attempt_id=lead_attempt_id,
            attempt_number=1,
            catalog_revision=self.catalog_revision,
            requirements=lead_reqs,
            config_snapshot=lead_config_snapshot,
            manual_model=(lead_provider, lead_model) if lead_mode is RoutingMode.MANUAL else None,
        )
        lead_preflight_packet = self.assembler.assemble(
            task_id=str(run_id),
            objective=instruction,
            constraints=(),
            state=f"run_id={run_id}; assignment=pending",
            references=self._compaction_references(),
        )
        assigned_lead = self.assignment_service.assign(
            lead_request,
            lambda: self._estimate_snapshot(
                self._get_candidates(
                    for_lead=True,
                    target_lead_model=active_controls.model,
                    routing_mode=active_controls.routing_mode,
                ),
                packet=lead_preflight_packet,
                profile=lead_profile,
                minimum_output_tokens=lead_reqs.minimum_output_tokens,
            ),
        )
        if isinstance(assigned_lead, RouteFailure):
            budget_blocked = assigned_lead.binding_constraint == "budget_unaffordable"
            lead_context_packet = self.assembler.assemble(
                task_id=str(run_id),
                objective=instruction,
                constraints=(),
                state=f"run_id={run_id}; route_failure={assigned_lead.binding_constraint}",
            )
            self._persist_context_packet(
                lead_context_packet,
                run_id=run_id,
                task_id=str(lead_task_id),
                attempt_id=str(lead_attempt_id),
            )
            with self.journal.transaction() as tx:
                tx.update_attempt_status(
                    attempt_id=str(lead_attempt_id), status=AttemptStatus.BLOCKED
                )
                tx.update_task_status(
                    task_id=str(lead_task_id),
                    status=TaskStatus.BUDGET_BLOCKED if budget_blocked else TaskStatus.BLOCKED,
                )
                tx.update_run_status(run_id=str(run_id), status="blocked")
                tx.update_session_status(session_id=str(self.session_id), status="idle")
            self._emit_event(
                run_id=run_id,
                type="run.blocked",
                payload=LifecyclePayload(status="blocked"),
            )
            return RunResult(
                run_id=run_id,
                lead_assignment=None,
                lead_context_packet=lead_context_packet,
                output=describe_route_failure(assigned_lead),
                messages=(),
                status="blocked",
            )
        lead_assignment = assigned_lead

        # 4. Assemble and persist lead context packet BEFORE first model call
        lead_context_packet = self.assembler.assemble(
            task_id=str(run_id),
            objective=instruction,
            constraints=(),
            state=f"run_id={run_id}; assignment={lead_assignment.assignment_id}",
            references=self._compaction_references(),
        )
        self._persist_context_packet(
            lead_context_packet,
            run_id=run_id,
            task_id=str(lead_task_id),
            attempt_id=str(lead_attempt_id),
        )

        recorded_child_results: list[TaskResult] = []

        # 5. Build and execute the lead with the persisted assignment binding.
        lead_agent = self._build_lead_for_run(
            run_id=run_id,
            controls=active_controls,
            workspace_revision=workspace_revision,
            delegation_approved=delegation_approved,
            recorded_child_results=recorded_child_results,
            leases=leases,
            gate=gate,
            scheduler=scheduler,
            saver=saver,
            lead_assignment=lead_assignment,
            lead_task_id=lead_task_id,
            lead_attempt_id=lead_attempt_id,
            lead_context_packet=lead_context_packet,
        )

        input_message = HumanMessage(content=instruction)
        invoke_config: RunnableConfig = {
            "configurable": {"thread_id": self._checkpoint_thread_id(run_id)}
        }
        try:
            result_state = cast(
                dict[str, Any],
                await lead_agent.ainvoke(
                    {
                        "messages": [input_message],
                        "attempt_id": str(lead_attempt_id),
                    },
                    config=invoke_config,
                ),
            )
        except BaseException as exc:
            error_type: str | None = None
            error_message: str | None = None
            is_cancelled = isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError))
            try:
                error_type = f"{type(exc).__module__}.{type(exc).__name__}"
                error_message = str(self.redactor.scrub(str(exc)))
                if is_cancelled:
                    _LOGGER.info("run cancelled: %s", run_id)
                else:
                    failure_traceback = self.redactor.scrub(traceback.format_exc())
                    _LOGGER.error(
                        "run failed: %s: %s\n%s",
                        error_type,
                        error_message,
                        failure_traceback,
                    )
                    if _is_message_sequence_error(exc):
                        shapes = await _collect_message_sequence_diagnostics(
                            lead_agent, invoke_config
                        )
                        _LOGGER.error("run failed diagnostics: %s", shapes)
            except Exception:
                pass  # diagnostics must never mask or replace the original failure
            run_status = "cancelled" if is_cancelled else "failed"
            attempt_status = AttemptStatus.INTERRUPTED if is_cancelled else AttemptStatus.FAILED
            task_status = TaskStatus.RETURNED_TO_LEAD if is_cancelled else TaskStatus.FAILED
            terminal_type = "run.cancelled" if is_cancelled else "run.failed"
            with self.journal.transaction() as tx:
                tx.update_attempt_status(attempt_id=str(lead_attempt_id), status=attempt_status)
                tx.update_task_status(task_id=str(lead_task_id), status=task_status)
                tx.update_run_status(run_id=str(run_id), status=run_status)
                tx.update_session_status(session_id=str(self.session_id), status="idle")
                self._append_event(
                    tx,
                    run_id=run_id,
                    type=terminal_type,
                    payload=LifecyclePayload(
                        status=run_status,
                        error_type=error_type,
                        error_message=error_message,
                    ),
                )
                self._reconcile_unlaunched_admissions()
            await _save_checkpoint(
                "terminal_cancelled" if is_cancelled else "terminal_failed",
                status="committed",
            )
            self._finalize_child_budgets(run_id, lead_task_id)
            self._finalize_assignment_budget(lead_assignment)
            self._release_lead_allowances()
            raise

        messages = cast(list[BaseMessage], result_state.get("messages", []))

        output_text = ""
        output_content: Any = None
        for message in reversed(messages):
            if isinstance(message, AIMessage) and message.content:
                output_content = self.redactor.scrub(message.content)
                output_text = model_content_to_text(output_content)
                break

        is_interrupted = bool(result_state.get("__interrupt__"))
        if is_interrupted:
            pending_interrupt = _first_interrupt_payload(result_state)
            self._pending_interrupt_payload = pending_interrupt
            self._pending_run = _PendingRun(
                run_id=run_id,
                instruction=instruction,
                controls=active_controls,
                workspace_revision=workspace_revision,
                delegation_approved=delegation_approved,
                lead_task_id=lead_task_id,
                lead_attempt_id=lead_attempt_id,
                lead_assignment=lead_assignment,
                lead_context_packet=lead_context_packet,
                checkpoint_thread_id=self._checkpoint_thread_id(run_id),
            )
            with self.journal.transaction() as tx:
                tx.update_attempt_status(
                    attempt_id=str(lead_attempt_id), status=AttemptStatus.RUNNING
                )
                tx.update_task_status(task_id=str(lead_task_id), status=TaskStatus.RUNNING)
                tx.update_run_status(run_id=str(run_id), status="blocked")
                tx.update_session_status(session_id=str(self.session_id), status="interrupted")
                if pending_interrupt is not None and pending_interrupt.get("kind") == "question":
                    raw_options = pending_interrupt.get("options", ())
                    options = (
                        tuple(option for option in raw_options if isinstance(option, str))
                        if isinstance(raw_options, (list, tuple))
                        else ()
                    )
                    self._append_event(
                        tx,
                        run_id=run_id,
                        type="user.question",
                        payload=UserPayload(
                            action="question",
                            kind=InterruptKind.QUESTION,
                            interrupt_id=str(pending_interrupt.get("question_id", "")),
                            content=str(pending_interrupt.get("prompt", "Question")),
                            options=options,
                            reason=str(pending_interrupt.get("reason", "")),
                            blocking_scope=str(
                                pending_interrupt.get("blocking_scope", "task")
                            ),
                        ),
                        task_id=lead_task_id,
                        attempt_id=lead_attempt_id,
                    )
                self._reconcile_unlaunched_admissions()
            await _save_checkpoint(
                "interrupted",
                status="interrupted",
                live_idempotency_keys=(f"attempt:{lead_attempt_id}",),
                extra_payload={
                    "interrupt": pending_interrupt,
                    "runtime": {
                        "workspace": str(self.workspace.resolve()),
                        "workspace_revision": workspace_revision,
                        "delegation_approved": delegation_approved,
                        "controls": {
                            "delegation": active_controls.delegation,
                            "model": active_controls.model,
                            "profile": active_controls.profile,
                            "write_allowed": active_controls.write_allowed,
                            "max_children": active_controls.max_children,
                            "direct_only": active_controls.direct_only,
                            "required_agent_count": active_controls.required_agent_count,
                            "routing_mode": active_controls.routing_mode.value,
                            "risk": active_controls.risk.value,
                        },
                        "lead_allowance_ids": tuple(self._lead_allowance_ids),
                    },
                },
            )
            self._emit_event(
                run_id=run_id,
                type="run.blocked",
                payload=LifecyclePayload(status="blocked"),
            )
            return RunResult(
                run_id=run_id,
                lead_assignment=lead_assignment,
                lead_context_packet=lead_context_packet,
                output="",
                messages=messages,
                child_results=recorded_child_results,
                status="blocked",
                interrupted=True,
                child_wall_seconds=scheduler.gate.child_wall_seconds,
                child_peak_active=scheduler.gate.peak_active,
                child_count=len(scheduler.gate.completed),
                pending_interrupt=pending_interrupt,
            )

        try:
            checkpoint_state, checkpoint_blocked = await self._finalize_completion(
                run_id=run_id,
                workspace_revision=workspace_revision,
                leases=leases,
                gate=gate,
                scheduler=scheduler,
                controls=active_controls,
                delegation_approved=delegation_approved,
                lead_assignment=lead_assignment,
                lead_agent=lead_agent,
                lead_attempt_id=lead_attempt_id,
                invoke_config=invoke_config,
                recorded_child_results=recorded_child_results,
            )
        except BaseException as exc:
            cancelled = isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError))
            run_status = "cancelled" if cancelled else "failed"
            with self.journal.transaction() as tx:
                tx.update_attempt_status(
                    attempt_id=str(lead_attempt_id),
                    status=(AttemptStatus.INTERRUPTED if cancelled else AttemptStatus.FAILED),
                )
                tx.update_task_status(
                    task_id=str(lead_task_id),
                    status=(TaskStatus.RETURNED_TO_LEAD if cancelled else TaskStatus.FAILED),
                )
                tx.update_run_status(run_id=str(run_id), status=run_status)
                tx.update_session_status(session_id=str(self.session_id), status="idle")
                self._append_event(
                    tx,
                    run_id=run_id,
                    type="run.cancelled" if cancelled else "run.failed",
                    payload=LifecyclePayload(status=run_status),
                )
            self._finalize_child_budgets(run_id, lead_task_id)
            try:
                self._finalize_assignment_budget(lead_assignment)
            finally:
                self._release_lead_allowances()
            raise

        if checkpoint_state is not None:
            messages = cast(list[BaseMessage], checkpoint_state.get("messages", []))
            output_text = ""
            output_content = None
            for message in reversed(messages):
                if isinstance(message, AIMessage) and message.content:
                    output_content = self.redactor.scrub(message.content)
                    output_text = model_content_to_text(output_content)
                    break
        if checkpoint_blocked:
            if self._pending_interrupt_payload is not None:
                self._pending_run = _PendingRun(
                    run_id=run_id,
                    instruction=instruction,
                    controls=active_controls,
                    workspace_revision=workspace_revision,
                    delegation_approved=delegation_approved,
                    lead_task_id=lead_task_id,
                    lead_attempt_id=lead_attempt_id,
                    lead_assignment=lead_assignment,
                    lead_context_packet=lead_context_packet,
                )
                with self.journal.transaction() as tx:
                    tx.update_run_status(run_id=str(run_id), status="blocked")
                    tx.update_session_status(session_id=str(self.session_id), status="interrupted")
                    self._append_event(
                        tx,
                        run_id=run_id,
                        type="run.blocked",
                        payload=LifecyclePayload(status="blocked"),
                    )
                await _save_checkpoint(
                    "interrupted",
                    status="interrupted",
                    live_idempotency_keys=(f"attempt:{lead_attempt_id}",),
                    extra_payload={
                        "interrupt": self._pending_interrupt_payload,
                        "runtime": {
                            "workspace": str(self.workspace.resolve()),
                            "workspace_revision": workspace_revision,
                            "delegation_approved": delegation_approved,
                            "controls": {
                                "delegation": active_controls.delegation,
                                "model": active_controls.model,
                                "profile": active_controls.profile,
                                "write_allowed": active_controls.write_allowed,
                                "max_children": active_controls.max_children,
                                "direct_only": active_controls.direct_only,
                                "required_agent_count": active_controls.required_agent_count,
                                "routing_mode": active_controls.routing_mode.value,
                                "risk": active_controls.risk.value,
                            },
                            "lead_allowance_ids": tuple(self._lead_allowance_ids),
                        },
                    },
                )
                return RunResult(
                    run_id=run_id,
                    lead_assignment=lead_assignment,
                    lead_context_packet=lead_context_packet,
                    output="",
                    messages=messages,
                    child_results=recorded_child_results,
                    status="blocked",
                    interrupted=True,
                    pending_interrupt=self._pending_interrupt_payload,
                )
            with self.journal.transaction() as tx:
                tx.update_attempt_status(
                    attempt_id=str(lead_attempt_id), status=AttemptStatus.BLOCKED
                )
                tx.update_task_status(task_id=str(lead_task_id), status=TaskStatus.BLOCKED)
                tx.update_run_status(run_id=str(run_id), status="blocked")
                tx.update_session_status(session_id=str(self.session_id), status="idle")
                self._append_event(
                    tx,
                    run_id=run_id,
                    type="run.blocked",
                    payload=LifecyclePayload(status="blocked"),
                )
            self._finalize_assignment_budget(lead_assignment)
            self._release_lead_allowances()
            return RunResult(
                run_id=run_id,
                lead_assignment=lead_assignment,
                lead_context_packet=lead_context_packet,
                output=output_text,
                messages=messages,
                child_results=recorded_child_results,
                status="blocked",
                child_wall_seconds=scheduler.gate.child_wall_seconds,
                child_peak_active=scheduler.gate.peak_active,
                child_count=len(scheduler.gate.completed),
            )

        if self._gated_noop_requires_blocked(
            run_id=run_id, recorded_child_results=recorded_child_results
        ):
            output_text = (
                "Execution blocked: every operational tool call was rejected "
                "because no execution decision was recorded "
                "(execution.decision_required), and no work was performed."
            )
            with self.journal.transaction() as tx:
                tx.update_attempt_status(
                    attempt_id=str(lead_attempt_id), status=AttemptStatus.BLOCKED
                )
                tx.update_task_status(task_id=str(lead_task_id), status=TaskStatus.BLOCKED)
                tx.update_run_status(run_id=str(run_id), status="blocked")
                tx.update_session_status(session_id=str(self.session_id), status="idle")
                self._append_event(
                    tx,
                    run_id=run_id,
                    type="diagnostic.error",
                    payload=DiagnosticPayload(
                        code="execution.decision_required",
                        summary=output_text,
                        details={"run_id": str(run_id)},
                    ),
                    task_id=lead_task_id,
                    attempt_id=lead_attempt_id,
                )
                self._append_event(
                    tx,
                    run_id=run_id,
                    type="run.blocked",
                    payload=LifecyclePayload(status="blocked"),
                )
            self._finalize_assignment_budget(lead_assignment)
            self._release_lead_allowances()
            await _save_checkpoint("terminal", status="committed")
            return RunResult(
                run_id=run_id,
                lead_assignment=lead_assignment,
                lead_context_packet=lead_context_packet,
                output=output_text,
                messages=messages,
                child_results=recorded_child_results,
                status="blocked",
                child_wall_seconds=scheduler.gate.child_wall_seconds,
                child_peak_active=scheduler.gate.peak_active,
                child_count=len(scheduler.gate.completed),
            )

        with self.journal.transaction() as tx:
            tx.update_attempt_status(
                attempt_id=str(lead_attempt_id), status=AttemptStatus.SUCCEEDED
            )
            tx.update_task_status(task_id=str(lead_task_id), status=TaskStatus.SUCCEEDED)
            tx.update_run_status(run_id=str(run_id), status="completed")
            tx.update_session_status(session_id=str(self.session_id), status="idle")
            self._append_event(
                tx,
                run_id=run_id,
                type="run.completed",
                payload=LifecyclePayload(
                    status="completed",
                    output=structured_output_for_jsonl(output_content),
                ),
            )

        self._finalize_assignment_budget(lead_assignment)
        self._release_lead_allowances()

        await _save_checkpoint("terminal", status="committed")
        return RunResult(
            run_id=run_id,
            lead_assignment=lead_assignment,
            lead_context_packet=lead_context_packet,
            output=output_text,
            messages=messages,
            child_results=recorded_child_results,
            status="completed",
            interrupted=False,
            child_wall_seconds=scheduler.gate.child_wall_seconds,
            child_peak_active=scheduler.gate.peak_active,
            child_count=len(scheduler.gate.completed),
        )

    def restore_interrupted(self) -> bool:
        self.registry.load_from_journal(self.journal, str(self.session_id))
        snapshot = self.journal.get_session_snapshot(str(self.session_id))
        recoverable_runs = []
        for run in snapshot.runs:
            if run.status == "blocked":
                task_graph_ids = [
                    f"{self.session_id}:{run.run_id}:{task.task_id}"
                    for task in snapshot.tasks
                    if task.run_id == run.run_id
                ]
                graph_ids = [f"{self.session_id}:{run.run_id}:lead", *task_graph_ids]
                has_pending_question = self.question_store is not None and any(
                    self.question_store.pending(graph_id) for graph_id in graph_ids
                )
                if snapshot.status == "interrupted" or has_pending_question:
                    recoverable_runs.append(run)
                continue
            if run.status != "running":
                continue
            decision = self.journal.get_execution_decision(run.run_id)
            if decision is not None and decision.plan is not None:
                recoverable_runs.append(run)
        if not recoverable_runs:
            return False
        run = recoverable_runs[-1]
        self._resume_lead_on_recovery = run.status == "blocked"
        run_tasks = [task for task in snapshot.tasks if task.run_id == run.run_id]
        for task in run_tasks:
            attempt = next(
                (
                    item
                    for item in reversed(snapshot.attempts)
                    if item.task_id == task.task_id and item.status is AttemptStatus.RUNNING
                ),
                None,
            )
            if attempt is None:
                continue
            assignment = next(
                (
                    item
                    for item in reversed(snapshot.assignments)
                    if item.attempt_id == attempt.attempt_id
                ),
                None,
            )
            if assignment is None:
                continue
            persisted_assignment = TaskAssignment.model_validate(assignment.payload)
            packet_snapshot = next(
                (
                    item
                    for item in reversed(snapshot.context_packets)
                    if item.run_id == run.run_id and item.task_id == task.task_id
                ),
                None,
            )
            if packet_snapshot is None:
                packet = self.assembler.assemble(
                    task_id=run.run_id,
                    objective=task.description,
                    constraints=(),
                    state=f"run_id={run.run_id}; restored=true",
                )
            else:
                payload = packet_snapshot.payload
                packet = ContextPacket(
                    version=int(payload["version"]),
                    task_id=run.run_id,
                    components=tuple(
                        ContextComponent(**component) for component in payload.get("components", ())
                    ),
                    estimated_tokens=int(payload.get("estimated_tokens", 0)),
                    omissions=tuple(payload.get("omissions", ())),
                )
            checkpoint = (
                self.checkpoints.latest_valid(str(self.session_id))
                if self.checkpoints is not None
                else None
            )
            if (
                checkpoint is not None
                and checkpoint.payload.get("run_id") not in {None, run.run_id}
            ):
                raise RuntimeError("session.checkpoint_run_mismatch")
            runtime = (
                checkpoint.payload.get("runtime", {})
                if checkpoint is not None and isinstance(checkpoint.payload, Mapping)
                else {}
            )
            if not isinstance(runtime, Mapping):
                runtime = {}
            persisted_workspace = runtime.get("workspace")
            if (
                persisted_workspace
                and Path(str(persisted_workspace)).resolve() != self.workspace.resolve()
            ):
                raise RuntimeError("interrupted run belongs to a different workspace")
            control_data = runtime.get("controls", {})
            if not isinstance(control_data, Mapping):
                control_data = {}
            controls = LeadControls(
                model=(
                    str(control_data["model"])
                    if control_data.get("model") is not None
                    else (
                        f"{persisted_assignment.provider}:{persisted_assignment.model}"
                        if persisted_assignment.routing_mode is RoutingMode.MANUAL
                        else None
                    )
                ),
                delegation=cast(Any, control_data.get("delegation", "auto")),
                profile=cast(str | None, control_data.get("profile")),
                write_allowed=cast(bool | None, control_data.get("write_allowed")),
                max_children=int(control_data.get("max_children", 3)),
                direct_only=bool(control_data.get("direct_only", False)),
                required_agent_count=(
                    int(control_data["required_agent_count"])
                    if control_data.get("required_agent_count") is not None
                    else None
                ),
                routing_mode=RoutingMode(
                    str(control_data.get("routing_mode", persisted_assignment.routing_mode.value))
                ),
                risk=TaskRisk(str(control_data.get("risk", TaskRisk.ROUTINE.value))),
            )
            self._pending_run = _PendingRun(
                run_id=RunId(run.run_id),
                instruction=task.description,
                controls=controls,
                workspace_revision=str(runtime.get("workspace_revision", "git:head")),
                delegation_approved=bool(runtime.get("delegation_approved", False)),
                lead_task_id=TaskId(task.task_id),
                lead_attempt_id=AttemptId(attempt.attempt_id),
                lead_assignment=persisted_assignment,
                lead_context_packet=packet,
                checkpoint_thread_id=(
                    checkpoint.thread_id
                    if checkpoint is not None
                    else self._checkpoint_thread_id(RunId(run.run_id))
                ),
            )
            self._restored_decision = self.journal.get_execution_decision(run.run_id)
            allowance_ids = runtime.get("lead_allowance_ids", ())
            if isinstance(allowance_ids, (list, tuple)):
                self._lead_allowance_ids = [str(value) for value in allowance_ids]
            if self.checkpoints is not None:
                interrupt = None if checkpoint is None else checkpoint.payload.get("interrupt")
                self._pending_interrupt_payload = (
                    dict(interrupt) if isinstance(interrupt, Mapping) else None
                )
            if self._pending_interrupt_payload is None and self.question_store is not None:
                questions = self.question_store.pending(f"{self.session_id}:{run.run_id}:lead")
                if questions:
                    question = questions[-1]
                    self._pending_interrupt_payload = {
                        "question_id": question.question_id,
                        "prompt": question.prompt,
                        "options": question.options,
                        "reason": question.reason,
                        "task_id": question.task_id,
                        "blocking_scope": question.blocking_scope,
                    }
            return True
        return False

    def _reconcile_unlaunched_admissions(self) -> None:
        """Block admitted-but-unlaunched dispatches and forget them.

        Called inside the exiting journal transaction: the savepoint-nested
        writes join it, so the terminal statuses and this reconciliation commit
        atomically.  Only dispatches the dispatch pump never began — those
        without a persisted execution row — are swept to BLOCKED; mid-flight
        children (with an execution row) keep their state.  Nothing launches
        here, and resumes never re-admit these: only persisted READY nodes
        re-enter the admission path.
        """
        include = frozenset(
            dispatch.node_id
            for dispatch in self._planned_node_dispatches
            if self.journal.plan_node_execution(dispatch.node_id) is None
        )
        if not include:
            return
        self.journal.reconcile_plan_node_executions(include_node_ids=include)
        self._planned_node_dispatches.clear()

    def _rebuild_safe_resume_frontier(
        self,
        *,
        run_id: RunId,
        scheduler: ChildScheduler,
    ) -> None:
        """Reconstruct only persisted READY agent work after a crash/interrupt.

        LAUNCHING/RUNNING/settled/retired/ambiguous provider work is never
        replayed: ambiguous launches are reconciled to BLOCKED first, and only
        nodes still persisted as READY are re-admitted through the normal
        agent admission path (which rebuilds task/attempt/assignment records).
        Already-admitted LAUNCHING work from this resume is left untouched;
        only persisted READY nodes are (re-)admitted. Nodes that already have
        a persisted task binding or execution record are skipped individually
        so the normal LAUNCHING->RUNNING lifecycle is never re-entered from
        READY, while independent safe READY nodes still dispatch.

        Already-admitted LAUNCHING dispatches from this resume are excluded
        from reconciliation so fresh work is never blocked as ambiguous.
        """
        admitted_node_ids = frozenset(
            dispatch.node_id for dispatch in self._planned_node_dispatches
        )
        self.journal.reconcile_plan_node_executions(exclude_node_ids=admitted_node_ids)
        for persisted in self.journal.plans_for_run(str(run_id)):
            ready = self.journal.ready_plan_nodes(persisted.plan_id)
            if not ready:
                continue
            nodes = {node.local_id: node for node in persisted.plan.nodes}
            if not any(nodes[snapshot.local_id].kind is PlanNodeKind.AGENT for snapshot in ready):
                continue
            pending = self._pending_run
            if pending is None:
                continue
            self._admit_ready_plan_agents(
                persisted,
                run_id=run_id,
                controls=pending.controls,
                workspace_revision=pending.workspace_revision,
                lead_assignment=pending.lead_assignment,
                scheduler=scheduler,
            )

    async def resume_interrupted(self, answer: str) -> RunResult:
        pending = self._pending_run
        if pending is None:
            raise RuntimeError("no interrupted run is available to resume")
        if self.checkpoints is None:
            raise RuntimeError("interrupted run has no checkpoint store")

        interrupt = self._pending_interrupt_payload or {}
        if interrupt.get("type") == "plan_tool_approval":
            if self.approvals is None:
                raise RuntimeError("plan tool command has no approval store")
            self.journal.retry_approved_plan_tool(
                plan_id=str(interrupt["plan_id"]), node_id=str(interrupt["node_id"])
            )
            self._resume_lead_on_recovery = False
            self._pending_interrupt_payload = None

        leases = WorkspaceLeaseManager()
        max_children = min(max(pending.controls.max_children, 1), 3)
        gate = ChildRunGate(max_children)
        scheduler = ChildScheduler(max_children=max_children)
        child_results: list[TaskResult] = []
        invoke_config: RunnableConfig = {
            "configurable": {
                "thread_id": pending.checkpoint_thread_id
                or self._checkpoint_thread_id(pending.run_id)
            }
        }
        async with self.checkpoints.saver(str(self.session_id)) as saver:
            await saver.setup()
            restored = self._restored_decision
            if restored is None:
                restored = self.journal.get_execution_decision(str(pending.run_id))
                self._restored_decision = restored
            lead_agent = self._build_lead_for_run(
                run_id=pending.run_id,
                controls=pending.controls,
                workspace_revision=pending.workspace_revision,
                delegation_approved=pending.delegation_approved,
                recorded_child_results=child_results,
                leases=leases,
                gate=gate,
                scheduler=scheduler,
                saver=saver,
                lead_assignment=pending.lead_assignment,
                lead_task_id=pending.lead_task_id,
                lead_attempt_id=pending.lead_attempt_id,
                lead_context_packet=pending.lead_context_packet,
                restored_decision=restored,
            )
            try:
                result_state = (
                    cast(
                        dict[str, Any],
                        await resume_agent(lead_agent, answer, config=invoke_config),
                    )
                    if self._resume_lead_on_recovery
                    else {"messages": []}
                )
            except BaseException as exc:
                error_type: str | None = None
                error_message: str | None = None
                try:
                    error_type = f"{type(exc).__module__}.{type(exc).__name__}"
                    error_message = str(self.redactor.scrub(str(exc)))
                    failure_traceback = self.redactor.scrub(traceback.format_exc())
                    _LOGGER.error(
                        "run failed: %s: %s\n%s",
                        error_type,
                        error_message,
                        failure_traceback,
                    )
                    if _is_message_sequence_error(exc):
                        shapes = await _collect_message_sequence_diagnostics(
                            lead_agent, invoke_config
                        )
                        _LOGGER.error("run failed diagnostics: %s", shapes)
                except Exception:
                    pass  # diagnostics must never mask or replace the original failure
                cancelled = isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError))
                with self.journal.transaction() as tx:
                    tx.update_attempt_status(
                        attempt_id=str(pending.lead_attempt_id),
                        status=(AttemptStatus.INTERRUPTED if cancelled else AttemptStatus.FAILED),
                    )
                    tx.update_task_status(
                        task_id=str(pending.lead_task_id),
                        status=(TaskStatus.RETURNED_TO_LEAD if cancelled else TaskStatus.FAILED),
                    )
                    tx.update_run_status(
                        run_id=str(pending.run_id),
                        status="cancelled" if cancelled else "failed",
                    )
                    tx.update_session_status(session_id=str(self.session_id), status="idle")
                    self._append_event(
                        tx,
                        run_id=pending.run_id,
                        type="run.cancelled" if cancelled else "run.failed",
                        payload=LifecyclePayload(
                            status="cancelled" if cancelled else "failed",
                            error_type=error_type,
                            error_message=error_message,
                        ),
                    )
                self._finalize_child_budgets(pending.run_id, pending.lead_task_id)
                self._finalize_assignment_budget(pending.lead_assignment)
                self._release_lead_allowances()
                self._pending_run = None
                self._pending_interrupt_payload = None
                raise
            checkpoint = await saver.aget_tuple(invoke_config)
            if self._resume_lead_on_recovery and checkpoint is not None:
                checkpoint_id = checkpoint.config.get("configurable", {}).get("checkpoint_id")
                if checkpoint_id:
                    self.checkpoints.record(
                        session_id=str(self.session_id),
                        thread_id=str(invoke_config["configurable"]["thread_id"]),
                        checkpoint_id=checkpoint_id,
                        idempotency_key=f"run:{pending.run_id}:resumed",
                        status=(
                            "interrupted" if result_state.get("__interrupt__") else "committed"
                        ),
                        payload={"run_id": str(pending.run_id), "boundary": "resumed"},
                        created_at=datetime.now(UTC),
                        live_idempotency_keys=(f"attempt:{pending.lead_attempt_id}",),
                    )

        messages = cast(list[BaseMessage], result_state.get("messages", []))
        if result_state.get("__interrupt__"):
            self._pending_interrupt_payload = _first_interrupt_payload(result_state)
            self.journal.update_session_status(
                session_id=str(self.session_id), status="interrupted"
            )
            return RunResult(
                run_id=pending.run_id,
                lead_assignment=pending.lead_assignment,
                lead_context_packet=pending.lead_context_packet,
                output="",
                messages=messages,
                child_results=child_results,
                status="blocked",
                interrupted=True,
                child_wall_seconds=gate.child_wall_seconds,
                child_peak_active=gate.peak_active,
                child_count=len(gate.completed),
                pending_interrupt=_first_interrupt_payload(result_state),
            )

        # The resumed lead may have admitted fresh plan work above; rebuild any
        # persisted READY work from a pre-interrupt crash so both reach one
        # shared coordinator finalization path before terminal.
        self._rebuild_safe_resume_frontier(run_id=pending.run_id, scheduler=scheduler)
        checkpoint_state, checkpoint_blocked = await self._finalize_completion(
            run_id=pending.run_id,
            workspace_revision=pending.workspace_revision,
            leases=leases,
            gate=gate,
            scheduler=scheduler,
            controls=pending.controls,
            delegation_approved=pending.delegation_approved,
            lead_assignment=pending.lead_assignment,
            lead_agent=lead_agent,
            lead_attempt_id=pending.lead_attempt_id,
            invoke_config=invoke_config,
            recorded_child_results=child_results,
        )
        if checkpoint_state is not None:
            messages = cast(list[BaseMessage], checkpoint_state.get("messages", []))
        if checkpoint_blocked:
            with self.journal.transaction() as tx:
                tx.update_attempt_status(
                    attempt_id=str(pending.lead_attempt_id), status=AttemptStatus.BLOCKED
                )
                tx.update_task_status(task_id=str(pending.lead_task_id), status=TaskStatus.BLOCKED)
                tx.update_run_status(run_id=str(pending.run_id), status="blocked")
                tx.update_session_status(session_id=str(self.session_id), status="idle")
                self._append_event(
                    tx,
                    run_id=pending.run_id,
                    type="run.blocked",
                    payload=LifecyclePayload(status="blocked"),
                )
            self._finalize_assignment_budget(pending.lead_assignment)
            self._release_lead_allowances()
            self._pending_run = None
            self._pending_interrupt_payload = None
            output_text = ""
            for message in reversed(messages):
                if isinstance(message, AIMessage) and message.content:
                    output_text = model_content_to_text(self.redactor.scrub(message.content))
                    break
            return RunResult(
                run_id=pending.run_id,
                lead_assignment=pending.lead_assignment,
                lead_context_packet=pending.lead_context_packet,
                output=output_text,
                messages=messages,
                child_results=child_results,
                status="blocked",
                child_wall_seconds=gate.child_wall_seconds,
                child_peak_active=gate.peak_active,
                child_count=len(gate.completed),
            )

        output_text = ""
        output_content: Any = None
        for message in reversed(messages):
            if isinstance(message, AIMessage) and message.content:
                output_content = self.redactor.scrub(message.content)
                output_text = model_content_to_text(output_content)
                break
        with self.journal.transaction() as tx:
            tx.update_attempt_status(
                attempt_id=str(pending.lead_attempt_id), status=AttemptStatus.SUCCEEDED
            )
            tx.update_task_status(task_id=str(pending.lead_task_id), status=TaskStatus.SUCCEEDED)
            tx.update_run_status(run_id=str(pending.run_id), status="completed")
            tx.update_session_status(session_id=str(self.session_id), status="idle")
            self._append_event(
                tx,
                run_id=pending.run_id,
                type="run.completed",
                payload=LifecyclePayload(
                    status="completed",
                    output=structured_output_for_jsonl(output_content),
                ),
            )
        self.usage_settler.settle_attempt(str(pending.lead_assignment.assignment_id))
        self._release_lead_allowances()
        self._pending_run = None
        self._pending_interrupt_payload = None
        return RunResult(
            run_id=pending.run_id,
            lead_assignment=pending.lead_assignment,
            lead_context_packet=pending.lead_context_packet,
            output=output_text,
            messages=messages,
            child_results=child_results,
            status="completed",
            child_wall_seconds=gate.child_wall_seconds,
            child_peak_active=gate.peak_active,
            child_count=len(gate.completed),
        )

    def reject_interrupted(self) -> RunResult:
        pending = self._pending_run
        if pending is None:
            raise RuntimeError("no interrupted run is available to reject")
        interrupt = self._pending_interrupt_payload or {}
        with self.journal.transaction() as tx:
            tx.update_attempt_status(
                attempt_id=str(pending.lead_attempt_id), status=AttemptStatus.BLOCKED
            )
            tx.update_task_status(task_id=str(pending.lead_task_id), status=TaskStatus.BLOCKED)
            tx.update_run_status(run_id=str(pending.run_id), status="blocked")
            tx.update_session_status(session_id=str(self.session_id), status="idle")
        assignment_id = str(pending.lead_assignment.assignment_id)
        if self._has_calls(assignment_id):
            self.usage_settler.settle_attempt(assignment_id)
        else:
            self.ledger.release(str(pending.lead_assignment.reservation_id))
        self._release_lead_allowances()
        self._emit_event(
            run_id=pending.run_id,
            type="user.cancellation",
            payload=UserPayload(
                action="cancellation",
                kind=(
                    InterruptKind.QUESTION
                    if interrupt.get("kind") == "question"
                    else InterruptKind.APPROVAL
                ),
                interrupt_id=(
                    str(interrupt["question_id"])
                    if interrupt.get("question_id") is not None
                    else None
                ),
                content=(
                    "question cancelled"
                    if interrupt.get("kind") == "question"
                    else "approval rejected"
                ),
            ),
        )
        self._pending_run = None
        self._pending_interrupt_payload = None
        return RunResult(
            run_id=pending.run_id,
            lead_assignment=pending.lead_assignment,
            lead_context_packet=pending.lead_context_packet,
            output="",
            messages=(),
            status="blocked",
        )

    def _persist_context_packet(
        self,
        packet: ContextPacket,
        *,
        run_id: RunId,
        task_id: str | None,
        attempt_id: str | None,
    ) -> None:
        self.journal.create_context_packet(
            packet_id=packet.revision,
            run_id=str(run_id),
            task_id=task_id,
            attempt_id=attempt_id,
            payload={
                "version": packet.version,
                "objective": next(
                    (
                        component.content
                        for component in packet.components
                        if component.label == "objective"
                    ),
                    "",
                ),
                "estimated_tokens": packet.estimated_tokens,
                "omissions": list(packet.omissions),
                "components": [component.__dict__ for component in packet.components],
            },
            idempotency_key=f"context:{run_id}:{task_id or 'lead'}:{attempt_id or 'lead'}",
            created_at=datetime.now(UTC),
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
        model_call_budget: RunModelCallBudget,
    ) -> CompiledSubAgent:
        attempt_ids: dict[str, str] = {}

        def default_assign(
            spec: TaskSpec, number: int, excluded: tuple[tuple[str, str], ...]
        ) -> AttemptBinding | RouteFailure:
            if number == 1:
                planned = self._planned_assignments.pop(str(spec.task_id), None)
                if planned is not None:
                    if isinstance(planned, AttemptBinding):
                        attempt_ids[str(spec.task_id)] = str(planned.attempt_id)
                    return planned
            if self.child_assigner is not None:
                binding = self.child_assigner(spec, number, excluded)
                if isinstance(binding, AttemptBinding):
                    attempt_ids[str(spec.task_id)] = str(binding.attempt_id)
                return binding

            attempt_id = new_attempt_id()
            now = datetime.now(UTC)

            # Persist task in journal if first attempt
            if number == 1:
                self.journal.ensure_task(
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

            model_policy = spec.request.model_policy
            configured_model = self.fixed_profile_models.get(profile.name)
            if configured_model is None and number == 1:
                if model_policy is not None and model_policy.model is not None:
                    configured_model = (
                        f"{model_policy.provider}:{model_policy.model}"
                        if model_policy.provider
                        else model_policy.model
                    )
                elif profile.name in self.profile_models:
                    configured_model = self.profile_models[profile.name]
                elif controls.model:
                    configured_model = controls.model
                elif self.candidates_fn is None:
                    configured_model = self.default_child_model

            if configured_model and any(
                (p == "injected" or p == configured_model.split(":")[0])
                and (m == configured_model or m == configured_model.split(":")[-1])
                for p, m in excluded
            ):
                return RouteFailure(
                    binding_constraint="model_excluded",
                    excluded_counts={"excluded": len(excluded)},
                )

            escalated = number == 2
            req_mode = (
                RoutingMode.MANUAL
                if (configured_model and not escalated)
                else controls.routing_mode
            )
            reqs = self._requirements.for_assignment(
                spec.requirements,
                role=profile.role,
                risk=controls.risk,
                mode=req_mode,
                role_hard_min=profile.role_floor,
                escalated=escalated,
                excluded_models=frozenset(excluded),
            )

            manual_pin = None
            if req_mode is RoutingMode.MANUAL and configured_model:
                prov = "injected"
                m_name = configured_model
                if ":" in configured_model:
                    prov, m_name = configured_model.split(":", 1)
                manual_pin = (prov, m_name)

            child_config_snapshot = self._routing_config_snapshot(controls.routing_mode)
            request = AssignmentRequest(
                session_id=self.session_id,
                run_id=run_id,
                task_id=spec.task_id,
                attempt_id=attempt_id,
                attempt_number=cast(Literal[1, 2], number),
                catalog_revision=self.catalog_revision,
                requirements=reqs,
                config_snapshot=child_config_snapshot,
                manual_model=manual_pin,
                task_limit_usd=spec.request.budget_usd,
            )

            def child_candidates() -> RoutingSnapshot:
                packet = self.assembler.assemble(
                    task_id=str(spec.task_id),
                    objective=spec.request.description,
                    constraints=spec.request.success_criteria,
                    state=f"attempt={number}; assignment=pending",
                )
                snapshot = self._get_candidates(
                    for_lead=False,
                    target_lead_model=controls.model,
                    routing_mode=controls.routing_mode,
                )
                snapshot = self._estimate_snapshot(
                    snapshot,
                    packet=packet,
                    profile=profile,
                    minimum_output_tokens=reqs.minimum_output_tokens,
                )
                if model_policy is None or model_policy.provider is None:
                    return snapshot
                return snapshot.model_copy(
                    update={
                        "candidates": tuple(
                            candidate
                            for candidate in snapshot.candidates
                            if candidate.profile.provider == model_policy.provider
                        )
                    }
                )

            assignment = self.assignment_service.assign(
                request,
                child_candidates,
            )
            if isinstance(assignment, RouteFailure):
                self.journal.update_attempt_status(
                    attempt_id=str(attempt_id), status=AttemptStatus.FAILED
                )
                return assignment

            attempt_ids[str(spec.task_id)] = str(attempt_id)
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

            child_model_key = f"{assignment.provider}:{assignment.model}"
            child_chat_model = self._all_models.get(child_model_key)
            if child_chat_model is None:
                return TaskResult(
                    task_id=spec.task_id,
                    status="failed",
                    summary=f"child model {assignment.model} not found",
                )

            curr_attempt_id = attempt_ids.get(str(spec.task_id))
            assignments, active = self.persisted_registry.runtime_bindings()

            if curr_attempt_id and curr_attempt_id not in active:
                model_key = f"{assignment.provider}:{assignment.model}"
                assignments[str(assignment.assignment_id)] = model_key
                active[curr_attempt_id] = FallbackBinding(
                    assignment_id=str(assignment.assignment_id),
                    provider=assignment.provider,
                    model=assignment.model,
                    model_key=model_key,
                    reservation_id=str(assignment.reservation_id),
                )

            child_middleware = TaskBoundModelMiddleware(
                self._all_models,
                assignments=assignments,
                allow_delegation=False,
                providers=self.providers,
                usage_callback=self._record_model_usage,
                call_begin=self.usage_settler.begin_call,
                call_ambiguous=self.usage_settler.mark_ambiguous,
                active_assignments=active,
                redactor=self.redaction,
            )

            isolated_workspace = None
            child_workspace = self.workspace
            if profile.write_capable and self._workspace_snapshot is not None:
                try:
                    isolated_workspace = self.workspace_manager.materialize(
                        self._workspace_snapshot, str(spec.task_id)
                    )
                except ValueError as error:
                    return TaskResult(
                        task_id=spec.task_id,
                        status="blocked",
                        summary=str(error),
                    )
                child_workspace = isolated_workspace.path

            inner_agent = build_default_agent(
                child_chat_model,
                workspace=child_workspace,
                profile=profile.name,
                lease_manager=leases,
                task_id=str(spec.task_id),
                extra_middleware=[child_middleware],
                redactor=self.redaction,
                runtime_event=self._activity_emitter(
                    run_id=run_id,
                    task_id=spec.task_id,
                    attempt_id=AttemptId(curr_attempt_id),
                )
                if curr_attempt_id
                else None,
                runtime_model_name=assignment.model,
                model_call_guard=model_call_budget.begin_call,
                session_id=str(self.session_id),
                run_id=str(run_id),
                graph_id=f"{self.session_id}:{run_id}:{spec.task_id}",
                allowed_write_paths=spec.permission_set.allowed_paths,
                execute_allowed=(
                    spec.permission_set.execute
                    and not spec.permission_set.allowed_paths
                    and isolated_workspace is None
                ),
                forbidden_host_paths=(self.workspace,) if isolated_workspace is not None else (),
                state_dir=self.state_dir,
            )

            formatted_prompt = _format_context_packet(packet)

            invoke_state: dict[str, Any] = {
                "messages": [HumanMessage(content=formatted_prompt)],
            }
            if curr_attempt_id:
                invoke_state["attempt_id"] = curr_attempt_id

            try:
                result_state = cast(
                    dict[str, Any],
                    await inner_agent.ainvoke(invoke_state),
                )
                inner_messages = cast(list[BaseMessage], result_state.get("messages", []))
                child_output = ""
                for msg in reversed(inner_messages):
                    if isinstance(msg, AIMessage) and msg.content:
                        child_output = model_content_to_text(self.redactor.scrub(msg.content))
                        break
                result = parse_child_result(
                    child_output,
                    task_id=spec.task_id,
                    required_criteria=spec.request.success_criteria,
                    evidence_validator=lambda reference: self._validate_evidence_at(
                        reference, child_workspace
                    ),
                    model_authored_analysis=not profile.permissions.write,
                    source_validator=lambda reference: self._validate_source_at(
                        reference, child_workspace
                    ),
                )
                if isolated_workspace is not None and result.status == "succeeded":
                    if curr_attempt_id is None or self._workspace_snapshot is None:
                        raise WorkspaceCaptureError("workspace.capture_identity_missing")
                    artifacts = ImmutableArtifactStore(
                        self.journal.path.parent / "workspace-artifacts"
                    )
                    async with leases.acquire(f"integrate:{spec.task_id}"):
                        changeset = capture_managed_changeset(
                            changeset_id=str(uuid4()),
                            task_id=str(spec.task_id),
                            attempt_id=curr_attempt_id,
                            declared_scope=spec.permission_set.allowed_paths,
                            snapshot=self._workspace_snapshot,
                            workspace=isolated_workspace,
                            manager=self.workspace_manager,
                            scanner=StableWorktreeScanner(
                                max_files=10_000,
                                max_bytes=256 * 1024 * 1024,
                            ),
                            artifacts=artifacts,
                            journal=self.journal,
                        )
                        status = ChangeSetIntegrator(
                            journal=self.journal,
                            artifacts=artifacts,
                        ).integrate(changeset.changeset_id, self.workspace)
                    if status is not ChangeSetStatus.INTEGRATED:
                        result = TaskResult(
                            task_id=spec.task_id,
                            status="blocked",
                            summary=f"changeset.{status.value}",
                        )
                    else:
                        self.workspace_manager.cleanup_integrated(isolated_workspace)
                        isolated_workspace = None
            except WorkspaceCaptureError as error:
                result = TaskResult(task_id=spec.task_id, status="blocked", summary=str(error))
            finally:
                if isolated_workspace is not None:
                    self.workspace_manager.cleanup(isolated_workspace)
            recorded_child_results.append(result)
            return result

        def record_settle(binding: AttemptBinding, result: TaskResult) -> None:
            attempt_status = {
                "succeeded": AttemptStatus.SUCCEEDED,
                "failed": AttemptStatus.FAILED,
                "blocked": AttemptStatus.BLOCKED,
                "budget_blocked": AttemptStatus.BLOCKED,
                "cancelled": AttemptStatus.CANCELLED,
                "returned_to_lead": AttemptStatus.FAILED,
            }[result.status]
            task_status = {
                "succeeded": TaskStatus.SUCCEEDED,
                "failed": TaskStatus.FAILED,
                "blocked": TaskStatus.BLOCKED,
                "budget_blocked": TaskStatus.BUDGET_BLOCKED,
                "cancelled": TaskStatus.CANCELLED,
                "returned_to_lead": TaskStatus.RETURNED_TO_LEAD,
            }[result.status]
            with self.journal.transaction() as tx:
                tx.record_task_result(
                    task_id=str(result.task_id), payload=result.model_dump(mode="json")
                )
                tx.update_attempt_status(attempt_id=str(binding.attempt_id), status=attempt_status)
                tx.update_task_status(task_id=str(result.task_id), status=task_status)
                self._append_event(
                    tx,
                    run_id=run_id,
                    type=f"task.{result.status}",
                    payload=TaskPayload(status=result.status, profile=profile.name),
                    task_id=result.task_id,
                    attempt_id=AttemptId(str(binding.attempt_id)),
                )

            plan_node = self._plan_nodes_by_task.get(str(result.task_id))
            if plan_node is not None and (
                result.status != "failed" or binding.assignment.attempt_number == 2
            ):
                self._settle_plan_node(plan_node[0], plan_node[1], result.model_dump(mode="json"))

            self._finalize_assignment_budget(binding.assignment)

        def exhaust_fp(spec: TaskSpec) -> None:
            self.registry._failed_fingerprint_attempts[spec.fingerprint] = 2

        def emit_task(
            spec: TaskSpec, status: str, attempt_id: str | None, summary: str | None
        ) -> None:
            event_persisted = False
            plan_node = self._plan_nodes_by_task.get(str(spec.task_id))
            if plan_node is not None:
                plan_id, node_id = plan_node
                try:
                    persisted = self.journal.get_plan(plan_id)
                    local_id = next(
                        local for local, value in persisted.node_ids.items() if value == node_id
                    )
                    current = persisted.node_states[local_id]
                    if status == "started":
                        if current is PlanNodeState.LAUNCHING:
                            self.journal.transition_plan_node_state(
                                plan_id=plan_id,
                                node_id=node_id,
                                expected=PlanNodeState.LAUNCHING,
                                target=PlanNodeState.RUNNING,
                                event_observer=self.events.publish_persisted_nowait,
                            )
                    elif status in {"blocked", "budget_blocked"}:
                        if current in {PlanNodeState.LAUNCHING, PlanNodeState.RUNNING}:
                            self._settle_plan_node(plan_id, node_id, {"status": status})
                    elif status in {"succeeded", "cancelled", "returned_to_lead"}:
                        if current in {PlanNodeState.LAUNCHING, PlanNodeState.RUNNING}:
                            self._settle_plan_node(plan_id, node_id, {"status": status})
                except (KeyError, StopIteration):
                    # A concurrently settled or replaced node needs only the task lifecycle event.
                    event_persisted = False
            persisted_attempt_id = attempt_id
            if persisted_attempt_id is None and plan_node is not None:
                binding = self.journal.plan_node_task_binding(plan_node[1])
                persisted_attempt_id = None if binding is None else binding.attempt_id
            if status == "started" and persisted_attempt_id is not None:
                with self.journal.transaction() as tx:
                    tx.update_attempt_status(
                        attempt_id=persisted_attempt_id, status=AttemptStatus.RUNNING
                    )
                    tx.update_task_status(task_id=str(spec.task_id), status=TaskStatus.RUNNING)
                    self._append_event(
                        tx,
                        run_id=run_id,
                        type="task.started",
                        payload=TaskPayload(status="started", profile=profile.name),
                        task_id=spec.task_id,
                        attempt_id=AttemptId(persisted_attempt_id),
                    )
                event_persisted = True
            elif status in {"blocked", "budget_blocked"} and persisted_attempt_id is not None:
                result = TaskResult(
                    task_id=spec.task_id,
                    status=cast(Any, status),
                    summary=(
                        summary
                        if summary is not None
                        else (
                            "budget_unaffordable"
                            if status == "budget_blocked"
                            else "task blocked before execution"
                        )
                    ),
                )
                with self.journal.transaction() as tx:
                    tx.record_task_result(
                        task_id=str(spec.task_id), payload=result.model_dump(mode="json")
                    )
                    tx.update_attempt_status(
                        attempt_id=persisted_attempt_id, status=AttemptStatus.BLOCKED
                    )
                    tx.update_task_status(
                        task_id=str(spec.task_id),
                        status=(
                            TaskStatus.BUDGET_BLOCKED
                            if status == "budget_blocked"
                            else TaskStatus.BLOCKED
                        ),
                    )
                    self._append_event(
                        tx,
                        run_id=run_id,
                        type=f"task.{status}",
                        payload=TaskPayload(status=status, profile=profile.name, reason=summary),
                        task_id=spec.task_id,
                        attempt_id=AttemptId(persisted_attempt_id),
                    )
                event_persisted = True
            if not event_persisted and status not in {
                "succeeded",
                "failed",
                "cancelled",
                "returned_to_lead",
            }:
                self._emit_event(
                    run_id=run_id,
                    type=f"task.{status}",
                    payload=TaskPayload(status=status, profile=profile.name, reason=summary),
                    task_id=spec.task_id,
                    attempt_id=AttemptId(attempt_id) if attempt_id else None,
                )

        return build_compiled_profile_subagent(
            name=profile.name,
            description=profile.description,
            profile=profile,
            validator=self.validator,
            run_id=run_id,
            workspace_revision=workspace_revision,
            gate=gate,
            leases=leases,
            scheduler=scheduler,
            task_registry=self.registry,
            persist_context=lambda packet: self._persist_context_packet(
                packet,
                run_id=run_id,
                task_id=packet.task_id,
                attempt_id=attempt_ids.get(packet.task_id),
            ),
            assign=default_assign,
            execute=execute_child,
            settle_attempt=record_settle,
            persist_result=lambda result: self.journal.record_task_result(
                task_id=str(result.task_id),
                payload=result.model_dump(mode="json"),
            ),
            exhaust_fingerprint=exhaust_fp,
            task_event=emit_task,
            resolve_spec=self._resolve_planned_spec,
            require_preplanned=True,
            serialize_writers=self.workspace_selection.mode is not WorkspaceMode.WORKTREE,
        )


def _route_failure_for_task(result: BatchAssignmentResult, task_id: str) -> RouteFailure:
    """Resolve a task's recorded batch deferral; never fabricate a constraint."""
    for failure in result.failures:
        if str(failure.task_id) == task_id:
            return RouteFailure(
                excluded_counts=dict(failure.excluded_counts),
                binding_constraint=failure.binding_constraint,
            )
    return RouteFailure(excluded_counts={}, binding_constraint=None)


def _task_request_for_plan_node(node: PlanNode) -> TaskRequest:
    features = dict(node.task_features)
    allowed = {
        "profile",
        "write_scope",
        "model_policy",
        "budget_usd",
        "priority",
    }
    if set(features) - allowed:
        raise TaskValidationError("plan.task_features_invalid")
    default_profile = "explorer" if node.effect_scope is EffectScope.READ else "implementer"
    try:
        request = TaskRequest.model_validate(
            {
                **features,
                "description": node.objective,
                "profile": features.get("profile", default_profile),
                "success_criteria": node.acceptance_criteria,
                "prerequisite_artifacts": node.artifact_refs,
                "source_revisions": node.inputs,
                "attempt_lineage": node.task_lineage or node.local_id,
            }
        )
    except ValueError as error:
        raise TaskValidationError("plan.task_features_invalid") from error
    profile = builtin_profiles().get(request.profile)
    if profile is None:
        raise TaskValidationError("task.profile_unknown")
    if node.effect_scope is EffectScope.READ and profile.write_capable:
        raise TaskValidationError("plan.node_effect_profile_mismatch")
    if node.effect_scope is EffectScope.WORKSPACE_WRITE and not profile.write_capable:
        raise TaskValidationError("plan.node_effect_profile_mismatch")
    return request


def _validate_plan_tool_node(node: PlanNode) -> None:
    features = dict(node.task_features)
    if set(features) - {"tool", "command", "arguments", "priority"}:
        raise TaskValidationError("plan.tool_features_invalid")
    if features.get("tool") != "execute" or not isinstance(features.get("command"), str):
        raise TaskValidationError("plan.tool_unauthorized")
    arguments = features.get("arguments", ())
    if not isinstance(arguments, (list, tuple)) or not all(
        isinstance(item, str) for item in arguments
    ):
        raise TaskValidationError("plan.tool_features_invalid")


def _format_context_packet(packet: ContextPacket) -> str:
    component_text = "\n".join(
        f"{component.label}: {component.content}" for component in packet.components
    )
    omissions = ", ".join(packet.omissions) or "none"
    return (
        f"<context_packet revision='{packet.revision}' tokens='{packet.estimated_tokens}'>\n"
        f"{component_text}\n"
        f"omissions: {omissions}\n"
        "</context_packet>\n"
        "Return only a JSON object with status, summary, changed_paths, artifacts, and "
        "verification. Every success criterion must have a passed=true verification item "
        "with concrete evidence."
    )


def _first_interrupt_payload(state: Mapping[str, Any]) -> dict[str, Any] | None:
    interrupts = state.get("__interrupt__")
    if not isinstance(interrupts, (list, tuple)) or not interrupts:
        return None
    value = getattr(interrupts[0], "value", interrupts[0])
    return dict(value) if isinstance(value, Mapping) else {"prompt": str(value)}
