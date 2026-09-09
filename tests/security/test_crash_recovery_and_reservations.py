from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from rudder.domain.ids import new_run_id, new_session_id, new_task_id
from rudder.domain.usage import NormalizedUsage, UsageAuthority
from rudder.routing.budget import BudgetLedger, ReservationRequest
from rudder.runtime.leases import WorkspaceLeaseManager
from rudder.sessions.journal import Journal
from rudder.sessions.locking import FileLockBusyError, process_file_lock


def test_budget_reservation_and_idempotent_settlement_on_crash_recovery(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.sqlite")
    journal.migrate()
    session_id = str(new_session_id())
    run_id = str(new_run_id())
    task_id = str(new_task_id())
    now = datetime.now(UTC)

    journal.create_session(session_id=session_id, title="Recovery", created_at=now)
    journal.create_run(
        run_id=run_id,
        session_id=session_id,
        status="running",
        budget_limit_usd=Decimal("5.00"),
        created_at=now,
    )
    journal.create_task(
        task_id=task_id,
        run_id=run_id,
        description="task",
        status="running",
        idempotency_key="key-t",
        created_at=now,
    )
    ledger = BudgetLedger(journal)

    # Reserve $1.50
    req = ReservationRequest(
        reservation_id="res-rec-1",
        run_id=run_id,
        task_id=task_id,
        amount_usd=Decimal("1.50"),
        idempotency_key="req-1",
    )
    res = ledger.reserve(req)
    assert res.reservation_id == "res-rec-1"
    snap = ledger.snapshot(run_id)
    assert snap.reserved_usd == Decimal("1.50")
    assert snap.available_usd == Decimal("3.50")

    # Simulate crash before completion, then recovery and settlement
    usage = NormalizedUsage(
        input_tokens=1000,
        output_tokens=500,
        cost_usd=Decimal("1.20"),
        authority=UsageAuthority.AUTHORITATIVE_ACTUAL,
    )

    ledger.settle("res-rec-1", usage_id="use-1", usage=usage, idempotency_key="settle-1")
    snap = ledger.snapshot(run_id)
    assert snap.reserved_usd == Decimal("0.00")
    assert snap.authoritative_actual_usd == Decimal("1.20")
    assert snap.available_usd == Decimal("3.80")

    # Idempotent replay does not double-deduct
    ledger.settle("res-rec-1", usage_id="use-1", usage=usage, idempotency_key="settle-1")
    assert ledger.snapshot(run_id).authoritative_actual_usd == Decimal("1.20")

    # Conflicting replay after settlement raises error
    with pytest.raises(Exception):
        ledger.settle("res-rec-1", usage_id="use-2", usage=usage, idempotency_key="settle-conflict")


def test_write_lease_released_on_cancellation_or_crash() -> None:
    manager = WorkspaceLeaseManager()
    owner_1 = "task-1"
    owner_2 = "task-2"

    with manager.hold(owner_1):
        assert manager.holder == owner_1

    assert manager.holder is None

    # Simulate process crash while holding lease
    manager._holder = owner_1
    manager._depth = 1
    assert manager.holder == owner_1

    # Stale recovery recovers the lease safely
    recovered = manager.recover_stale(owner_1)
    assert recovered
    assert manager.holder is None

    # Subsequent task acquires cleanly
    with manager.hold(owner_2):
        assert manager.holder == owner_2


def test_session_file_lock_prevents_concurrent_process_mutation(tmp_path: Path) -> None:
    lock_file = tmp_path / "session.lock"

    with process_file_lock(lock_file, timeout_sec=0.5):
        # Second process attempting lock will time out with FileLockBusyError
        with pytest.raises(FileLockBusyError):
            with process_file_lock(lock_file, timeout_sec=0.05):
                pass

    # Once the first lock exits, acquiring lock succeeds cleanly
    with process_file_lock(lock_file, timeout_sec=0.1):
        pass


def test_session_file_lock_waits_for_an_in_process_writer(tmp_path: Path) -> None:
    lock_file = tmp_path / "session.lock"
    first_acquired = threading.Event()
    release_first = threading.Event()
    second_acquired = threading.Event()

    def first_writer() -> None:
        with process_file_lock(lock_file):
            first_acquired.set()
            assert release_first.wait(timeout=1)

    def second_writer() -> None:
        assert first_acquired.wait(timeout=1)
        with process_file_lock(lock_file):
            second_acquired.set()

    first = threading.Thread(target=first_writer)
    second = threading.Thread(target=second_writer)
    first.start()
    second.start()
    assert first_acquired.wait(timeout=1)
    time.sleep(0.05)
    assert not second_acquired.is_set()
    release_first.set()
    first.join(timeout=1)
    second.join(timeout=1)
    assert not first.is_alive()
    assert not second.is_alive()
    assert second_acquired.is_set()
