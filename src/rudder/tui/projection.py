from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from rudder.domain.events import EventEnvelope
from rudder.sessions.journal import SessionSnapshot


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


@dataclass
class FooterData:
    lead_model: str = "auto"
    active_mode: str = "direct"  # "direct", "discover", "planned"
    routing_mode: str = "auto"
    session_cost_usd: Decimal = Decimal("0.00")
    budget_limit_usd: Decimal | None = None
    context_tokens_estimated: int = 0
    active_agents_count: int = 0


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
        self.session_id = snapshot.session_id
        self.session_title = snapshot.title
        self.session_status = snapshot.status

        # 1. Budget and usage
        limit = None
        for run in snapshot.runs:
            if run.budget_limit_usd is not None:
                limit = run.budget_limit_usd
                break
        self.budget_item.hard_limit_usd = limit

        total_authoritative = Decimal("0.00")
        total_estimated = Decimal("0.00")
        total_unknown = Decimal("0.00")
        agent_costs: dict[str, Decimal] = {}

        for u in snapshot.usage_records:
            if u.authoritative:
                total_authoritative += u.amount_usd
            else:
                total_estimated += u.amount_usd
            if getattr(u, "unknown", False):
                total_unknown += u.amount_usd
            if u.task_id:
                agent_costs[u.task_id] = agent_costs.get(u.task_id, Decimal("0.00")) + u.amount_usd

        active_reservations = Decimal("0.00")
        for r in snapshot.budget_reservations:
            if r.status in ("active", "reserved"):
                active_reservations += r.amount_usd

        self.budget_item.authoritative_actual_usd = total_authoritative
        self.budget_item.estimated_actual_usd = total_estimated
        self.budget_item.reserved_usd = active_reservations
        self.budget_item.unknown_cost_usd = total_unknown
        self.budget_item.per_agent_costs = agent_costs
        if limit is not None:
            committed = total_authoritative + total_estimated + active_reservations + total_unknown
            remaining = limit - committed
            self.budget_item.available_usd = max(Decimal("0.00"), remaining)
            if limit > 0 and (total_authoritative / limit) >= Decimal("0.80"):
                self.budget_item.warning_state = True

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
                capability_floor=float(payload.get("capability_floor", 0.50)),
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
            if asg.estimated_cost_usd > Decimal("0.00") and total_estimated == Decimal("0.00"):
                total_estimated += asg.estimated_cost_usd

        if total_estimated > self.budget_item.estimated_actual_usd:
            self.budget_item.estimated_actual_usd = total_estimated

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
                )
                self.transcript_items.append(
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

        # 9. Footer
        context_tokens = 0
        if snapshot.context_packets:
            context_tokens = snapshot.context_packets[-1].payload.get("estimated_tokens", 0)

        default_route = RouteViewItem(
            "lead", 1, "auto", "fake", "auto", 0.7, Decimal("0"), ()
        )
        lead_model_name = self.route_items.get("lead", default_route).model
        self.footer_data = FooterData(
            lead_model=lead_model_name,
            active_mode=self.footer_data.active_mode,
            routing_mode="auto",
            session_cost_usd=total_authoritative,
            budget_limit_usd=limit,
            context_tokens_estimated=context_tokens,
            active_agents_count=active_count,
        )

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
            self.transcript_items.append(
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
            self.transcript_items.append(
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
            self.transcript_items.append(
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
            self.pending_interrupt = InterruptItem(
                approval_id=str(event.event_id),
                task_id=task_id_str,
                question=content or "Question",
                status="pending",
            )
            self.transcript_items.append(
                TranscriptItem(
                    id=str(event.event_id),
                    role="approval",
                    title="User Question",
                    content=content or "",
                    status="pending",
                    collapsed=False,
                    can_collapse=False,
                    task_id=task_id_str,
                )
            )

        elif ev_type == "user.answer":
            if self.pending_interrupt:
                self.pending_interrupt.status = "approved"
            content = getattr(event.payload, "content", "Answered")
            self.transcript_items.append(
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
                self.transcript_items.append(
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
                self.transcript_items.append(
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
                self.transcript_items.append(
                    TranscriptItem(
                        id=str(event.event_id),
                        role="task",
                        title=f"Plan Node {node_id_val or ''} ({st_val})",
                        content=f"Plan node state is {st_val}",
                        status=st_val,
                    )
                )
            elif ev_type == "plan.blocked":
                self.transcript_items.append(
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
            self.transcript_items.append(
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
            self.transcript_items.append(
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
            self.transcript_items.append(
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
                self.budget_item.authoritative_actual_usd += amount
            elif action == "warned":
                self.budget_item.warning_state = True
            elif action == "unknown":
                self.budget_item.unknown_cost_usd += amount

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
            self.footer_data.session_cost_usd = self.budget_item.authoritative_actual_usd

        # Recalculate active agent count
        self.footer_data.active_agents_count = sum(
            1 for item in self.agent_rail_items if item.status in ("queued", "running", "escalated")
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
