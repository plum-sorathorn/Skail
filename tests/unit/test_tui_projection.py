from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from skail.domain.changesets import (
    ChangeSet,
    ChangeSetPath,
    ChangeSetStatus,
    ContentImage,
)
from skail.domain.events import (
    BudgetPayload,
    DiagnosticPayload,
    EventEnvelope,
    PlanPayload,
    TaskPayload,
    ToolPayload,
    UserPayload,
)
from skail.domain.ids import new_event_id, new_run_id, new_session_id, new_task_id
from skail.domain.plans import (
    EffectScope,
    ExecutionPlan,
    PlanNode,
    PlanNodeKind,
    PlanNodeState,
)
from skail.domain.sessions import SessionStatus
from skail.domain.tasks import AttemptStatus, TaskStatus
from skail.sessions.journal import (
    ApprovalSnapshot,
    AssignmentSnapshot,
    AttemptSnapshot,
    PersistedChangeSet,
    PersistedPlan,
    ReservationSnapshot,
    RunSnapshot,
    SessionSnapshot,
    TaskSnapshot,
    UsageSnapshot,
)
from skail.tui.projection import TuiProjection


def test_projection_initial_state() -> None:
    proj = TuiProjection()
    assert proj.session_id == ''
    assert proj.session_title == ''
    assert proj.session_status == 'active'
    assert proj.transcript_items == []
    assert proj.agent_rail_items == []
    assert proj.route_items == {}
    assert proj.budget_item.authoritative_actual_usd == Decimal('0.00')
    assert proj.pending_interrupt is None
    assert proj.focused_agent_id is None


def test_projection_apply_snapshot() -> None:
    now_iso = datetime.now(UTC).isoformat()
    sid = str(new_session_id())
    task_id = 'task-001'
    attempt_id = 'attempt-001'
    assignment_id = 'asg-001'

    snapshot = SessionSnapshot(
        session_id=sid,
        status=SessionStatus.ACTIVE.value,
        title='Test Build Session',
        created_at=now_iso,
        updated_at=now_iso,
        runs=(
            RunSnapshot(
                run_id='run-1',
                status='running',
                budget_limit_usd=Decimal('10.00'),
            ),
        ),
        tasks=(
            TaskSnapshot(
                task_id=task_id,
                run_id='run-1',
                description='Implement widget',
                status=TaskStatus.RUNNING,
                idempotency_key='k1',
            ),
        ),
        attempts=(
            AttemptSnapshot(
                attempt_id=attempt_id,
                task_id=task_id,
                number=1,
                status=AttemptStatus.RUNNING,
                idempotency_key='a1',
            ),
        ),
        assignments=(
            AssignmentSnapshot(
                assignment_id=assignment_id,
                attempt_id=attempt_id,
                provider='fake',
                model='fake:fast-model',
                estimated_cost_usd=Decimal('0.05'),
                payload={
                    'routing_mode': 'auto',
                    'capability_floor': 0.70,
                    'explanation': ['selected-by-policy'],
                    'lineage': ['lead-dispatch'],
                },
            ),
        ),
        usage_records=(
            UsageSnapshot(
                usage_id='u1',
                task_id=task_id,
                amount_usd=Decimal('0.03'),
                authoritative=True,
                idempotency_key='u1',
            ),
        ),
        budget_reservations=(
            ReservationSnapshot(
                reservation_id='res-1',
                task_id=task_id,
                amount_usd=Decimal('0.05'),
                status='active',
                idempotency_key='r1',
            ),
        ),
        approvals=(
            ApprovalSnapshot(
                approval_id='app-1',
                task_id=task_id,
                question='Allow rm -rf?',
                status='pending',
            ),
        ),
        context_packets=(),
        events=(),
    )

    proj = TuiProjection()
    proj.apply_snapshot(snapshot)

    assert proj.session_id == sid
    assert proj.session_title == 'Test Build Session'
    assert proj.budget_item.hard_limit_usd == Decimal('10.00')
    assert proj.budget_item.authoritative_actual_usd == Decimal('0.03')
    assert proj.budget_item.estimated_actual_usd == Decimal('0.00')
    assert proj.budget_item.reserved_usd == Decimal('0.05')
    assert proj.budget_item.available_usd == Decimal('9.92')
    assert proj.budget_item.per_agent_costs[task_id] == Decimal('0.03')
    assert proj.footer_data.session_cost_usd == Decimal('0.03')

    # Rail verification
    assert len(proj.agent_rail_items) == 1
    rail = proj.agent_rail_items[0]
    assert rail.task_id == task_id
    assert rail.model == 'fake:fast-model'
    assert rail.status == 'running'
    assert rail.cost_authoritative_usd == Decimal('0.03')
    assert rail.cost_estimated_usd == Decimal('0.05')

    # Route view verification
    assert task_id in proj.route_items
    route = proj.route_items[task_id]
    assert route.model == 'fake:fast-model'
    assert route.provider == 'fake'
    assert route.explanation == ('selected-by-policy',)
    assert route.lineage == ('lead-dispatch',)
    assert route.capability_floor == 0.70

    # Interrupts verification
    assert proj.pending_interrupt is not None
    assert proj.pending_interrupt.approval_id == 'app-1'
    assert proj.pending_interrupt.question == 'Allow rm -rf?'

    proj.apply_snapshot(snapshot)

    assert len(proj.transcript_items) == 1
    assert len(proj.agent_rail_items) == 1
    assert proj.pending_interrupt is not None


