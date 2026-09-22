from __future__ import annotations

import gc
import sqlite3
import weakref
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from skail.domain.events import DiagnosticPayload, EventEnvelope
from skail.domain.ids import RunId, SessionId, new_event_id
from skail.sessions import Journal

NOW = datetime(2026, 9, 16, tzinfo=UTC)
SESSION_ID = "11111111-1111-4111-8111-111111111111"
RUN_ID = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def journal(tmp_path: Path) -> Journal:
    result = Journal(tmp_path / "journal.sqlite", busy_timeout_ms=1234)
    result.migrate()
    result.create_session(session_id=SESSION_ID, title="Lifecycle", created_at=NOW)
    result.create_run(
        run_id=RUN_ID, session_id=SESSION_ID, status="running",
        budget_limit_usd=None, created_at=NOW,
    )
    return result


def test_sequential_appends_reuse_connections_and_commit_each_event(journal: Journal) -> None:
    # Connection creation is the resource budget behind the persistence regression;
    # checking it avoids a hardware-dependent wall-clock threshold in the test suite.
    with closing(sqlite3.connect(journal.path)) as observer:
        with patch("skail.sessions.journal.sqlite3.connect", wraps=sqlite3.connect) as connect:
            for sequence in range(1, 13):
                journal.append_event(event=EventEnvelope(
                    event_id=new_event_id(), session_id=SessionId(SESSION_ID),
                    run_id=RunId(RUN_ID), sequence=sequence, occurred_at=NOW,
                    type="diagnostic.error",
                    payload=DiagnosticPayload(code="test.event", summary="Persisted"),
                ))
                assert observer.execute("SELECT count(*) FROM events").fetchone()[0] == sequence
            assert connect.call_count <= 2


def test_close_releases_idle_resources_and_allows_reopen(journal: Journal) -> None:
    with journal.transaction() as transaction:
        retained = transaction.connection
    journal.close()
    journal.close()
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        retained.execute("SELECT 1")
    assert journal.get_session_record(SESSION_ID).title == "Lifecycle"


def test_close_during_transaction_defers_release_until_commit(journal: Journal) -> None:
    with journal.transaction() as transaction:
        retained = transaction.connection
        journal.close()
        transaction.create_session("after-close", "Committed", NOW)
        assert retained.execute("SELECT 1").fetchone()[0] == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        retained.execute("SELECT 1")
    assert journal.get_session_record("after-close").title == "Committed"


def test_collection_releases_idle_connection(journal: Journal) -> None:
    # A separate owner avoids pytest's fixture cache keeping the owner alive.
    owner = Journal(journal.path)
    with owner.transaction() as transaction:
        retained = transaction.connection
    assert retained.execute("SELECT 1").fetchone()[0] == 1
    owner_ref = weakref.ref(owner)
    del owner
    gc.collect()
    assert owner_ref() is None
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        retained.execute("SELECT 1")


def test_reused_connections_preserve_sqlite_safety_settings(journal: Journal) -> None:
    for _ in range(3):
        with journal.transaction() as transaction:
            connection = transaction.connection
            assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2
            assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 1234


def test_nested_and_outer_rollbacks_preserve_callback_and_commit_boundaries(
    journal: Journal,
) -> None:
    callbacks: list[str] = []
    with journal.transaction() as outer:
        outer.create_session("outer", "Kept", NOW)
        outer.after_commit(lambda: callbacks.append("outer"))
        with pytest.raises(ValueError, match="nested"):
            with journal.transaction() as nested:
                nested.create_session("nested", "Discarded", NOW)
                nested.after_commit(lambda: callbacks.append("nested"))
                raise ValueError("nested")
        assert callbacks == []
    assert callbacks == ["outer"]
    with pytest.raises(ValueError, match="outer"):
        with journal.transaction() as failed:
            failed.create_session("failed", "Discarded", NOW)
            failed.after_commit(lambda: callbacks.append("failed"))
            raise ValueError("outer")
    assert callbacks == ["outer"]
    assert {row.session_id for row in journal.list_sessions()} == {SESSION_ID, "outer"}


def test_concurrent_reader_does_not_share_active_transaction(journal: Journal) -> None:
    with ThreadPoolExecutor(max_workers=1) as workers:
        with journal.transaction() as transaction:
            transaction.create_session("pending", "Uncommitted", NOW)
            rows = workers.submit(journal.list_sessions).result(timeout=5)
            assert {row.session_id for row in rows} == {SESSION_ID}
        rows = workers.submit(journal.list_sessions).result(timeout=5)
        assert {row.session_id for row in rows} == {SESSION_ID, "pending"}


def test_callback_failure_leaves_committed_state_and_reusable_journal(journal: Journal) -> None:
    def fail_callback() -> None:
        raise ValueError("delivery failed")

    with pytest.raises(ValueError, match="delivery failed"):
        with journal.transaction() as transaction:
            transaction.create_session("committed", "Kept", NOW)
            transaction.after_commit(fail_callback)
    assert journal.get_session_record("committed").title == "Kept"
    journal.create_session(session_id="next", title="Still usable", created_at=NOW)
    assert journal.get_session_record("next").title == "Still usable"
