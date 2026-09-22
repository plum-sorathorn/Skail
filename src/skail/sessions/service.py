from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from skail.config.paths import session_lock_path
from skail.domain.ids import new_session_id
from skail.domain.sessions import (
    SessionRecord,
    SessionStatus,
    transition_session,
)
from skail.sessions.checkpoints import CheckpointStore
from skail.sessions.journal import Journal
from skail.sessions.locking import FileLockBusyError, process_file_lock
from skail.sessions.recovery import RecoveryResult, recover_session


class SessionLockedError(RuntimeError):
    """Raised when an operation cannot proceed because the session process lock is held."""
    pass


class SessionResumeResult:
    def __init__(
        self,
        *,
        ok: bool,
        session: SessionRecord,
        interrupted_call_keys: tuple[str, ...],
        pending_approval_ids: tuple[str, ...],
        released_reservation_ids: tuple[str, ...],
        recovery_error: Any | None = None,
    ) -> None:
        self.ok = ok
        self.session = session
        self.interrupted_call_keys = interrupted_call_keys
        self.pending_approval_ids = pending_approval_ids
        self.released_reservation_ids = released_reservation_ids
        self.recovery_error = recovery_error


class SessionService:
    def __init__(
        self,
        *,
        journal: Journal,
        checkpoints: CheckpointStore,
        sessions_dir: Path | None = None,
    ) -> None:
        self.journal = journal
        self.checkpoints = checkpoints
        self.sessions_dir = sessions_dir

    def _lock_path(self, session_id: str) -> Path:
        return session_lock_path(session_id, base_dir=self.sessions_dir)

    @contextmanager
    def session_lock(self, session_id: str, timeout_sec: float = 5.0) -> Iterator[None]:
        lock_file = self._lock_path(session_id)
        try:
            with process_file_lock(lock_file, timeout_sec=timeout_sec):
                yield
        except FileLockBusyError as exc:
            raise SessionLockedError(
                f"session {session_id} is locked by another process"
            ) from exc

    def create_session(
        self,
        *,
        title: str = "New Session",
        session_id: str | None = None,
        status: SessionStatus = SessionStatus.ACTIVE,
    ) -> SessionRecord:
        sid = session_id or str(new_session_id())
        now = datetime.now(UTC)
        self.journal.create_session(
            session_id=sid,
            title=title,
            created_at=now,
            status=status.value,
        )
        return SessionRecord(
            session_id=sid,
            title=title,
            status=status,
            created_at=now,
            updated_at=now,
        )

    def get_session(self, session_id: str) -> SessionRecord:
        summary = self.journal.get_session_record(session_id)
        return SessionRecord(
            session_id=summary.session_id,
            title=summary.title,
            status=SessionStatus(summary.status),
            created_at=datetime.fromisoformat(summary.created_at),
            updated_at=datetime.fromisoformat(summary.updated_at),
        )

    def list_sessions(self) -> list[SessionRecord]:
        summaries = self.journal.list_sessions()
        return [
            SessionRecord(
                session_id=s.session_id,
                title=s.title,
                status=SessionStatus(s.status),
                created_at=datetime.fromisoformat(s.created_at),
                updated_at=datetime.fromisoformat(s.updated_at),
            )
            for s in summaries
        ]

    def transition_session(
        self, session_id: str, target_status: SessionStatus | str
    ) -> SessionRecord:
        current = self.get_session(session_id)
        new_status = transition_session(current.status, target_status)
        now = datetime.now(UTC)
        self.journal.update_session_status(
            session_id=session_id,
            status=new_status.value,
            updated_at=now,
        )
        return SessionRecord(
            session_id=session_id,
            title=current.title,
            status=new_status,
            created_at=current.created_at,
            updated_at=now,
        )

    def resume_session(self, session_id: str) -> SessionResumeResult:
        with self.session_lock(session_id):
            recovery_result: RecoveryResult = recover_session(
                journal=self.journal,
                checkpoints=self.checkpoints,
                session_id=session_id,
            )
            if not recovery_result.ok:
                current = self.get_session(session_id)
                return SessionResumeResult(
                    ok=False,
                    session=current,
                    interrupted_call_keys=(),
                    pending_approval_ids=(),
                    released_reservation_ids=(),
                    recovery_error=recovery_result.error,
                )

            current = self.get_session(session_id)
            if current.status != SessionStatus.ACTIVE:
                current = self.transition_session(session_id, SessionStatus.ACTIVE)

            return SessionResumeResult(
                ok=True,
                session=current,
                interrupted_call_keys=recovery_result.interrupted_call_keys,
                pending_approval_ids=recovery_result.pending_approval_ids,
                released_reservation_ids=recovery_result.released_reservation_ids,
            )
