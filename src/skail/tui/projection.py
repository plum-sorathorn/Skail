"""Pure TUI projection: view-model reconstructed from snapshots and events.

Phase 3a: queue, child slots, receipts, plan/approval state, missions,
model immutability, unread counts, stable transcript IDs, budget helpers.
This module must stay Textual-free and Rich-free.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from skail.domain.events import EventEnvelope, InterruptKind
from skail.sessions.journal import SessionSnapshot

BUDGET_UNAVAILABLE_COPY = "Budget details are unavailable for this provider."

_FILLED_CELL = "■"
_EMPTY_CELL = "·"
_DEFAULT_METER_CELLS = 8

_VALID_PLAN_STATES = ("none", "proposed", "accepted", "rejected")
_VALID_APPROVAL_STATES = ("pending", "approved", "rejected")
_MAX_CHILD_SLOTS = 3


@dataclass
class TranscriptItem:
    id: str
    role: str  # "lead", "user", "task", "tool", "error", "approval", "system"
    title: str
    content: str
    status: str = "normal"
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    collapsed: bool = False
    can_collapse: bool = True
    task_id: str | None = None


@dataclass
class AgentRailItem:
    task_id: str
    task_id_suffix: str
    parent_task_id: str | None
    profile: str
    model: str
    # "queued", "running", "succeeded", "failed",
    # "returned_to_lead", "blocked", "cancelled", "escalated"
    status: str
    elapsed_sec: float = 0.0
    cost_authoritative_usd: Decimal = Decimal("0.00")
    cost_estimated_usd: Decimal = Decimal("0.00")
    depth: int = 1


@dataclass
class PlanNodeViewItem:
    node_id: str
    local_id: str
    objective: str
    kind: str  # "agent", "tool", "checkpoint"
    # "waiting", "ready", "launching", "running", "succeeded", "failed", "blocked", "cancelled"
    state: str
    depends_on: tuple[str, ...] = ()
    effect_scope: str = "read"
    task_id: str | None = None


@dataclass
class WorkspaceIntegrationItem:
    changeset_id: str
    task_id: str
    attempt_id: str
    status: str  # "captured", "applying", "in_doubt", "integrated", "blocked"
    base_head: str
    paths: tuple[str, ...] = ()
    error: str | None = None


@dataclass
class RouteViewItem:
    task_id: str
    attempt_number: int
    model: str
    provider: str
    routing_mode: str
    capability_floor: float
    estimated_cost_usd: Decimal
    explanation: tuple[str, ...]
    lineage: tuple[str, ...] = ()
    binding_constraint: str | None = None
    evidence_status: str | None = None
    evidence_revision: str | None = None
    shadow_recommendation: str | None = None
    shadow_reasons: tuple[str, ...] = ()


@dataclass
class BudgetViewItem:
    hard_limit_usd: Decimal | None = None
    authoritative_actual_usd: Decimal = Decimal("0.00")
    estimated_actual_usd: Decimal = Decimal("0.00")
    token_derived_actual_usd: Decimal = Decimal("0.00")
    conservative_estimate_usd: Decimal = Decimal("0.00")
    reserved_usd: Decimal = Decimal("0.00")
    unknown_cost_usd: Decimal = Decimal("0.00")
    available_usd: Decimal | None = None
    warning_state: bool = False
    lead_allowance_usd: Decimal | None = None
    per_agent_costs: dict[str, Decimal] = field(default_factory=dict)


@dataclass
class InterruptItem:
    approval_id: str
    task_id: str | None
    question: str
    status: str = "pending"  # "pending", "approved", "rejected"
    payload: dict[str, Any] = field(default_factory=dict)
    kind: InterruptKind = InterruptKind.APPROVAL


@dataclass
class FooterData:
    lead_model: str = "auto"
    active_mode: str = "direct"  # "direct", "discover", "planned"
    routing_mode: str = "auto"
    session_cost_usd: Decimal = Decimal("0.00")
    budget_limit_usd: Decimal | None = None
    context_tokens_estimated: int = 0
    active_agents_count: int = 0


@dataclass
class ChildView:
    """Mission row for the sidebar/missions view."""

    id: str
    slot: int
    status: str = "running"
    task: str = ""
    model: str = ""
    workspace_lock: str = ""
    last_event: str = ""
    cost: Decimal = Decimal("0.00")

    @property
    def task_id(self) -> str:
        return self.id

    def __getitem__(self, key: str) -> Any:
        if key == "task_id":
            return self.id
        return getattr(self, key)


class BudgetState(str):
    """State string equal to both spec and legacy display copies."""

    _ALIASES: dict[str, str] = {
        "normal": "normal",
        "near": "near",
        "near limit": "near",
        "near_limit": "near",
        "critical": "critical",
        "exceeded": "exceeded",
        "limit reached": "exceeded",
        "limit_reached": "exceeded",
    }

    @classmethod
    def _normalize(cls, value: object) -> str:
        text = str(value).strip().lower().replace("_", " ")
        text = " ".join(text.split())
        return cls._ALIASES.get(text, text)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self._normalize(self) == self._normalize(other)
        if isinstance(other, BudgetState):
            return self._normalize(self) == self._normalize(other)
        return False

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return hash(self._normalize(self))


@dataclass
class BudgetViewModel:
    cells: str = ""
    pct: float = 0.0
    state: BudgetState = field(default_factory=lambda: BudgetState("normal"))
    unavailable: bool = False
    copy: str = ""

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


def _ratio_to_state(ratio: float) -> BudgetState:
    if ratio >= 1.0:
        return BudgetState("exceeded")
    if ratio >= 0.90:
        return BudgetState("critical")
    if ratio >= 0.75:
        return BudgetState("near")
    return BudgetState("normal")


def budget_meter(
    used: float,
    limit: float | None = None,
    cells: int = _DEFAULT_METER_CELLS,
) -> str:
    """Render an 8-cell meter of filled/empty cells.

    Accepts either a ratio (single arg) or used/limit pair.
    """
    if limit is None:
        ratio = float(used)
    elif limit <= 0:
        ratio = 0.0 if float(used) <= 0 else 1.0
    else:
        ratio = float(used) / float(limit)
    if ratio != ratio:  # NaN guard
        ratio = 0.0
    ratio = min(1.0, max(0.0, ratio))
    filled = int(ratio * cells)
    filled = min(cells, max(0, filled))
    return _FILLED_CELL * filled + _EMPTY_CELL * (cells - filled)


def _ratio_from_item(
    item: BudgetViewItem | None,
    used_ratio: float | None,
) -> float:
    if used_ratio is not None:
        return float(used_ratio)
    if item is None or item.hard_limit_usd is None:
        return 0.0
    limit = float(item.hard_limit_usd)
    if limit <= 0:
        return 0.0
    committed = (
        float(item.authoritative_actual_usd)
        + float(item.estimated_actual_usd)
        + float(item.reserved_usd)
        + float(item.unknown_cost_usd)
    )
    return committed / limit


def budget_view_model(
    used: BudgetViewItem | float | None = None,
    limit: float | None = None,
    *,
    used_ratio: float | None = None,
    cells: int = _DEFAULT_METER_CELLS,
) -> BudgetViewModel:
    """Build a budget view-model for either calling convention.

    New: budget_view_model(used, limit) -> {cells, pct, state}.
    Legacy: budget_view_model(BudgetViewItem | None, used_ratio=...).
    """
    if isinstance(used, BudgetViewItem) or used is None and (
        used_ratio is not None or limit is None
    ):
        item = used if isinstance(used, BudgetViewItem) else None
        if item is None and used_ratio is None and limit is None:
            # budget_view_model(None) -> unavailable
            if used is None:
                return BudgetViewModel(
                    cells=_EMPTY_CELL * cells,
                    pct=0.0,
                    state=BudgetState("normal"),
                    unavailable=True,
                    copy=BUDGET_UNAVAILABLE_COPY,
                )
        # Legacy item path (item may be None with used_ratio given).
        ratio = _ratio_from_item(item, used_ratio)
        state = _ratio_to_state(ratio)
        meter = budget_meter(ratio, None, cells)
        return BudgetViewModel(
            cells=meter,
            pct=ratio * 100.0,
            state=state,
            unavailable=False,
            copy="",
        )
    # Numeric path: used is float, limit optional.
    used_val = float(used) if used is not None else 0.0
    if used_ratio is not None:
        ratio = float(used_ratio)
    elif limit is None:
        ratio = used_val
    elif limit <= 0:
        ratio = 0.0 if used_val <= 0 else 1.0
    else:
        ratio = used_val / float(limit)
    ratio = min(2.0, max(0.0, ratio)) if ratio == ratio else 0.0
    state = _ratio_to_state(ratio)
    meter = budget_meter(ratio, None, cells)
    return BudgetViewModel(
        cells=meter,
        pct=ratio * 100.0,
        state=state,
        unavailable=False,
        copy="",
    )


def queue_followup(queue: list[str], text: str) -> list[str]:
    """Append a follow-up prompt to a FIFO queue (pure helper)."""
    queue.append(text)
    return queue


def take_back_newest(queue: list[str]) -> tuple[list[str], str | None]:
    """Remove and return the newest queued prompt (pure helper)."""
    if not queue:
        return ([], None)
    newest = queue[-1]
    return (list(queue[:-1]), newest)


class TuiProjection:
    """Pure projection reconstructing UI state from snapshots and event streams."""

    def __init__(self) -> None:
        self.session_id: str = ""
        self.session_title: str = ""
        self.session_status: str = "active"
        self.transcript_items: list[TranscriptItem] = []
        self.agent_rail_items: list[AgentRailItem] = []
        self.route_items: dict[str, RouteViewItem] = {}  # keyed by task_id
        self.plan_items: dict[str, PlanNodeViewItem] = {}  # keyed by local_id
        self.current_plan_id: str | None = None
        self.current_plan_revision: int = 1
        # keyed by changeset_id
        self.workspace_integrations: dict[str, WorkspaceIntegrationItem] = {}
        self.budget_item: BudgetViewItem = BudgetViewItem()
        self.pending_interrupt: InterruptItem | None = None
        self.footer_data: FooterData = FooterData()
        self.focused_agent_id: str | None = None
        self._seen_event_ids: set[str] = set()
        self._seen_transcript_ids: set[str] = set()
        # Phase 3a pure-data fields.
        self.queue: list[str] = []
        self.child_slots: dict[str, int] = {}
        self.receipts: list[str] = []
        self.plan_state: str = "none"
        self.approvals: dict[str, str] = {}
        self._children: dict[str, ChildView] = {}
        self.attempt_models: dict[str, str] = {}
        self._future_model: str = "auto"
        self.unread: int = 0

    # -- Phase 3a helpers -------------------------------------------------
    def queue_followup(self, text: str) -> None:
        self.queue.append(text)

    def take_back_newest(self) -> str | None:
        if not self.queue:
            return None
        return self.queue.pop()

    def child_slot_for(self, child_id: str) -> int:
        if child_id in self.child_slots:
            return self.child_slots[child_id]
        used = set(self.child_slots.values())
        for slot in (1, 2, 3):
            if slot not in used:
                if len(self.child_slots) >= _MAX_CHILD_SLOTS:
                    break
                self.child_slots[child_id] = slot
                return slot
        # At capacity: deterministic fallback without growing the map.
        return 1

    def note_receipt(self, text: str) -> None:
        self.receipts.append(text)
        self.unread += 1

    def note_plan(self, state: str) -> None:
        normalized = state.strip().lower()
        if normalized not in _VALID_PLAN_STATES:
            raise ValueError(f"Invalid plan state: {state}")
        self.plan_state = normalized

    def mark_approval(self, approval_id: str, decision: str) -> None:
        normalized = decision.strip().lower()
        if normalized not in _VALID_APPROVAL_STATES:
            raise ValueError(f"Invalid approval decision: {decision}")
        self.approvals[approval_id] = normalized
        if self.pending_interrupt is not None and (
            self.pending_interrupt.approval_id == approval_id
        ):
            self.pending_interrupt.status = normalized

    def note_child(
        self,
        child_id: str,
        task: str = "",
        model: str = "",
        workspace_lock: str = "",
    ) -> int:
        slot = self.child_slot_for(child_id)
        existing = self._children.get(child_id)
        if existing is not None:
            if task:
                existing.task = task
            if model:
                existing.model = model
            if workspace_lock:
                existing.workspace_lock = workspace_lock
            return existing.slot
        self._children[child_id] = ChildView(
            id=child_id,
            slot=slot,
            status="running",
            task=task,
            model=model,
            workspace_lock=workspace_lock,
            last_event="started",
            cost=Decimal("0.00"),
        )
        return slot

    def mark_child_status(
        self,
        child_id: str,
        status: str,
        last_event: str | None = None,
    ) -> None:
        child = self._children.get(child_id)
        if child is None:
            slot = self.child_slot_for(child_id)
            child = ChildView(
                id=child_id,
                slot=slot,
                status=status,
                last_event=last_event or status,
            )
            self._children[child_id] = child
            return
        child.status = status
        child.last_event = last_event if last_event is not None else status

    def children_view(self) -> list[ChildView]:
        return sorted(self._children.values(), key=lambda c: (c.slot, c.id))

    def set_future_model(self, name: str) -> None:
        self._future_model = name
        self.footer_data.lead_model = name

    def model_for_future(self) -> str:
        return self._future_model

    def note_attempt_model(self, attempt_id: str, model: str) -> None:
        if attempt_id not in self.attempt_models:
            self.attempt_models[attempt_id] = model

    def model_for_attempt(self, attempt_id: str) -> str | None:
        return self.attempt_models.get(attempt_id)

    def mark_seen(self) -> None:
        self.unread = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize UI state without any secret material."""

        def _safe(value: Any) -> Any:
            if isinstance(value, Decimal):
                return str(value)
            if isinstance(value, datetime):
                return value.isoformat()
            if isinstance(value, dict):
                return {str(k): _safe(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [_safe(v) for v in value]
            return value

        raw: dict[str, Any] = {
            "session_id": self.session_id,
            "session_title": self.session_title,
            "session_status": self.session_status,
            "queue": list(self.queue),
            "child_slots": dict(self.child_slots),
            "receipts": list(self.receipts),
            "plan_state": self.plan_state,
            "approvals": dict(self.approvals),
            "children": [asdict(c) for c in self.children_view()],
            "attempt_models": dict(self.attempt_models),
            "future_model": self._future_model,
            "unread": self.unread,
            "transcript": [asdict(t) for t in self.transcript_items],
        }
        cleaned: dict[str, Any] = _safe(raw)
        return cleaned

    def _add_transcript_item(self, item: TranscriptItem) -> bool:
        if not item.id:
            item.id = f"tx-{uuid.uuid4().hex[:12]}"
        if item.id in self._seen_transcript_ids:
            return False
        self._seen_transcript_ids.add(item.id)
        self.transcript_items.append(item)
        self.unread += 1
        return True

    def apply_budget_snapshot(self, snapshot: SessionSnapshot) -> None:
        """Refresh current-run budget state without rebuilding the transcript."""
        current_run = snapshot.runs[-1] if snapshot.runs else None
        current_run_id = current_run.run_id if current_run is not None else ""

        def belongs_to_current_run(item: object) -> bool:
            item_run_id = str(getattr(item, "run_id", ""))
            return not current_run_id or not item_run_id or item_run_id == current_run_id

        budget = BudgetViewItem(
            hard_limit_usd=(
                current_run.budget_limit_usd if current_run is not None else None
            )
        )
        for usage in snapshot.usage_records:
            if not belongs_to_current_run(usage):
                continue
            authority = usage.authority
            if usage.authoritative or authority == "authoritative_actual":
                budget.authoritative_actual_usd += usage.amount_usd
            elif authority == "token_derived_estimate":
                budget.token_derived_actual_usd += usage.amount_usd
                budget.estimated_actual_usd += usage.amount_usd
            elif authority == "conservative_estimate":
                budget.conservative_estimate_usd += usage.amount_usd
                budget.estimated_actual_usd += usage.amount_usd
            elif authority == "unknown":
                budget.unknown_cost_usd += usage.amount_usd
            else:
                budget.estimated_actual_usd += usage.amount_usd
            if usage.task_id:
                budget.per_agent_costs[usage.task_id] = (
                    budget.per_agent_costs.get(usage.task_id, Decimal("0.00"))
                    + usage.amount_usd
                )

        for reservation in snapshot.budget_reservations:
            if belongs_to_current_run(reservation) and reservation.status in (
                "active",
                "reserved",
            ):
                budget.reserved_usd += reservation.amount_usd

        incurred = (
            budget.authoritative_actual_usd
            + budget.estimated_actual_usd
            + budget.unknown_cost_usd
        )
        committed = incurred + budget.reserved_usd
        if budget.hard_limit_usd is not None:
            budget.available_usd = max(
                Decimal("0.00"), budget.hard_limit_usd - committed
            )
            budget.warning_state = bool(
                budget.hard_limit_usd > 0
                and committed / budget.hard_limit_usd >= Decimal("0.80")
            )

        self.budget_item = budget
        self.footer_data.session_cost_usd = sum(
            (usage.amount_usd for usage in snapshot.usage_records), Decimal("0")
        )
        self.footer_data.budget_limit_usd = budget.hard_limit_usd

    def apply_snapshot(self, snapshot: SessionSnapshot) -> None:
        self.transcript_items = []
        self.agent_rail_items = []
        self.route_items = {}
        self.plan_items = {}
        self.current_plan_id = None
        self.current_plan_revision = 1
        self.workspace_integrations = {}
        self.budget_item = BudgetViewItem()
        self.pending_interrupt = None
        self.footer_data = FooterData()
        self._seen_event_ids = set()
        self._seen_transcript_ids = set()
        self.session_id = snapshot.session_id
        self.session_title = snapshot.title
        self.session_status = snapshot.status

        # 1. Budget and usage
        self.apply_budget_snapshot(snapshot)
        agent_costs = self.budget_item.per_agent_costs

        # 2. Routes from assignments
        attempts_by_task: dict[str, list[Any]] = {}
        for a in snapshot.attempts:
            attempts_by_task.setdefault(a.task_id, []).append(a)

        for asg in snapshot.assignments:
            # find matching attempt
            matching_attempt = next(
                (a for a in snapshot.attempts if a.attempt_id == asg.attempt_id),
                None,
            )
            task_id = matching_attempt.task_id if matching_attempt else asg.attempt_id
            attempt_num = matching_attempt.number if matching_attempt else 1

            payload = asg.payload or {}
            raw_expl = payload.get("explanation", ())
            expl = tuple(raw_expl) if isinstance(raw_expl, list) else (str(raw_expl),)
            capability_floor = payload.get("capability_floor")
            raw_lineage = payload.get("lineage")
            lineage = tuple(raw_lineage) if isinstance(raw_lineage, list) else ()
            evidence_status = payload.get("evidence_status")
            evidence_revision = payload.get("evidence_revision")
            shadow_rec = payload.get("shadow_recommendation")
            raw_shadow_reasons = payload.get("shadow_reasons", ())
            shadow_reasons = (
                tuple(raw_shadow_reasons)
                if isinstance(raw_shadow_reasons, list)
                else (str(raw_shadow_reasons),) if raw_shadow_reasons else ()
            )

            route_item = RouteViewItem(
                task_id=task_id,
                attempt_number=attempt_num,
                model=asg.model,
                provider=asg.provider,
                routing_mode=payload.get("routing_mode", "auto"),
                capability_floor=(
                    0.50 if capability_floor is None else float(capability_floor)
                ),
                estimated_cost_usd=asg.estimated_cost_usd,
                explanation=expl,
                lineage=lineage,
                binding_constraint=payload.get("binding_constraint"),
                evidence_status=evidence_status,
                evidence_revision=evidence_revision,
                shadow_recommendation=shadow_rec,
                shadow_reasons=shadow_reasons,
            )
            self.route_items[task_id] = route_item

        # 3. Agent rail items from tasks
        rail_items: list[AgentRailItem] = []
        active_count = 0
        for t in snapshot.tasks:
            status_val = t.status.value
            if status_val in ("queued", "running"):
                active_count += 1
            asg_item = self.route_items.get(t.task_id)
            model_name = asg_item.model if asg_item else "unassigned"
            cost_auth = agent_costs.get(t.task_id, Decimal("0.00"))
            cost_est = asg_item.estimated_cost_usd if asg_item else Decimal("0.00")

            # Check if escalated
            task_attempts = attempts_by_task.get(t.task_id, [])
            display_status = status_val
            if len(task_attempts) > 1 and status_val == "running":
                display_status = "escalated"

            rail_item = AgentRailItem(
                task_id=t.task_id,
                task_id_suffix=t.task_id[-8:] if len(t.task_id) >= 8 else t.task_id,
                parent_task_id=None,
                profile="implementer",
                model=model_name,
                status=display_status,
                cost_authoritative_usd=cost_auth,
                cost_estimated_usd=cost_est,
            )
            rail_items.append(rail_item)

        self.agent_rail_items = rail_items

        # 4. Approvals / Interrupts
        for ap in snapshot.approvals:
            if ap.status == "pending":
                self.pending_interrupt = InterruptItem(
                    approval_id=ap.approval_id,
                    task_id=ap.task_id,
                    question=ap.question,
                    status="pending",
                    kind=InterruptKind.APPROVAL,
                )
                self._add_transcript_item(
                    TranscriptItem(
                        id=f"app-{ap.approval_id}",
                        role="approval",
                        title=f"Approval Required: {ap.approval_id}",
                        content=ap.question,
                        status="pending",
                        can_collapse=False,
                        collapsed=False,
                        task_id=ap.task_id,
                    )
                )

        # 5. Plans
        if getattr(snapshot, "plans", None):
            for persisted_plan in snapshot.plans:
                self.current_plan_id = persisted_plan.plan_id
                self.current_plan_revision = persisted_plan.plan.revision
                for node in persisted_plan.plan.nodes:
                    st = persisted_plan.node_states.get(node.local_id)
                    st_val = (
                        st.value
                        if st is not None and hasattr(st, "value")
                        else str(st or "waiting")
                    )
                    nid = persisted_plan.node_ids.get(node.local_id, "")
                    kind_str = (
                        node.kind.value if hasattr(node.kind, "value") else str(node.kind)
                    )
                    scope_str = (
                        node.effect_scope.value
                        if hasattr(node.effect_scope, "value")
                        else str(node.effect_scope)
                    )
                    self.plan_items[node.local_id] = PlanNodeViewItem(
                        node_id=nid,
                        local_id=node.local_id,
                        objective=node.objective,
                        kind=kind_str,
                        state=st_val,
                        depends_on=tuple(node.depends_on),
                        effect_scope=scope_str,
                    )
                self.footer_data.active_mode = "planned"

        # 6. Changesets
        if getattr(snapshot, "changesets", None):
            for cs_item in snapshot.changesets:
                cs = cs_item.changeset
                cs_status = (
                    cs_item.status.value
                    if hasattr(cs_item.status, "value")
                    else str(cs_item.status)
                )
                self.workspace_integrations[cs.changeset_id] = WorkspaceIntegrationItem(
                    changeset_id=cs.changeset_id,
                    task_id=cs.task_id,
                    attempt_id=cs.attempt_id,
                    status=cs_status,
                    base_head=cs.base_head,
                    paths=tuple(p.path for p in cs.paths),
                )

        # 7. Execution Decisions
        if getattr(snapshot, "execution_decisions", None) and snapshot.execution_decisions:
            latest_dec = snapshot.execution_decisions[-1]
            mode_val = getattr(latest_dec, "mode", None)
            if mode_val:
                self.footer_data.active_mode = (
                    mode_val.value if hasattr(mode_val, "value") else str(mode_val)
                )

        # 8. Events into transcript
        for ev in snapshot.events:
            self.apply_event(ev)

        # Persisted ledger rows are authoritative; replayed budget events must
        # not apply the same reservation or charge a second time.
        self.apply_budget_snapshot(snapshot)

        # 9. Footer
        context_tokens = 0
        if snapshot.context_packets:
            context_tokens = snapshot.context_packets[-1].payload.get("estimated_tokens", 0)

        default_route = RouteViewItem(
            "lead", 1, "auto", "unassigned", "auto", 0.7, Decimal("0"), ()
        )
        lead_model_name = self.route_items.get("lead", default_route).model
        self.footer_data = FooterData(
            lead_model=self.footer_data.lead_model
            if self.footer_data.lead_model != "auto"
            else lead_model_name,
            active_mode=self.footer_data.active_mode,
            routing_mode="auto",
            session_cost_usd=sum(
                (usage.amount_usd for usage in snapshot.usage_records), Decimal("0")
            ),
            budget_limit_usd=self.budget_item.hard_limit_usd,
            context_tokens_estimated=context_tokens,
            active_agents_count=active_count,
        )
        # Preserve future model if it was customized before snapshot.
        if self._future_model != "auto":
            self.footer_data.lead_model = self._future_model

    def apply_event(self, event: EventEnvelope) -> None:
        event_id = str(event.event_id)
        if event_id in self._seen_event_ids:
            return
        self._seen_event_ids.add(event_id)
        ev_type = event.type
        task_id_str = str(event.task_id) if event.task_id else None

        if ev_type.startswith("task."):
            suffix = ev_type.split(".", 1)[1]
            # Update rail item if present
            if task_id_str:
                for item in self.agent_rail_items:
                    if item.task_id == task_id_str:
                        item.status = suffix
                        break
                else:
                    # New task
                    suffix_token = (
                        task_id_str[-8:] if len(task_id_str) >= 8 else task_id_str
                    )
                    self.agent_rail_items.append(
                        AgentRailItem(
                            task_id=task_id_str,
                            task_id_suffix=suffix_token,
                            parent_task_id=None,
                            profile=getattr(event.payload, "profile", "agent") or "agent",
                            model="unassigned",
                            status=suffix,
                        )
                    )

            # Add to transcript
            terminal_states = (
                "succeeded",
                "failed",
                "blocked",
                "cancelled",
                "returned_to_lead",
            )
            is_terminal = suffix in terminal_states
            is_error = suffix in ("failed", "blocked")
            self._add_transcript_item(
                TranscriptItem(
                    id=str(event.event_id),
                    role="task",
                    title=f"Task {ev_type} ({task_id_str or 'lead'})",
                    content=f"Status: {suffix}",
                    status=suffix,
                    collapsed=is_terminal and not is_error,
                    can_collapse=not is_error,
                    task_id=task_id_str,
                )
            )

        elif ev_type.startswith("tool."):
            tool_name = getattr(event.payload, "tool", "tool")
            status_val = getattr(event.payload, "status", "completed")
            is_error = status_val in ("failed", "rejected")
            self._add_transcript_item(
                TranscriptItem(
                    id=str(event.event_id),
                    role="error" if is_error else "tool",
                    title=f"Tool: {tool_name} ({status_val})",
                    content=f"Tool {tool_name} status is {status_val}",
                    status=status_val,
                    collapsed=not is_error,
                    can_collapse=not is_error,
                    task_id=task_id_str,
                )
            )

        elif ev_type in ("diagnostic.error", "invariant.failed"):
            summary = getattr(event.payload, "summary", "Diagnostic Error")
            code = getattr(event.payload, "code", "error")
            self._add_transcript_item(
                TranscriptItem(
                    id=str(event.event_id),
                    role="error",
                    title=f"Error [{code}]: {summary}",
                    content=str(getattr(event.payload, "details", {})),
                    status="error",
                    collapsed=False,
                    can_collapse=False,
                    task_id=task_id_str,
                )
            )

        elif ev_type == "user.question":
            content = getattr(event.payload, "content", "Pending user question")
            interrupt_id = getattr(event.payload, "interrupt_id", None) or str(event.event_id)
            options = getattr(event.payload, "options", ())
            self.pending_interrupt = InterruptItem(
                approval_id=str(interrupt_id),
                task_id=task_id_str,
                question=content or "Question",
                status="pending",
                payload={
                    "kind": InterruptKind.QUESTION.value,
                    "question_id": str(interrupt_id),
                    "prompt": content or "Question",
                    "options": tuple(options),
                    "reason": getattr(event.payload, "reason", None),
                    "blocking_scope": getattr(event.payload, "blocking_scope", None),
                    "session_id": str(event.session_id),
                    "run_id": str(event.run_id),
                    "plan_id": self.current_plan_id,
                },
                kind=InterruptKind.QUESTION,
            )
            self._add_transcript_item(
                TranscriptItem(
                    id=str(event.event_id),
                    role="question",
                    title="QUESTION · Your answer is needed",
                    content=content or "",
                    status="pending",
                    collapsed=False,
                    can_collapse=False,
                    task_id=task_id_str,
                )
            )

        elif ev_type == "user.answer":
            interrupt_id = getattr(event.payload, "interrupt_id", None)
            if (
                self.pending_interrupt is not None
                and self.pending_interrupt.kind is InterruptKind.QUESTION
                and (interrupt_id is None or self.pending_interrupt.approval_id == interrupt_id)
            ):
                self.pending_interrupt = None
            content = getattr(event.payload, "content", "Answered")
            self._add_transcript_item(
                TranscriptItem(
                    id=str(event.event_id),
                    role="user",
                    title="User Response",
                    content=content or "",
                    status="completed",
                    collapsed=False,
                    can_collapse=True,
                )
            )

        elif ev_type == "user.cancellation":
            interrupt_id = getattr(event.payload, "interrupt_id", None)
            is_question_cancellation = (
                getattr(event.payload, "kind", None) is InterruptKind.QUESTION
                or self.pending_interrupt is not None
                and self.pending_interrupt.kind is InterruptKind.QUESTION
            )
            if is_question_cancellation and (
                self.pending_interrupt is not None
                and (interrupt_id is None or self.pending_interrupt.approval_id == interrupt_id)
            ):
                self.pending_interrupt = None
            if is_question_cancellation:
                self._add_transcript_item(
                    TranscriptItem(
                        id=str(event.event_id),
                        role="system",
                        title="Question Cancelled",
                        content="The waiting run was cancelled.",
                        status="cancelled",
                        collapsed=False,
                        can_collapse=False,
                        task_id=task_id_str,
                    )
                )

        elif ev_type.startswith("plan."):
            suffix = ev_type.split(".", 1)[1]
            if ev_type == "plan.admitted":
                plan_id_val = getattr(event.payload, "plan_id", None)
                if plan_id_val:
                    self.current_plan_id = str(plan_id_val)
                rev_val = getattr(event.payload, "revision", None)
                if rev_val is not None:
                    self.current_plan_revision = int(rev_val)
                self.footer_data.active_mode = "planned"
                self._add_transcript_item(
                    TranscriptItem(
                        id=str(event.event_id),
                        role="system",
                        title=f"Plan Admitted (rev {self.current_plan_revision})",
                        content=f"Plan {self.current_plan_id or ''} admitted",
                        status="planned",
                    )
                )
            elif ev_type == "plan.revised":
                rev_val = getattr(event.payload, "revision", None)
                if rev_val is not None:
                    self.current_plan_revision = int(rev_val)
                self._add_transcript_item(
                    TranscriptItem(
                        id=str(event.event_id),
                        role="system",
                        title=f"Plan Revised (rev {self.current_plan_revision})",
                        content=f"Plan revised to revision {self.current_plan_revision}",
                        status="revised",
                    )
                )
            elif suffix.startswith("node_"):
                st_val = suffix.split("node_", 1)[1]
                node_id_val = getattr(event.payload, "node_id", None)
                if node_id_val:
                    for plan_item in self.plan_items.values():
                        if (
                            plan_item.node_id == str(node_id_val)
                            or plan_item.local_id == str(node_id_val)
                        ):
                            plan_item.state = st_val
                            break
                    else:
                        self.plan_items[str(node_id_val)] = PlanNodeViewItem(
                            node_id=str(node_id_val),
                            local_id=str(node_id_val),
                            objective=f"Node {node_id_val}",
                            kind="agent",
                            state=st_val,
                        )
                self._add_transcript_item(
                    TranscriptItem(
                        id=str(event.event_id),
                        role="task",
                        title=f"Plan Node {node_id_val or ''} ({st_val})",
                        content=f"Plan node state is {st_val}",
                        status=st_val,
                    )
                )
            elif ev_type == "plan.blocked":
                self._add_transcript_item(
                    TranscriptItem(
                        id=str(event.event_id),
                        role="error",
                        title="Plan Blocked",
                        content="Execution plan blocked",
                        status="blocked",
                    )
                )

        elif ev_type.startswith("route."):
            action_val = getattr(event.payload, "action", ev_type.split(".", 1)[1])
            asg_id = getattr(event.payload, "assignment_id", None)
            self._add_transcript_item(
                TranscriptItem(
                    id=str(event.event_id),
                    role="system" if action_val != "failed" else "error",
                    title=f"Route {action_val.capitalize()} ({task_id_str or 'lead'})",
                    content=f"Routing decision: {action_val} (assignment: {asg_id})",
                    status=action_val,
                    task_id=task_id_str,
                )
            )

        elif ev_type in ("decision.recorded", "execution.decision"):
            mode_val = getattr(event.payload, "mode", None)
            if mode_val:
                self.footer_data.active_mode = (
                    mode_val.value if hasattr(mode_val, "value") else str(mode_val)
                )
            self._add_transcript_item(
                TranscriptItem(
                    id=str(event.event_id),
                    role="system",
                    title=f"Execution Mode: {self.footer_data.active_mode}",
                    content=f"Execution decision recorded: mode={self.footer_data.active_mode}",
                    status="recorded",
                )
            )

        elif ev_type.startswith("changeset.") or ev_type.startswith("workspace."):
            action_val = ev_type.split(".", 1)[1]
            cs_id = str(getattr(event.payload, "changeset_id", task_id_str or str(event.event_id)))
            if cs_id in self.workspace_integrations:
                self.workspace_integrations[cs_id].status = action_val
            else:
                self.workspace_integrations[cs_id] = WorkspaceIntegrationItem(
                    changeset_id=cs_id,
                    task_id=task_id_str or "",
                    attempt_id="",
                    status=action_val,
                    base_head="",
                )
            self._add_transcript_item(
                TranscriptItem(
                    id=str(event.event_id),
                    role="task",
                    title=f"Workspace Integration ({action_val})",
                    content=f"Changeset {cs_id} status: {action_val}",
                    status=action_val,
                    task_id=task_id_str,
                )
            )

        elif ev_type.startswith("budget."):
            amount = getattr(event.payload, "amount_usd", Decimal("0.00"))
            action = getattr(event.payload, "action", "")
            if action == "reserved":
                self.budget_item.reserved_usd += amount
            elif action == "released":
                remaining_res = self.budget_item.reserved_usd - amount
                self.budget_item.reserved_usd = max(Decimal("0.00"), remaining_res)
            elif action == "charged":
                self.budget_item.estimated_actual_usd += amount
                self.footer_data.session_cost_usd += amount
            elif action == "warned":
                self.budget_item.warning_state = True
            elif action == "unknown":
                self.budget_item.unknown_cost_usd += amount
                self.footer_data.session_cost_usd += amount

            if self.budget_item.hard_limit_usd is not None:
                committed = (
                    self.budget_item.authoritative_actual_usd
                    + self.budget_item.estimated_actual_usd
                    + self.budget_item.reserved_usd
                    + self.budget_item.unknown_cost_usd
                )
                self.budget_item.available_usd = max(
                    Decimal("0.00"),
                    self.budget_item.hard_limit_usd - committed,
                )
        # Recalculate active agent count
        self.footer_data.active_agents_count = sum(
            1
            for item in self.agent_rail_items
            if item.status in ("queued", "started", "running", "escalated")
        )

    def toggle_collapse(self, item_id: str) -> bool:
        """Toggle collapsed state of an item if permitted. Returns new collapsed state."""
        for item in self.transcript_items:
            if item.id == item_id and item.can_collapse:
                item.collapsed = not item.collapsed
                return item.collapsed
        return False

    def focus_agent(self, task_id: str | None) -> None:
        self.focused_agent_id = task_id


__all__ = [
    "BUDGET_UNAVAILABLE_COPY",
    "AgentRailItem",
    "BudgetState",
    "BudgetViewItem",
    "BudgetViewModel",
    "ChildView",
    "FooterData",
    "InterruptItem",
    "PlanNodeViewItem",
    "RouteViewItem",
    "TranscriptItem",
    "TuiProjection",
    "WorkspaceIntegrationItem",
    "budget_meter",
    "budget_view_model",
    "queue_followup",
    "take_back_newest",
]
