from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import Barrier, Event

import pytest

from skail.sessions import Journal, JournalBusyError

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def _seed_run(database: Path) -> None:
    journal = Journal(database)
    journal.migrate()
    journal.create_session(session_id="session-1", title="Concurrency", created_at=NOW)
    journal.create_run(
        run_id="run-1",
        session_id="session-1",
        status="running",
        budget_limit_usd=Decimal("3.00"),
        created_at=NOW,
    )


def test_concurrent_idempotent_writers_do_not_duplicate_usage(tmp_path: Path) -> None:
    database = tmp_path / "skail.sqlite"
    _seed_run(database)
    barrier = Barrier(8)

    def record_same_usage(worker: int) -> None:
        journal = Journal(database, busy_timeout_ms=2_000, max_retries=4)
        barrier.wait(timeout=5)
        journal.record_usage(
            usage_id="usage-provider-call-1",
            run_id="run-1",
            task_id=None,
            amount_usd=Decimal("0.10"),
            authoritative=False,
            idempotency_key="provider-call-1",
            created_at=NOW,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(record_same_usage, worker) for worker in range(8)]
        for future in futures:
            future.result(timeout=10)

    snapshot = Journal(database).get_session_snapshot("session-1")
    assert len(snapshot.usage_records) == 1
    assert snapshot.usage_records[0].idempotency_key == "provider-call-1"
    assert snapshot.usage_records[0].amount_usd == Decimal("0.10")


def test_concurrent_reservations_are_each_committed_once(tmp_path: Path) -> None:
    database = tmp_path / "skail.sqlite"
    _seed_run(database)
    barrier = Barrier(6)

    def reserve(worker: int) -> None:
        journal = Journal(database, busy_timeout_ms=2_000, max_retries=4)
        barrier.wait(timeout=5)
        journal.create_reservation(
            reservation_id=f"reservation-{worker}",
            run_id="run-1",
            task_id=None,
            amount_usd=Decimal("0.10"),
            status="reserved",
            idempotency_key=f"reservation-key-{worker}",
            created_at=NOW,
        )

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(reserve, worker) for worker in range(6)]
        for future in futures:
            future.result(timeout=10)

    reservations = Journal(database).get_session_snapshot(
        "session-1"
    ).budget_reservations
    assert len(reservations) == 6
    assert {record.idempotency_key for record in reservations} == {
        f"reservation-key-{worker}" for worker in range(6)
    }


def test_busy_retry_policy_has_a_deterministic_bound(tmp_path: Path) -> None:
    database = tmp_path / "skail.sqlite"
    _seed_run(database)
    lock_holder = Journal(database)
    writer_started = Event()

    def blocked_write() -> None:
        writer_started.set()
        Journal(database, busy_timeout_ms=0, max_retries=0).record_usage(
            usage_id="blocked-usage",
            run_id="run-1",
            task_id=None,
            amount_usd=Decimal("0.01"),
            authoritative=False,
            idempotency_key="blocked-provider-call",
            created_at=NOW,
        )

    with lock_holder.transaction() as transaction:
        transaction.create_reservation(
            reservation_id="lock-holder",
            run_id="run-1",
            task_id=None,
            amount_usd=Decimal("0.01"),
            status="reserved",
            idempotency_key="lock-holder-key",
            created_at=NOW,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(blocked_write)
            assert writer_started.wait(timeout=2)
            with pytest.raises(JournalBusyError):
                future.result(timeout=2)

    assert Journal(database).get_session_snapshot("session-1").usage_records == ()