def test_collapsible_and_uncollapsible_invariants() -> None:
    proj = TuiProjection()
    sid = new_session_id()
    rid = new_run_id()
    tid = new_task_id()

    # 1. Tool call - can collapse, default collapsed when completed
    tool_ev = EventEnvelope(
        event_id=new_event_id(),
        session_id=sid,
        run_id=rid,
        task_id=tid,
        sequence=1,
        type='tool.completed',
        payload=ToolPayload(tool='read_file', status='completed'),
    )
    proj.apply_event(tool_ev)
    tool_item = proj.transcript_items[-1]
    assert tool_item.can_collapse is True
    assert tool_item.collapsed is True
    # Can toggle
    assert proj.toggle_collapse(tool_item.id) is False  # uncollapsed
    assert tool_item.collapsed is False
    assert proj.toggle_collapse(tool_item.id) is True  # collapsed
    assert tool_item.collapsed is True

    # 2. Diagnostic error - CANNOT collapse, collapsed must be False
    err_ev = EventEnvelope(
        event_id=new_event_id(),
        session_id=sid,
        run_id=rid,
        task_id=tid,
        sequence=2,
        type='diagnostic.error',
        payload=DiagnosticPayload(code='PERMISSION_DENIED', summary='Access denied to system dir'),
    )
    proj.apply_event(err_ev)
    err_item = proj.transcript_items[-1]
    assert err_item.can_collapse is False
    assert err_item.collapsed is False
    # Attempting to toggle has no effect
    assert proj.toggle_collapse(err_item.id) is False
    assert err_item.collapsed is False

    # 3. User question (interrupt) - CANNOT collapse
    question_ev = EventEnvelope(
        event_id=new_event_id(),
        session_id=sid,
        run_id=rid,
        task_id=tid,
        sequence=3,
        type='user.question',
        payload=UserPayload(action='question', content='Which dependency should we use?'),
    )
    proj.apply_event(question_ev)
    q_item = proj.transcript_items[-1]
    assert q_item.can_collapse is False
    assert q_item.collapsed is False
    assert proj.toggle_collapse(q_item.id) is False
    assert q_item.collapsed is False


