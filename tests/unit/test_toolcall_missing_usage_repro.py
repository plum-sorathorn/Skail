"""Repro: tool-call response with no provider usage must not block finalize."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage

from skail.config.models import ProviderConfig
from skail.providers.errors import ProviderError, ProviderErrorKind
from skail.providers.llmgateway import LLMGATEWAY_BASE_URL, LLMGatewayAdapter
from skail.routing.assignment import AccountingReconciliationRequired, AssignmentUsageSettler
from skail.routing.budget import BudgetLedger
from skail.runtime.model_middleware import TaskBoundModelMiddleware
from skail.sessions import Journal
from skail.sessions.export import SessionExporter
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
    pricing: dict[str, str] | None = None,
    provider: str = "fake",
    model: str = "fake/capable",
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
        provider=provider,
        model=model,
        estimated_cost_usd=Decimal(estimated),
        created_at=NOW,
        idempotency_key=f"assignment:{assignment_id}",
        payload={
            "reservation_id": reservation_id,
            "estimated_attempt_cost_usd": estimated,
            "pricing_evidence": pricing or {},
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
        call_succeeded=settler.mark_call_succeeded,
        call_ambiguous=settler.mark_ambiguous,
    )


def _request(
    *, assignment_id: str, attempt_id: str,
    provider: str = "fake", model_key: str = "fake/capable"
) -> ModelRequest[Any]:
    model = FakeProviderChatModel()
    return ModelRequest(
        model=model,
        messages=[],
        state={
            "current_assignment_id": assignment_id,
            "locked_assignment_id": assignment_id,
            "assigned_model": model_key,
            "assigned_provider": provider,
            "attempt_id": attempt_id,
        },
    )


def _raise_usage_error(_assignment_id: str, _response: object, _call_id: str) -> None:
    raise ValueError("model call usage replay conflicts")


def test_measured_response_does_not_write_a_separate_success_marker() -> None:
    marked: list[str] = []
    recorded: list[str] = []
    middleware = TaskBoundModelMiddleware(
        {"fake/capable": FakeProviderChatModel()},
        assignments={"assignment": "fake/capable"},
        usage_callback=lambda _assignment, _response, call_id: recorded.append(call_id),
        call_begin=lambda _assignment, _key: "call-1",
        call_succeeded=marked.append,
    )
    response = ModelResponse(result=[AIMessage(content="done")])

    actual = middleware.wrap_model_call(
        _request(assignment_id="assignment", attempt_id="attempt"),
        lambda _request: response,
    )

    assert actual is response
    assert recorded == ["call-1"]
    assert marked == []


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


@pytest.mark.asyncio
async def test_cancelled_inflight_provider_call_keeps_its_reservation(
    tmp_path: Path,
) -> None:
    run_id = "abababab-abab-4bab-8bab-abababababab"
    task_id = "bcbcbcbc-bcbc-4cbc-8cbc-bcbcbcbcbcbc"
    assignment_id = "cdcdcdcd-cdcd-4dcd-8dcd-cdcdcdcdcdcd"
    attempt_id = "dededede-dede-4ede-8ede-dededededede"
    reservation_id = "res-cancelled-provider"
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
    entered = asyncio.Event()

    async def handler(_request: ModelRequest[Any]) -> ModelResponse[Any]:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    pending = asyncio.create_task(
        middleware.awrap_model_call(
            _request(assignment_id=assignment_id, attempt_id=attempt_id), handler
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending

    with journal._connect() as connection:
        call = connection.execute(
            "SELECT status,error_summary FROM provider_calls WHERE assignment_id=?",
            (assignment_id,),
        ).fetchone()
    assert call is not None
    assert call["status"] == "ambiguous"
    assert call["error_summary"].startswith("CancelledError:")

    with pytest.raises(AccountingReconciliationRequired):
        _finalize(
            journal,
            ledger,
            settler,
            assignment_id=assignment_id,
            reservation_id=reservation_id,
        )
    with journal._connect() as connection:
        reservation = connection.execute(
            "SELECT status FROM budget_reservations WHERE reservation_id=?",
            (reservation_id,),
        ).fetchone()
        usage_count = connection.execute(
            "SELECT COUNT(*) FROM usage_records WHERE reservation_id=?",
            (reservation_id,),
        ).fetchone()[0]
    assert reservation is not None and reservation["status"] == "reserved"
    assert usage_count == 0


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


def test_returned_but_unmeasured_toolcall_settles_estimated(tmp_path: Path) -> None:
    """A recorded provider response can settle from the attempt estimate."""
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

    # The tool-call response returned without usable token counts.
    call_id = settler.begin_call(assignment_id)
    settler.mark_call_succeeded(call_id)
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


def test_unreturned_started_call_is_ambiguous_on_finalization(tmp_path: Path) -> None:
    run_id = "10101010-1010-4010-8010-101010101010"
    task_id = "11111111-2222-4111-8111-111111111111"
    assignment_id = "12121212-2222-4212-8212-121212121212"
    attempt_id = "13131313-2222-4313-8313-131313131313"
    reservation_id = "res-unreturned-call"
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
    settler.begin_call(assignment_id)

    with pytest.raises(AccountingReconciliationRequired):
        _finalize(
            journal,
            ledger,
            settler,
            assignment_id=assignment_id,
            reservation_id=reservation_id,
        )
    with journal._connect() as connection:
        call_status = connection.execute(
            "SELECT status FROM provider_calls WHERE assignment_id=?", (assignment_id,)
        ).fetchone()["status"]
        reservation_status = connection.execute(
            "SELECT status FROM budget_reservations WHERE reservation_id=?",
            (reservation_id,),
        ).fetchone()["status"]
    assert call_status == "ambiguous"
    assert reservation_status == "reserved"


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
        settler.mark_call_succeeded(call_id)
    with pytest.raises(AccountingReconciliationRequired):
        settler.record_call(
            assignment_id,
            AIMessage(
                content="late response",
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            ),
            call_id=call_id,
        )

    with pytest.raises(AccountingReconciliationRequired):
        _finalize(
            journal, ledger, settler,
            assignment_id=assignment_id, reservation_id=reservation_id,
        )


def _cancelled_calls(
    tmp_path: Path, *, count: int = 1, estimated: str = "0.20"
) -> tuple[Journal, BudgetLedger, AssignmentUsageSettler, str, str, list[str]]:
    run_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    task_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    assignment_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    attempt_id = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    reservation_id = "res-reconcile-cancelled"
    journal = _setup_journal(tmp_path, run_id=run_id, task_id=task_id)
    ledger = BudgetLedger(journal)
    settler = AssignmentUsageSettler(journal, ledger, {})
    _make_assignment(
        journal,
        assignment_id=assignment_id,
        attempt_id=attempt_id,
        task_id=task_id,
        reservation_id=reservation_id,
        estimated=estimated,
    )
    call_ids = [settler.begin_call(assignment_id, f"call-{index}") for index in range(count)]
    for call_id in call_ids:
        settler.mark_ambiguous(call_id, asyncio.CancelledError())
    return journal, ledger, settler, assignment_id, reservation_id, call_ids


def test_cancelled_call_estimate_preview_and_reconciliation_keep_usage_unknown(
    tmp_path: Path,
) -> None:
    journal, ledger, settler, assignment_id, reservation_id, call_ids = _cancelled_calls(
        tmp_path
    )
    session_id = "11111111-1111-4111-8111-111111111111"
    call_id = call_ids[0]

    preview = settler.preview_ambiguous_call(session_id, call_id)
    assert preview.estimated_attempt_cost_usd == Decimal("0.20")
    assert preview.remaining_open_calls == 1
    assert not preview.settled
    snapshot = ledger.snapshot(_run_id(journal, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"))
    assert snapshot.reserved_usd == Decimal("0.20")

    applied = settler.reconcile_ambiguous_call(session_id, call_id)
    assert applied.estimated_attempt_cost_usd == Decimal("0.20")
    assert applied.remaining_open_calls == 0
    assert applied.settled
    assert settler.reconcile_ambiguous_call(session_id, call_id) == applied
    _finalize(
        journal,
        ledger,
        settler,
        assignment_id=assignment_id,
        reservation_id=reservation_id,
    )

    with journal._connect() as connection:
        call = connection.execute(
            "SELECT status,input_tokens,output_tokens,amount_usd,authority "
            "FROM provider_calls WHERE call_id=?",
            (call_id,),
        ).fetchone()
        reservation = connection.execute(
            "SELECT status FROM budget_reservations WHERE reservation_id=?",
            (reservation_id,),
        ).fetchone()
        usage = connection.execute(
            "SELECT amount_usd,authoritative,authority FROM usage_records WHERE reservation_id=?",
            (reservation_id,),
        ).fetchone()
        failure = connection.execute(
            "SELECT status FROM accounting_reconciliation_failures WHERE call_id=?",
            (call_id,),
        ).fetchone()
    assert tuple(call) == ("ambiguous", None, None, None, "unknown")
    assert reservation["status"] == "settled"
    assert tuple(usage) == ("0.20", 0, "reconciled_estimate")
    assert failure["status"] == "estimated"
    exported = SessionExporter(journal=journal).export(session_id)
    assert exported["provider_calls"][0]["cost_usd"] is None
    assert exported["provider_calls"][0]["status"] == "ambiguous"
    assert exported["provider_calls"][0]["reconciliation_status"] == "estimated"
    assert exported["usage"][0]["authority"] == "reconciled_estimate"
    assert exported["model_usage"][0]["total_cost_usd"] is None


def test_multiple_cancelled_calls_settle_once_after_each_is_reconciled(
    tmp_path: Path,
) -> None:
    journal, ledger, settler, _, reservation_id, call_ids = _cancelled_calls(
        tmp_path, count=2
    )
    session_id = "11111111-1111-4111-8111-111111111111"
    with pytest.raises(KeyError):
        settler.preview_ambiguous_call("wrong-session", call_ids[0])

    first = settler.reconcile_ambiguous_call(session_id, call_ids[0])
    assert first.remaining_open_calls == 1
    assert not first.settled
    with journal._connect() as connection:
        assert connection.execute(
            "SELECT status FROM budget_reservations WHERE reservation_id=?",
            (reservation_id,),
        ).fetchone()["status"] == "reserved"

    second = settler.reconcile_ambiguous_call(session_id, call_ids[1])
    assert second.remaining_open_calls == 0
    assert second.settled
    with journal._connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM usage_records WHERE reservation_id=?",
            (reservation_id,),
        ).fetchone()[0] == 1
    snapshot = ledger.snapshot(_run_id(journal, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"))
    assert snapshot.estimated_actual_usd == Decimal("0.20")


def test_cancelled_call_estimate_includes_observed_token_cost(tmp_path: Path) -> None:
    run_id = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    task_id = "ffffffff-ffff-4fff-8fff-ffffffffffff"
    assignment_id = "10101010-1010-4010-8010-101010101010"
    journal = _setup_journal(tmp_path, run_id=run_id, task_id=task_id)
    settler = AssignmentUsageSettler(
        journal, BudgetLedger(journal),
        {"fake": FakeProviderAdapter(FakeProviderChatModel())},
    )
    _make_assignment(
        journal,
        assignment_id=assignment_id,
        attempt_id="20202020-2020-4020-8020-202020202020",
        task_id=task_id,
        reservation_id="res-measured-before-cancel",
        estimated="0.01",
        pricing={"input_usd_per_million": "1", "output_usd_per_million": "2"},
    )
    measured = settler.begin_call(assignment_id, "measured")
    settler.record_call(
        assignment_id,
        AIMessage(
            content="done",
            usage_metadata={
                "input_tokens": 20000,
                "output_tokens": 10000,
                "total_tokens": 30000,
            },
        ),
        call_id=measured,
    )
    cancelled = settler.begin_call(assignment_id, "cancelled")
    settler.mark_ambiguous(cancelled, asyncio.CancelledError())
    session_id = "11111111-1111-4111-8111-111111111111"

    preview = settler.preview_ambiguous_call(session_id, cancelled)
    assert preview.estimated_attempt_cost_usd == Decimal("0.04")
    applied = settler.reconcile_ambiguous_call(session_id, cancelled)
    assert applied.settled
    with journal._connect() as connection:
        usage = connection.execute(
            "SELECT amount_usd,authority FROM usage_records "
            "WHERE reservation_id='res-measured-before-cancel'"
        ).fetchone()
    assert tuple(usage) == ("0.04", "reconciled_estimate")


def test_unpriced_cancelled_call_does_not_become_zero_cost(tmp_path: Path) -> None:
    _, _, settler, _, _, call_ids = _cancelled_calls(tmp_path, estimated="0")
    with pytest.raises(AccountingReconciliationRequired, match="no priced attempt estimate"):
        settler.preview_ambiguous_call(
            "11111111-1111-4111-8111-111111111111", call_ids[0]
        )


@pytest.mark.asyncio
async def test_gateway_http_400_rejection_settles_prior_measured_calls(
    tmp_path: Path,
) -> None:
    run_id = "30303030-3030-4030-8030-303030303030"
    task_id = "40404040-4040-4040-8040-404040404040"
    assignment_id = "50505050-5050-4050-8050-505050505050"
    attempt_id = "60606060-6060-4060-8060-606060606060"
    reservation_id = "res-gateway-rejected"
    session_id = "11111111-1111-4111-8111-111111111111"
    journal = _setup_journal(tmp_path, run_id=run_id, task_id=task_id)
    ledger = BudgetLedger(journal)
    adapter = LLMGatewayAdapter(
        ProviderConfig(
            type="openai-compatible",
            base_url=LLMGATEWAY_BASE_URL,
            models=("gpt-6-sol",),
        ),
        api_key="fixture-credential",
    )
    settler = AssignmentUsageSettler(journal, ledger, {"llmgateway": adapter})
    _make_assignment(
        journal,
        assignment_id=assignment_id,
        attempt_id=attempt_id,
        task_id=task_id,
        reservation_id=reservation_id,
        provider="llmgateway",
        model="gpt-6-sol",
        pricing={"input_usd_per_million": "1", "output_usd_per_million": "2"},
    )
    prior_call = settler.begin_call(assignment_id, "prior")
    settler.record_call(
        assignment_id,
        AIMessage(
            content="done",
            usage_metadata={
                "input_tokens": 20000,
                "output_tokens": 10000,
                "total_tokens": 30000,
            },
        ),
        call_id=prior_call,
    )
    middleware = TaskBoundModelMiddleware(
        {"gpt-6-sol": FakeProviderChatModel()},
        assignments={assignment_id: "gpt-6-sol"},
        providers={"llmgateway": adapter},
        usage_callback=settler.record_call,
        call_begin=lambda selected_id, _key: settler.begin_call(selected_id),
        call_rejected=settler.mark_rejected,
        call_ambiguous=settler.mark_ambiguous,
    )
    request = httpx.Request("POST", f"{LLMGATEWAY_BASE_URL}/chat/completions")
    response = httpx.Response(
        400,
        request=request,
        json={"error": {"type": "invalid_request_error", "code": "invalid_request"}},
    )

    async def handler(_request: ModelRequest[Any]) -> ModelResponse[Any]:
        raise httpx.HTTPStatusError("bad request", request=request, response=response)

    with pytest.raises(ProviderError, match="400"):
        await middleware.awrap_model_call(
            _request(
                assignment_id=assignment_id,
                attempt_id=attempt_id,
                provider="llmgateway",
                model_key="gpt-6-sol",
            ),
            handler,
        )
    _finalize(
        journal,
        ledger,
        settler,
        assignment_id=assignment_id,
        reservation_id=reservation_id,
    )

    with journal._connect() as connection:
        calls = connection.execute(
            "SELECT status,amount_usd FROM provider_calls WHERE assignment_id=? "
            "ORDER BY ordinal",
            (assignment_id,),
        ).fetchall()
        usage = connection.execute(
            "SELECT amount_usd FROM usage_records WHERE reservation_id=?",
            (reservation_id,),
        ).fetchone()
        failures = connection.execute(
            "SELECT COUNT(*) FROM accounting_reconciliation_failures WHERE assignment_id=?",
            (assignment_id,),
        ).fetchone()[0]
    assert [tuple(call) for call in calls] == [
        ("completed", "0.04"),
        ("rejected", None),
    ]
    assert usage["amount_usd"] == "0.04"
    assert failures == 0
    assert ledger.snapshot(run_id).reserved_usd == Decimal("0")
    exported = SessionExporter(journal=journal).export(session_id)
    assert exported["model_usage"][0]["total_cost_usd"] == "0.04"


def test_rejected_only_call_releases_reservation_without_zero_usage(tmp_path: Path) -> None:
    run_id = "70707070-7070-4070-8070-707070707070"
    task_id = "80808080-8080-4080-8080-808080808080"
    assignment_id = "90909090-9090-4090-8090-909090909090"
    reservation_id = "res-rejected-only"
    journal = _setup_journal(tmp_path, run_id=run_id, task_id=task_id)
    ledger = BudgetLedger(journal)
    settler = AssignmentUsageSettler(
        journal, ledger, {"fake": FakeProviderAdapter(FakeProviderChatModel())}
    )
    _make_assignment(
        journal,
        assignment_id=assignment_id,
        attempt_id="a0a0a0a0-a0a0-40a0-80a0-a0a0a0a0a0a0",
        task_id=task_id,
        reservation_id=reservation_id,
    )
    call_id = settler.begin_call(assignment_id)
    rejected = ProviderError(
        kind=ProviderErrorKind.PROTOCOL,
        summary="request rejected (HTTP 400)",
        provider="fake",
        retry_safe=False,
        request_rejected=True,
    )

    settler.mark_rejected(call_id, rejected)
    settler.mark_ambiguous(call_id, RuntimeError("late error"))
    with pytest.raises(AccountingReconciliationRequired):
        settler.record_call(assignment_id, AIMessage(content="late response"), call_id=call_id)
    _finalize(
        journal,
        ledger,
        settler,
        assignment_id=assignment_id,
        reservation_id=reservation_id,
    )

    with journal._connect() as connection:
        call = connection.execute(
            "SELECT status,amount_usd FROM provider_calls WHERE call_id=?", (call_id,)
        ).fetchone()
        reservation = connection.execute(
            "SELECT status FROM budget_reservations WHERE reservation_id=?",
            (reservation_id,),
        ).fetchone()
        usage_count = connection.execute(
            "SELECT COUNT(*) FROM usage_records WHERE reservation_id=?", (reservation_id,)
        ).fetchone()[0]
    assert tuple(call) == ("rejected", None)
    assert reservation["status"] == "released"
    assert usage_count == 0


def test_failed_estimate_settlement_keeps_reconciliation_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal, ledger, settler, _, reservation_id, call_ids = _cancelled_calls(tmp_path)

    def fail_settlement(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("settlement failed")

    monkeypatch.setattr(ledger, "settle", fail_settlement)
    with pytest.raises(AccountingReconciliationRequired, match="usage settlement failed"):
        settler.reconcile_ambiguous_call(
            "11111111-1111-4111-8111-111111111111", call_ids[0]
        )
    with journal._connect() as connection:
        failure = connection.execute(
            "SELECT status FROM accounting_reconciliation_failures WHERE call_id=?",
            (call_ids[0],),
        ).fetchone()
        reservation = connection.execute(
            "SELECT status FROM budget_reservations WHERE reservation_id=?",
            (reservation_id,),
        ).fetchone()
        usage_count = connection.execute(
            "SELECT COUNT(*) FROM usage_records WHERE reservation_id=?", (reservation_id,)
        ).fetchone()[0]
    assert failure["status"] == "open"
    assert reservation["status"] == "reserved"
    assert usage_count == 0


def test_cancelled_call_reconciliation_cli_previews_before_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from skail.cli import commands
    from skail.cli.main import _parse_cli_args

    journal, _, _, _, _, call_ids = _cancelled_calls(tmp_path)
    session_id = "11111111-1111-4111-8111-111111111111"
    rendered: list[str] = []
    monkeypatch.setattr(commands, "render_print_stdout", rendered.append)
    args = _parse_cli_args(["sessions", "reconcile-call", session_id, call_ids[0]])
    assert commands.handle_sessions(args, None, journal) == 0  # type: ignore[arg-type]
    assert any("USD 0.20" in line and "estimate" in line.lower() for line in rendered)
    with journal._connect() as connection:
        assert connection.execute(
            "SELECT status FROM accounting_reconciliation_failures WHERE call_id=?",
            (call_ids[0],),
        ).fetchone()["status"] == "open"

    applied = _parse_cli_args(
        ["sessions", "reconcile-call", session_id, call_ids[0], "--apply"]
    )
    assert commands.handle_sessions(applied, None, journal) == 0  # type: ignore[arg-type]
    assert any("settled" in line.lower() for line in rendered)
