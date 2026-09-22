"""Repro: tool-call response with no provider usage must not block finalize."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage

from skail.routing.assignment import AccountingReconciliationRequired, AssignmentUsageSettler
from skail.routing.budget import BudgetLedger
from skail.runtime.model_middleware import TaskBoundModelMiddleware
from skail.sessions import Journal
from tests.fakes.provider import FakeProviderAdapter, FakeProviderChatModel

NOW = datetime(2026, 9, 17, tzinfo=UTC)


def _toolcall_message_without_usage() -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "write_file",
                "args": {"path": "a.txt", "content": "hi"},
                "id": "call_1",
                "type": "tool_call",
            }
        ],
        usage_metadata=None,
    )


def test_toolcall_message_shape_has_no_usage() -> None:
    message = _toolcall_message_without_usage()

    assert message.tool_calls, "expected tool-call fixture to carry tool_calls"
    assert message.usage_metadata is None


def _setup_journal(tmp_path: Path, *, run_id: str, task_id: str) -> Journal:
    journal = Journal(tmp_path / f"{run_id}.sqlite")
    journal.migrate()
    session_id = "11111111-1111-4111-8111-111111111111"
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
    return journal


def _make_assignment(
    journal: Journal,
    *,
    assignment_id: str,
    attempt_id: str,
    task_id: str,
    reservation_id: str,
    estimated: str = "0.20",
) -> None:
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
        run_id=_run_id(journal, task_id),
        task_id=task_id,
        amount_usd=Decimal(estimated),
        status="reserved",
        idempotency_key=f"res:{reservation_id}",
        created_at=NOW,
    )
    journal.create_assignment(
        assignment_id=assignment_id,
        attempt_id=attempt_id,
        provider="fake",
        model="fake/capable",
        estimated_cost_usd=Decimal(estimated),
        created_at=NOW,
        idempotency_key=f"assignment:{assignment_id}",
        payload={
            "reservation_id": reservation_id,
            "estimated_attempt_cost_usd": estimated,
        },
    )


def _run_id(journal: Journal, task_id: str) -> str:
    with journal._connect() as connection:
        row = connection.execute(
            "SELECT run_id FROM tasks WHERE task_id=?", (task_id,)
        ).fetchone()
        assert row is not None
        return str(row["run_id"])


def _finalize(journal: Journal, ledger: BudgetLedger, settler: AssignmentUsageSettler,
              *, assignment_id: str, reservation_id: str) -> None:
    from skail.runtime.run_controller import RunController

    controller = RunController.__new__(RunController)
    controller.journal = journal  # type: ignore[attr-defined]
    controller.ledger = ledger  # type: ignore[attr-defined]
    controller.usage_settler = settler  # type: ignore[attr-defined]
    assignment = SimpleNamespace(
        assignment_id=assignment_id, reservation_id=reservation_id
    )
    controller._finalize_assignment_budget(assignment)  # type: ignore[attr-defined]


def _middleware(
    settler: AssignmentUsageSettler,
    *,
    assignment_id: str,
    attempt_id: str,
    usage_callback: Any,
) -> TaskBoundModelMiddleware:
    model = FakeProviderChatModel()
    return TaskBoundModelMiddleware(
        {"fake/capable": model},
        assignments={assignment_id: "fake/capable"},
        usage_callback=usage_callback,
        call_begin=lambda selected_id, _key: settler.begin_call(selected_id),
        call_ambiguous=settler.mark_ambiguous,
    )


def _request(*, assignment_id: str, attempt_id: str) -> ModelRequest[Any]:
    model = FakeProviderChatModel()
    return ModelRequest(
        model=model,
        messages=[],
        state={
            "current_assignment_id": assignment_id,
            "locked_assignment_id": assignment_id,
            "assigned_model": "fake/capable",
            "assigned_provider": "fake",
            "attempt_id": attempt_id,
        },
    )


def _raise_usage_error(_assignment_id: str, _response: object, _call_id: str) -> None:
    raise ValueError("model call usage replay conflicts")


def test_sync_successful_response_with_unrecordable_usage_settles_estimated(
    tmp_path: Path,
) -> None:
    run_id = "12121212-1212-4212-8212-121212121212"
    task_id = "13131313-1313-4313-8313-131313131313"
    assignment_id = "14141414-1414-4414-8414-141414141414"
    attempt_id = "15151515-1515-4515-8515-151515151515"
    reservation_id = "res-sync-middleware"
    journal = _setup_journal(tmp_path, run_id=run_id, task_id=task_id)
    ledger = BudgetLedger(journal)
    settler = AssignmentUsageSettler(
        journal, ledger, {"fake": FakeProviderAdapter(FakeProviderChatModel())}
    )
    _make_assignment(
        journal,
        assignment_id=assignment_id,
        attempt_id=attempt_id,
        task_id=task_id,
        reservation_id=reservation_id,
    )
    middleware = _middleware(
        settler,
        assignment_id=assignment_id,
        attempt_id=attempt_id,
        usage_callback=_raise_usage_error,
    )
    response = ModelResponse(result=[_toolcall_message_without_usage()])

    actual = middleware.wrap_model_call(
        _request(assignment_id=assignment_id, attempt_id=attempt_id),
        lambda _request: response,
    )

    assert actual is response
    _finalize(
        journal,
        ledger,
        settler,
        assignment_id=assignment_id,
        reservation_id=reservation_id,
    )


@pytest.mark.asyncio
async def test_async_success_without_usage_is_not_made_ambiguous(tmp_path: Path) -> None:
    run_id = "16161616-1616-4616-8616-161616161616"
    task_id = "17171717-1717-4717-8717-171717171717"
    assignment_id = "18181818-1818-4818-8818-181818181818"
    attempt_id = "19191919-1919-4919-8919-191919191919"
    reservation_id = "res-async-middleware"
    journal = _setup_journal(tmp_path, run_id=run_id, task_id=task_id)
    ledger = BudgetLedger(journal)
    settler = AssignmentUsageSettler(
        journal, ledger, {"fake": FakeProviderAdapter(FakeProviderChatModel())}
    )
    _make_assignment(
        journal,
        assignment_id=assignment_id,
        attempt_id=attempt_id,
        task_id=task_id,
        reservation_id=reservation_id,
    )
    middleware = _middleware(
        settler,
        assignment_id=assignment_id,
        attempt_id=attempt_id,
        usage_callback=_raise_usage_error,
    )
    response = ModelResponse(result=[_toolcall_message_without_usage()])

    async def handler(_request: ModelRequest[Any]) -> ModelResponse[Any]:
        return response

    actual = await middleware.awrap_model_call(
        _request(assignment_id=assignment_id, attempt_id=attempt_id), handler
    )

    assert actual is response
    _finalize(
        journal,
        ledger,
        settler,
        assignment_id=assignment_id,
        reservation_id=reservation_id,
    )


def test_sync_handler_failure_is_marked_ambiguous(tmp_path: Path) -> None:
    run_id = "20202020-2020-4020-8020-202020202020"
    task_id = "21212121-2121-4121-8121-212121212121"
    assignment_id = "23232323-2323-4323-8323-232323232323"
    attempt_id = "24242424-2424-4424-8424-242424242424"
    reservation_id = "res-handler-error"
    journal = _setup_journal(tmp_path, run_id=run_id, task_id=task_id)
    ledger = BudgetLedger(journal)
    settler = AssignmentUsageSettler(
        journal, ledger, {"fake": FakeProviderAdapter(FakeProviderChatModel())}
    )
    _make_assignment(
        journal,
        assignment_id=assignment_id,
        attempt_id=attempt_id,
        task_id=task_id,
        reservation_id=reservation_id,
    )
    middleware = _middleware(
        settler,
        assignment_id=assignment_id,
        attempt_id=attempt_id,
        usage_callback=settler.record_call,
    )

    def handler(_request: ModelRequest[Any]) -> ModelResponse[Any]:
        raise RuntimeError("transport failed")

    with pytest.raises(AccountingReconciliationRequired):
        middleware.wrap_model_call(
            _request(assignment_id=assignment_id, attempt_id=attempt_id), handler
        )
    with pytest.raises(AccountingReconciliationRequired):
        _finalize(
            journal,
            ledger,
            settler,
            assignment_id=assignment_id,
            reservation_id=reservation_id,
        )


def test_started_but_unmeasured_toolcall_settles_estimated(tmp_path: Path) -> None:
    """RED: begin_call success with no usage record must settle, not raise."""
    run_id = "22222222-2222-4222-8222-222222222222"
    task_id = "33333333-3333-4333-8333-333333333333"
    journal = _setup_journal(tmp_path, run_id=run_id, task_id=task_id)
    ledger = BudgetLedger(journal)
    adapter = FakeProviderAdapter(FakeProviderChatModel())
    settler = AssignmentUsageSettler(journal, ledger, {"fake": adapter})

    assignment_id = "55555555-5555-4555-8555-555555555555"
    attempt_id = "44444444-4444-4444-8444-444444444444"
    reservation_id = "res-started-1"
    _make_assignment(
        journal,
        assignment_id=assignment_id,
        attempt_id=attempt_id,
        task_id=task_id,
        reservation_id=reservation_id,
    )

    # Streaming tool-call path: begin_call happened, response carried no
    # usage_metadata and record_call was skipped/raced -> row stays 'started'.
    settler.begin_call(assignment_id)
    message = _toolcall_message_without_usage()
    assert adapter.normalize_usage(message) is None

    _finalize(
        journal, ledger, settler,
        assignment_id=assignment_id, reservation_id=reservation_id,
    )

    with journal._connect() as connection:
        usage = connection.execute(
            "SELECT amount_usd, authoritative FROM usage_records WHERE reservation_id=?",
            (reservation_id,),
        ).fetchone()
    assert usage is not None, "expected estimated settlement for unmeasured call"
    assert Decimal(str(usage["amount_usd"])) == Decimal("0.20")
    assert usage["authoritative"] == 0


def test_genuine_ambiguous_still_raises(tmp_path: Path) -> None:
    run_id = "66666666-6666-4666-8666-666666666666"
    task_id = "77777777-7777-4777-8777-777777777777"
    journal = _setup_journal(tmp_path, run_id=run_id, task_id=task_id)
    ledger = BudgetLedger(journal)
    settler = AssignmentUsageSettler(
        journal, ledger, {"fake": FakeProviderAdapter(FakeProviderChatModel())}
    )

    assignment_id = "88888888-8888-4888-8888-888888888888"
    attempt_id = "99999999-9999-4999-8999-999999999999"
    reservation_id = "res-ambiguous-1"
    _make_assignment(
        journal,
        assignment_id=assignment_id,
        attempt_id=attempt_id,
        task_id=task_id,
        reservation_id=reservation_id,
    )

    call_id = settler.begin_call(assignment_id)
    settler.mark_ambiguous(call_id, RuntimeError("transport blew up mid-stream"))

    with pytest.raises(AccountingReconciliationRequired):
        _finalize(
            journal, ledger, settler,
            assignment_id=assignment_id, reservation_id=reservation_id,
        )