def test_agent_rail_distinct_states() -> None:
    proj = TuiProjection()
    sid = new_session_id()
    rid = new_run_id()
    tid = new_task_id()

    states = [
        "queued", "started", "succeeded", "failed",
        "blocked", "cancelled", "returned_to_lead",
    ]
    for i, st in enumerate(states):
        ev = EventEnvelope(
            event_id=new_event_id(),
            session_id=sid,
            run_id=rid,
            task_id=tid,
            sequence=i + 1,
            type=f'task.{st}',
            payload=TaskPayload(profile='tester', status=st),
        )
        proj.apply_event(ev)
        assert len(proj.agent_rail_items) == 1
        assert proj.agent_rail_items[0].status == st


def test_budget_event_projection() -> None:
    proj = TuiProjection()
    proj.budget_item.hard_limit_usd = Decimal('10.00')
    sid = new_session_id()
    rid = new_run_id()

    # Reserve .00
    res_ev = EventEnvelope(
        event_id=new_event_id(),
        session_id=sid,
        run_id=rid,
        sequence=1,
        type='budget.reserved',
        payload=BudgetPayload(action='reserved', amount_usd=Decimal('2.00')),
    )
    proj.apply_event(res_ev)
    assert proj.budget_item.reserved_usd == Decimal('2.00')
    assert proj.budget_item.available_usd == Decimal('8.00')

    # Charge .50
    chg_ev = EventEnvelope(
        event_id=new_event_id(),
        session_id=sid,
        run_id=rid,
        sequence=2,
        type='budget.charged',
        payload=BudgetPayload(action='charged', amount_usd=Decimal('1.50')),
    )
    proj.apply_event(chg_ev)
    assert proj.budget_item.authoritative_actual_usd == Decimal('1.50')
    assert proj.budget_item.available_usd == Decimal('6.50')
    assert proj.footer_data.session_cost_usd == Decimal('1.50')


def test_projection_deduplicates_replayed_event_ids() -> None:
    proj = TuiProjection()
    event = EventEnvelope(
        event_id=new_event_id(),
        session_id=new_session_id(),
        run_id=new_run_id(),
        task_id=new_task_id(),
        sequence=1,
        type='tool.completed',
        payload=ToolPayload(tool='read_file', status='completed'),
    )

    proj.apply_event(event)
    proj.apply_event(event)

    assert len(proj.transcript_items) == 1


def test_projection_adaptive_plan_nodes_and_dependencies() -> None:
    proj = TuiProjection()
    plan = ExecutionPlan(
        schema_version=1,
        policy_version="1.0",
        revision=1,
        nodes=(
            PlanNode(
                local_id="n1",
                kind=PlanNodeKind.AGENT,
                objective="Analyze requirements",
                depends_on=(),
                effect_scope=EffectScope.READ,
            ),
            PlanNode(
                local_id="n2",
                kind=PlanNodeKind.TOOL,
                objective="Run tests",
                depends_on=("n1",),
                effect_scope=EffectScope.READ,
            ),
            PlanNode(
                local_id="n3",
                kind=PlanNodeKind.AGENT,
                objective="Implement change",
                depends_on=("n2",),
                effect_scope=EffectScope.WORKSPACE_WRITE,
            ),
        ),
    )
    plan_id = "00000000-0000-4000-8000-000000000010"
    node_id_1 = "00000000-0000-4000-8000-000000000011"
    node_id_2 = "00000000-0000-4000-8000-000000000012"
    node_id_3 = "00000000-0000-4000-8000-000000000013"
    persisted_plan = PersistedPlan(
        plan_id=plan_id,
        run_id="run-001",
        plan=plan,
        node_ids={"n1": node_id_1, "n2": node_id_2, "n3": node_id_3},
        node_states={
            "n1": PlanNodeState.READY,
            "n2": PlanNodeState.WAITING,
            "n3": PlanNodeState.WAITING,
        },
    )

    snapshot = SessionSnapshot(
        session_id="session-001",
        status="active",
        runs=(
            RunSnapshot(
                run_id="run-001",
                status="running",
                budget_limit_usd=Decimal("10.00"),
            ),
        ),
        tasks=(),
        attempts=(),
        assignments=(),
        budget_reservations=(),
        usage_records=(),
        approvals=(),
        events=(),
        plans=(persisted_plan,),
    )

    proj.apply_snapshot(snapshot)

    assert proj.current_plan_id == plan_id
    assert proj.current_plan_revision == 1
    assert len(proj.plan_items) == 3
    assert proj.plan_items["n1"].state == "ready"
    assert proj.plan_items["n2"].depends_on == ("n1",)
    assert proj.plan_items["n2"].state == "waiting"
    assert proj.plan_items["n3"].depends_on == ("n2",)

    # Live event transitions n1 to running, then succeeded, then n2 to ready
    event_running = EventEnvelope(
        event_id=new_event_id(),
        session_id=new_session_id(),
        run_id=new_run_id(),
        sequence=1,
        type="plan.node_running",
        payload=PlanPayload(
            action="node_running", plan_id=plan_id, revision=1, node_id=node_id_1
        ),
    )
    proj.apply_event(event_running)
    assert proj.plan_items["n1"].state == "running"

    event_succeeded = EventEnvelope(
        event_id=new_event_id(),
        session_id=new_session_id(),
        run_id=new_run_id(),
        sequence=2,
        type="plan.node_succeeded",
        payload=PlanPayload(
            action="node_succeeded", plan_id=plan_id, revision=1, node_id=node_id_1
        ),
    )
    proj.apply_event(event_succeeded)
    assert proj.plan_items["n1"].state == "succeeded"


