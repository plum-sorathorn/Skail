from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from skail.domain.usage import NormalizedUsage, UsageAuthority
from skail.routing.budget import (
    BudgetBlockedError,
    BudgetLedger,
    ReservationRequest,
    ReservationStateError,
)
from skail.sessions import Journal, JournalIdempotencyError

NOW = datetime(2026, 9, 2, tzinfo=UTC)
SESSION_ID = "11111111-1111-4111-8111-111111111111"
RUN_ID = "22222222-2222-4222-8222-222222222222"
TASK_ID = "33333333-3333-4333-8333-333333333333"


def _ledger(tmp_path: Path, limit: str = "1.00") -> BudgetLedger:
    journal = Journal(tmp_path / "skail.sqlite")
    journal.migrate()
    journal.create_session(session_id=SESSION_ID, title="budget", created_at=NOW)
    journal.create_run(
        run_id=RUN_ID,
        session_id=SESSION_ID,
        status="running",
        budget_limit_usd=Decimal(limit),
        created_at=NOW,
    )
    journal.create_task(
        task_id=TASK_ID,
        run_id=RUN_ID,
        description="fund me",
        status="queued",
        idempotency_key="task",
        created_at=NOW,
    )
    return BudgetLedger(journal)


def _request(amount: str = "0.40", *, key: str = "reserve-1") -> ReservationRequest:
    return ReservationRequest(
        reservation_id=f"id-{key}",
        run_id=RUN_ID,
        task_id=TASK_ID,
        amount_usd=Decimal(amount),
        idempotency_key=key,
    )


def test_snapshot_keeps_actual_estimated_reserved_and_available_distinct(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    reservation = ledger.reserve(_request())
    ledger.settle(
        reservation.reservation_id,
        usage_id="usage-1",
        usage=NormalizedUsage(
            input_tokens=1,
            output_tokens=1,
            cost_usd=Decimal("0.25"),
            authority=UsageAuthority.ESTIMATED_ACTUAL,
        ),
        idempotency_key="call-1",
    )
    ledger.reserve(_request("0.10", key="reserve-2"))
    snapshot = ledger.snapshot(RUN_ID)
    assert snapshot.authoritative_actual_usd == Decimal("0")
    assert snapshot.estimated_actual_usd == Decimal("0.25")
    assert snapshot.reserved_usd == Decimal("0.10")
    assert snapshot.available_usd == Decimal("0.65")


def test_reserve_honors_run_task_and_lead_allowance_boundaries(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    held = ledger.reserve(
        _request("0.70"), task_limit_usd=Decimal("0.70"), lead_allowance_usd=Decimal("0.30")
    )
    assert held.warning_crossed is False
    with pytest.raises(BudgetBlockedError) as caught:
        ledger.reserve(_request("0.31", key="blocked"))
    assert caught.value.code == "budget.blocked"


def test_reserve_release_and_settle_are_idempotent(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    request = _request()
    first = ledger.reserve(request)
    assert ledger.reserve(request) == first
    with pytest.raises(JournalIdempotencyError):
        ledger.reserve(request.model_copy(update={"amount_usd": Decimal("0.41")}))
    ledger.release(first.reservation_id)
    ledger.release(first.reservation_id)
    assert ledger.snapshot(RUN_ID).available_usd == Decimal("1.00")

    second = ledger.reserve(_request(key="reserve-2"))
    usage = NormalizedUsage(
        input_tokens=1,
        output_tokens=1,
        cost_usd=Decimal("0.20"),
        authority=UsageAuthority.AUTHORITATIVE_ACTUAL,
    )
    ledger.settle(second.reservation_id, usage_id="usage-2", usage=usage, idempotency_key="call-2")
    ledger.settle(second.reservation_id, usage_id="usage-2", usage=usage, idempotency_key="call-2")
    assert ledger.snapshot(RUN_ID).authoritative_actual_usd == Decimal("0.20")
    with pytest.raises(ReservationStateError):
        ledger.release(second.reservation_id)


def test_authoritative_usage_may_replace_estimated_without_double_charge(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    held = ledger.reserve(_request())
    estimated = NormalizedUsage(
        input_tokens=10,
        output_tokens=2,
        cost_usd=Decimal("0.30"),
        authority=UsageAuthority.ESTIMATED_ACTUAL,
    )
    actual = estimated.model_copy(
        update={"cost_usd": Decimal("0.22"), "authority": UsageAuthority.AUTHORITATIVE_ACTUAL}
    )
    ledger.settle(
        held.reservation_id, usage_id="usage", usage=estimated, idempotency_key="provider-call"
    )
    ledger.settle(
        held.reservation_id, usage_id="usage", usage=actual, idempotency_key="provider-call"
    )
    snapshot = ledger.snapshot(RUN_ID)
    assert snapshot.estimated_actual_usd == Decimal("0")
    assert snapshot.authoritative_actual_usd == Decimal("0.22")


def test_conservative_estimate_may_reconcile_a_lower_token_estimate(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    held = ledger.reserve(_request())
    measured = NormalizedUsage(
        input_tokens=1000,
        output_tokens=500,
        cost_usd=Decimal("0.002"),
        authority=UsageAuthority.TOKEN_DERIVED_ESTIMATE,
    )
    conservative = NormalizedUsage(
        input_tokens=1000,
        output_tokens=500,
        cost_usd=Decimal("0.20"),
        authority=UsageAuthority.CONSERVATIVE_ESTIMATE,
    )
    ledger.settle(
        held.reservation_id, usage_id="usage", usage=measured, idempotency_key="attempt"
    )
    ledger.settle(
        held.reservation_id,
        usage_id="usage",
        usage=conservative,
        idempotency_key="attempt",
    )
    ledger.settle(
        held.reservation_id,
        usage_id="usage",
        usage=conservative,
        idempotency_key="attempt",
    )

    snapshot = ledger.snapshot(RUN_ID)
    assert snapshot.authoritative_actual_usd == Decimal("0")
    assert snapshot.estimated_actual_usd == Decimal("0.20")


def test_warning_fires_once_until_balance_falls_below_then_crosses_again(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    first = ledger.reserve(_request("0.80"))
    assert first.warning_crossed is True
    assert ledger.reserve(_request("0.80")).warning_crossed is False
    ledger.release(first.reservation_id)
    second = ledger.reserve(_request("0.80", key="reserve-2"))
    assert second.warning_crossed is True
