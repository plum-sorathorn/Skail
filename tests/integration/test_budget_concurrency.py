from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import Barrier

from skail.routing.budget import BudgetBlockedError, BudgetLedger, ReservationRequest
from skail.sessions import Journal


def test_concurrent_reservations_cannot_overcommit_the_run(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "skail.sqlite")
    journal.migrate()
    now = datetime(2026, 9, 2, tzinfo=UTC)
    journal.create_session(session_id="session", title="race", created_at=now)
    journal.create_run(
        run_id="run",
        session_id="session",
        status="running",
        budget_limit_usd=Decimal("1.00"),
        created_at=now,
    )
    ledger = BudgetLedger(journal)
    barrier = Barrier(2)

    def reserve(index: int) -> bool:
        barrier.wait()
        try:
            ledger.reserve(
                ReservationRequest(
                    reservation_id=f"r-{index}",
                    run_id="run",
                    task_id=None,
                    amount_usd=Decimal("0.70"),
                    idempotency_key=f"reserve-{index}",
                )
            )
        except BudgetBlockedError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(reserve, (1, 2)))
    assert sorted(results) == [False, True]
    assert ledger.snapshot("run").reserved_usd == Decimal("0.70")