def test_projection_active_mode_and_route_shadow_labels() -> None:
    proj = TuiProjection()
    tid = "task-shadow-1"
    aid = "attempt-shadow-1"

    asg = AssignmentSnapshot(
        assignment_id="asg-shadow-1",
        attempt_id=aid,
        provider="fake",
        model="fake:conservative-model",
        estimated_cost_usd=Decimal("0.15"),
        payload={
            "routing_mode": "auto",
            "capability_floor": 0.80,
            "explanation": ["active policy baseline"],
            "lineage": ["lead-dispatch"],
            "binding_constraint": "floor>=0.80",
            "evidence_status": "local (3 observations, rev: abc)",
            "evidence_revision": "abc12345",
            "shadow_recommendation": "direct ($0.0300) [shadow]",
            "shadow_reasons": ["shadow_candidate_has_lower_reliable_completed_work_cost"],
        },
    )

    snapshot = SessionSnapshot(
        session_id="session-shadow",
        status="active",
        runs=(
            RunSnapshot(
                run_id="run-shadow",
                status="running",
                budget_limit_usd=Decimal("5.00"),
            ),
        ),
        tasks=(
            TaskSnapshot(
                task_id=tid,
                run_id="run-shadow",
                description="Task with shadow decision",
                status=TaskStatus.RUNNING,
                idempotency_key="tsk-key",
            ),
        ),
        attempts=(
            AttemptSnapshot(
                attempt_id=aid,
                task_id=tid,
                number=1,
                status=AttemptStatus.RUNNING,
                idempotency_key="att-key",
            ),
        ),
        assignments=(asg,),
        budget_reservations=(),
        usage_records=(),
        approvals=(),
        events=(),
    )

    proj.apply_snapshot(snapshot)

    assert tid in proj.route_items
    route_item = proj.route_items[tid]
    assert route_item.shadow_recommendation == "direct ($0.0300) [shadow]"
    assert route_item.shadow_reasons == ("shadow_candidate_has_lower_reliable_completed_work_cost",)
    assert route_item.evidence_status == "local (3 observations, rev: abc)"
    assert route_item.evidence_revision == "abc12345"


