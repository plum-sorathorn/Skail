"""Regression tests for tool-scoped failure keys, gate blocking, redaction."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import ToolMessage

from skail.routing.assignment import (
    AccountingReconciliationRequired,
    AssignmentUsageSettler,
)
from skail.routing.budget import BudgetLedger
from skail.runtime.failure_monitor import FailureMonitor
from skail.sessions import Journal
from skail.tools.assembly import RuntimeActivityMiddleware

NOW = datetime(2026, 9, 17, tzinfo=UTC)


class ReadTimeout(TimeoutError):
    pass


def _middleware() -> RuntimeActivityMiddleware:
    return RuntimeActivityMiddleware(
        model_name="test-model", emit=lambda _event, _value: None, redactor=None
    )


def _request(name: str, call_id: str) -> Any:
    from langchain.agents.middleware import ToolCallRequest

    return ToolCallRequest(
        tool_call={"name": name, "id": call_id, "args": {}, "type": "tool_call"},
        tool=None,
        state={},
        runtime=None,  # type: ignore[arg-type]
    )


def test_same_tool_error_after_success_is_repeated() -> None:
    monitor = FailureMonitor()
    assert monitor.observe_error("boom", tool="edit_file") is None
    monitor.observe_success()
    assert (
        monitor.observe_error("boom", tool="edit_file") == "failure.repeated_error"
    )


def test_different_tools_gate_rejections_do_not_repeat() -> None:
    middleware = _middleware()

    def gate_rejection(request: Any) -> ToolMessage:
        return ToolMessage(
            content=(
                "execution.decision_required: record execution_decision "
                "before operational tools"
            ),
            tool_call_id=request.tool_call["id"],
            status="error",
        )

    assert (
        middleware._run_tool(_request("task", "call-1"), gate_rejection) is not None
    )
    assert middleware._run_tool(_request("ls", "call-2"), gate_rejection) is not None


def test_same_tool_twice_is_repeated_error() -> None:
    middleware = _middleware()

    def tool_error(request: Any) -> ToolMessage:
        return ToolMessage(
            content="disk write failed",
            tool_call_id=request.tool_call["id"],
            status="error",
        )

    middleware._run_tool(_request("edit_file", "call-1"), tool_error)
    with pytest.raises(RuntimeError, match="failure.repeated_error"):
        middleware._run_tool(_request("edit_file", "call-2"), tool_error)


def _setup_journal(tmp_path: Path) -> tuple[Journal, str, str, str]:
    journal = Journal(tmp_path / "repro.sqlite")
    journal.migrate()
    session_id = "11111111-1111-4111-8111-111111111111"
    run_id = "22222222-2222-4222-8222-222222222222"
    task_id = "33333333-3333-4333-8333-333333333333"
    attempt_id = "44444444-4444-4444-8444-444444444444"
    assignment_id = "55555555-5555-4555-8555-555555555555"
    reservation_id = "66666666-6666-4666-8666-666666666666"
    journal.create_session(session_id=session_id, title="repro", created_at=NOW)
    journal.create_run(
        run_id=run_id,
        session_id=session_id,
        status="running",
        budget_limit_usd=Decimal("1.00"),
        created_at=NOW,
    )
    journal.create_task(
        task_id=task_id,
        run_id=run_id,
        description="route",
        status="queued",
        idempotency_key=f"task:{task_id}",
        created_at=NOW,
    )
    journal.create_attempt(
        attempt_id=attempt_id,
        task_id=task_id,
        number=1,
        status="assigned",
        idempotency_key=f"attempt:{attempt_id}",
        created_at=NOW,
    )
    journal.create_reservation(
        reservation_id=reservation_id,
        run_id=run_id,
        task_id=task_id,
        amount_usd=Decimal("0.20"),
        status="reserved",
        idempotency_key=f"res:{reservation_id}",
        created_at=NOW,
    )
    journal.create_assignment(
        assignment_id=assignment_id,
        attempt_id=attempt_id,
        provider="fake",
        model="fake/capable",
        estimated_cost_usd=Decimal("0.20"),
        created_at=NOW,
        idempotency_key=f"assignment:{assignment_id}",
        payload={
            "reservation_id": reservation_id,
            "estimated_attempt_cost_usd": "0.20",
        },
    )
    return journal, assignment_id, reservation_id, run_id


def test_ambiguous_handler_surfaces_class_name_redacted(tmp_path: Path) -> None:
    from tests.fakes.provider import FakeProviderAdapter

    journal, assignment_id, reservation_id, _run_id = _setup_journal(tmp_path)
    ledger = BudgetLedger(journal)
    settler = AssignmentUsageSettler(journal, ledger, {"fake": FakeProviderAdapter()})
    call_id = settler.begin_call(assignment_id)
    settler.mark_ambiguous(call_id, ReadTimeout("transport blew up mid-stream"))

    with journal._connect() as connection:
        row = connection.execute(
            "SELECT status FROM provider_calls WHERE call_id=?", (call_id,)
        ).fetchone()
    assert row["status"] == "ambiguous"

    from skail.runtime.run_controller import RunController

    controller = RunController.__new__(RunController)
    controller.journal = journal  # type: ignore[attr-defined]
    controller.ledger = ledger  # type: ignore[attr-defined]
    controller.usage_settler = settler  # type: ignore[attr-defined]
    assignment = SimpleNamespace(
        assignment_id=assignment_id, reservation_id=reservation_id
    )
    with pytest.raises(AccountingReconciliationRequired, match="ReadTimeout"):
        controller._finalize_assignment_budget(assignment)  # type: ignore[attr-defined]

    try:
        controller._finalize_assignment_budget(assignment)  # type: ignore[attr-defined]
    except AccountingReconciliationRequired as exc:
        assert "ReadTimeout" in str(exc)
        # D-12(3): the stored (redacted) ambiguity detail is surfaced for
        # operators while the class-only prefix is preserved.
        assert (
            "provider usage is uncertain (ReadTimeout); reservation "
            "remains held: transport blew up mid-stream" in str(exc)
        )

    with journal._connect() as connection:
        reservation = connection.execute(
            "SELECT status FROM budget_reservations WHERE reservation_id=?",
            (reservation_id,),
        ).fetchone()
    assert reservation["status"] == "reserved"


def test_ambiguous_detail_defaults_to_legacy_message_without_summary(
    tmp_path: Path,
) -> None:
    from tests.fakes.provider import FakeProviderAdapter

    journal, assignment_id, reservation_id, _run_id = _setup_journal(tmp_path)
    ledger = BudgetLedger(journal)
    settler = AssignmentUsageSettler(journal, ledger, {"fake": FakeProviderAdapter()})
    call_id = settler.begin_call(assignment_id)
    settler.mark_ambiguous(call_id, ReadTimeout("transport blew up mid-stream"))
    with journal._connect() as connection:
        connection.execute(
            "UPDATE provider_calls SET error_summary='NoColonDetail' WHERE call_id=?",
            (call_id,),
        )

    from skail.runtime.run_controller import RunController

    controller = RunController.__new__(RunController)
    controller.journal = journal  # type: ignore[attr-defined]
    controller.ledger = ledger  # type: ignore[attr-defined]
    controller.usage_settler = settler  # type: ignore[attr-defined]
    assignment = SimpleNamespace(
        assignment_id=assignment_id, reservation_id=reservation_id
    )

    with pytest.raises(
        AccountingReconciliationRequired,
        match=r"provider usage is uncertain \(NoColonDetail\); reservation remains held$",
    ):
        controller._finalize_assignment_budget(assignment)  # type: ignore[attr-defined]
