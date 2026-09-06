from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from rudder.domain.events import (
    BudgetPayload,
    DiagnosticPayload,
    EventEnvelope,
    TaskPayload,
    ToolPayload,
    UserPayload,
)
from rudder.domain.ids import new_event_id, new_run_id, new_session_id, new_task_id
from rudder.domain.sessions import SessionStatus
from rudder.domain.tasks import AttemptStatus, TaskStatus
from rudder.sessions.journal import (
    ApprovalSnapshot,
    AssignmentSnapshot,
    AttemptSnapshot,
    ReservationSnapshot,
    RunSnapshot,
    SessionSnapshot,
    TaskSnapshot,
    UsageSnapshot,
)
from rudder.tui.projection import TuiProjection


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
    assert proj.budget_item.reserved_usd == Decimal('0.05')
    assert proj.budget_item.available_usd == Decimal('9.92')
    assert proj.budget_item.per_agent_costs[task_id] == Decimal('0.03')

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