def test_projection_workspace_integration_state() -> None:
    proj = TuiProjection()
    cs = ChangeSet(
        schema_version=1,
        changeset_id="00000000-0000-4000-8000-000000000001",
        task_id="00000000-0000-4000-8000-000000000002",
        attempt_id="00000000-0000-4000-8000-000000000003",
        snapshot_id="a" * 64,
        base_head="b" * 40,
        declared_scope=("src/module.py",),
        paths=(
            ChangeSetPath(
                path="src/module.py",
                effect="added",
                after=ContentImage(
                    digest="c" * 64,
                    size=24,
                    artifact_ref="art-001",
                ),
            ),
        ),
    )
    persisted_cs = PersistedChangeSet(changeset=cs, status=ChangeSetStatus.INTEGRATED)

    snapshot = SessionSnapshot(
        session_id="session-ws",
        status="active",
        runs=(),
        tasks=(),
        attempts=(),
        assignments=(),
        budget_reservations=(),
        usage_records=(),
        approvals=(),
        events=(),
        changesets=(persisted_cs,),
    )

    proj.apply_snapshot(snapshot)

    assert cs.changeset_id in proj.workspace_integrations
    ws_item = proj.workspace_integrations[cs.changeset_id]
    assert ws_item.status == "integrated"
    assert ws_item.paths == ("src/module.py",)
    assert ws_item.base_head == "b" * 40


def test_projection_actual_estimated_reserved_unknown_cost() -> None:
    proj = TuiProjection()
    snapshot = SessionSnapshot(
        session_id="session-costs",
        status="active",
        runs=(
            RunSnapshot(
                run_id="run-costs",
                status="running",
                budget_limit_usd=Decimal("10.00"),
            ),
        ),
        tasks=(),
        attempts=(),
        assignments=(),
        budget_reservations=(
            ReservationSnapshot(
                reservation_id="res-1",
                task_id=None,
                amount_usd=Decimal("2.00"),
                status="reserved",
                idempotency_key="r1",
            ),
        ),
        usage_records=(
            UsageSnapshot(
                usage_id="u1",
                task_id=None,
                amount_usd=Decimal("1.25"),
                authoritative=True,
                idempotency_key="u-auth",
            ),
            UsageSnapshot(
                usage_id="u2",
                task_id=None,
                amount_usd=Decimal("0.75"),
                authoritative=False,
                idempotency_key="u-est",
            ),
        ),
        approvals=(),
        events=(),
    )

    proj.apply_snapshot(snapshot)

    assert proj.budget_item.authoritative_actual_usd == Decimal("1.25")
    assert proj.budget_item.estimated_actual_usd == Decimal("0.75")
    assert proj.budget_item.reserved_usd == Decimal("2.00")
    assert proj.budget_item.unknown_cost_usd == Decimal("0.00")
    assert proj.budget_item.available_usd == Decimal("6.00")
    assert proj.footer_data.session_cost_usd == Decimal("2.00")


def test_projection_budget_uses_latest_run_only() -> None:
    proj = TuiProjection()
    snapshot = SessionSnapshot(
        session_id="session-multi-run",
        status="active",
        runs=(
            RunSnapshot(
                run_id="run-old",
                status="completed",
                budget_limit_usd=Decimal("1.00"),
            ),
            RunSnapshot(
                run_id="run-current",
                status="running",
                budget_limit_usd=Decimal("10.00"),
            ),
        ),
        tasks=(),
        attempts=(),
        assignments=(),
        budget_reservations=(
            ReservationSnapshot(
                reservation_id="res-old",
                task_id=None,
                amount_usd=Decimal("0.60"),
                status="reserved",
                idempotency_key="res-old",
                run_id="run-old",
            ),
            ReservationSnapshot(
                reservation_id="res-current",
                task_id=None,
                amount_usd=Decimal("0.50"),
                status="reserved",
                idempotency_key="res-current",
                run_id="run-current",
            ),
        ),
        usage_records=(
            UsageSnapshot(
                usage_id="usage-old",
                task_id=None,
                amount_usd=Decimal("0.30"),
                authoritative=True,
                idempotency_key="usage-old",
                run_id="run-old",
            ),
            UsageSnapshot(
                usage_id="usage-current",
                task_id=None,
                amount_usd=Decimal("0.25"),
                authoritative=True,
                idempotency_key="usage-current",
                run_id="run-current",
            ),
        ),
        approvals=(),
        events=(),
    )

    proj.apply_snapshot(snapshot)

    assert proj.budget_item.hard_limit_usd == Decimal("10.00")
    assert proj.budget_item.authoritative_actual_usd == Decimal("0.25")
    assert proj.budget_item.reserved_usd == Decimal("0.50")
    assert proj.budget_item.available_usd == Decimal("9.25")


def test_snapshot_budget_events_do_not_double_persisted_ledger_rows() -> None:
    session_id = new_session_id()
    run_id = new_run_id()
    snapshot = SessionSnapshot(
        session_id=str(session_id),
        status="active",
        runs=(
            RunSnapshot(
                run_id=str(run_id),
                status="running",
                budget_limit_usd=Decimal("1.00"),
            ),
        ),
        tasks=(),
        attempts=(),
        assignments=(),
        budget_reservations=(
            ReservationSnapshot(
                reservation_id="res-persisted",
                task_id=None,
                amount_usd=Decimal("0.40"),
                status="reserved",
                idempotency_key="res-persisted",
                run_id=str(run_id),
            ),
        ),
        usage_records=(),
        approvals=(),
        events=(
            EventEnvelope(
                event_id=new_event_id(),
                session_id=session_id,
                run_id=run_id,
                sequence=1,
                type="budget.reserved",
                payload=BudgetPayload(action="reserved", amount_usd=Decimal("0.40")),
            ),
        ),
    )

    projection = TuiProjection()
    projection.apply_snapshot(snapshot)

    assert projection.budget_item.reserved_usd == Decimal("0.40")
    assert projection.budget_item.available_usd == Decimal("0.60")


def test_live_and_resumed_projections_agree() -> None:
    sid = new_session_id()
    rid = new_run_id()
    tid = "00000000-0000-4000-8000-000000000021"
    aid = "00000000-0000-4000-8000-000000000022"
    plan_id = "00000000-0000-4000-8000-000000000023"
    node_id_1 = "00000000-0000-4000-8000-000000000024"
    node_id_2 = "00000000-0000-4000-8000-000000000025"
    cs_id = "00000000-0000-4000-8000-000000000026"

    plan = ExecutionPlan(
        schema_version=1,
        policy_version="1.0",
        revision=1,
        nodes=(
            PlanNode(
                local_id="step-1",
                kind=PlanNodeKind.AGENT,
                objective="Read repository docs",
                depends_on=(),
                effect_scope=EffectScope.READ,
            ),
            PlanNode(
                local_id="step-2",
                kind=PlanNodeKind.AGENT,
                objective="Implement feature",
                depends_on=("step-1",),
                effect_scope=EffectScope.WORKSPACE_WRITE,
            ),
        ),
    )

    persisted_plan = PersistedPlan(
        plan_id=plan_id,
        run_id=str(rid),
        plan=plan,
        node_ids={"step-1": node_id_1, "step-2": node_id_2},
        node_states={
            "step-1": PlanNodeState.SUCCEEDED,
            "step-2": PlanNodeState.READY,
        },
    )

    changeset = ChangeSet(
        schema_version=1,
        changeset_id=cs_id,
        task_id=tid,
        attempt_id=aid,
        snapshot_id="d" * 64,
        base_head="e" * 40,
        declared_scope=("docs/readme.md",),
        paths=(
            ChangeSetPath(
                path="docs/readme.md",
                effect="added",
                after=ContentImage(
                    digest="f" * 64,
                    size=120,
                    artifact_ref="art-readme",
                ),
            ),
        ),
    )
    persisted_cs = PersistedChangeSet(changeset=changeset, status=ChangeSetStatus.INTEGRATED)

    events = (
        EventEnvelope(
            event_id=new_event_id(),
            session_id=sid,
            run_id=rid,
            sequence=1,
            type="plan.admitted",
            payload=PlanPayload(action="admitted", plan_id=plan_id, revision=1),
        ),
        EventEnvelope(
            event_id=new_event_id(),
            session_id=sid,
            run_id=rid,
            sequence=2,
            type="budget.reserved",
            payload=BudgetPayload(action="reserved", amount_usd=Decimal("1.50")),
        ),
        EventEnvelope(
            event_id=new_event_id(),
            session_id=sid,
            run_id=rid,
            sequence=3,
            type="plan.node_running",
            payload=PlanPayload(
                action="node_running", plan_id=plan_id, revision=1, node_id=node_id_1
            ),
        ),
        EventEnvelope(
            event_id=new_event_id(),
            session_id=sid,
            run_id=rid,
            sequence=4,
            type="budget.charged",
            payload=BudgetPayload(action="charged", amount_usd=Decimal("0.50")),
        ),
        EventEnvelope(
            event_id=new_event_id(),
            session_id=sid,
            run_id=rid,
            sequence=5,
            type="plan.node_succeeded",
            payload=PlanPayload(
                action="node_succeeded", plan_id=plan_id, revision=1, node_id=node_id_1
            ),
        ),
        EventEnvelope(
            event_id=new_event_id(),
            session_id=sid,
            run_id=rid,
            sequence=6,
            type="plan.node_ready",
            payload=PlanPayload(
                action="node_ready", plan_id=plan_id, revision=1, node_id=node_id_2
            ),
        ),
        EventEnvelope(
            event_id=new_event_id(),
            session_id=sid,
            run_id=rid,
            sequence=7,
            type="task.succeeded",
            payload=TaskPayload(status="succeeded"),
            task_id=new_task_id(),
        ),
    )

    snapshot = SessionSnapshot(
        session_id=str(sid),
        status="active",
        runs=(
            RunSnapshot(
                run_id=str(rid),
                status="running",
                budget_limit_usd=Decimal("10.00"),
            ),
        ),
        tasks=(),
        attempts=(),
        assignments=(),
        budget_reservations=(
            ReservationSnapshot(
                reservation_id="res-agree",
                task_id=None,
                amount_usd=Decimal("1.50"),
                status="reserved",
                idempotency_key="r-agree",
            ),
        ),
        usage_records=(
            UsageSnapshot(
                usage_id="u-agree",
                task_id=None,
                amount_usd=Decimal("0.50"),
                authoritative=True,
                idempotency_key="u-agree-key",
            ),
        ),
        approvals=(),
        events=(),
        plans=(persisted_plan,),
        changesets=(persisted_cs,),
    )

    # 1. Reconstruct from snapshot
    proj_resumed = TuiProjection()
    proj_resumed.apply_snapshot(snapshot)

    # 2. Reconstruct from live events
    proj_live = TuiProjection()
    proj_live.budget_item.hard_limit_usd = Decimal("10.00")
    for ev in events:
        proj_live.apply_event(ev)

    # Both must agree on key execution states:
    assert (
        proj_resumed.budget_item.authoritative_actual_usd
        == proj_live.budget_item.authoritative_actual_usd
    )
    assert proj_resumed.budget_item.reserved_usd == proj_live.budget_item.reserved_usd
    assert proj_resumed.footer_data.active_mode == proj_live.footer_data.active_mode
    assert proj_resumed.footer_data.active_mode == "planned"
    assert "step-1" in proj_resumed.plan_items
    assert "step-2" in proj_resumed.plan_items
    assert proj_resumed.plan_items["step-1"].state == "succeeded"
    assert proj_resumed.plan_items["step-2"].state == "ready"
    assert proj_live.plan_items[node_id_1].state == "succeeded"
    assert proj_live.plan_items[node_id_2].state == "ready"


