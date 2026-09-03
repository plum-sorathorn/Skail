from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class SessionTransitionError(ValueError):
    """Raised when an illegal session state transition is attempted."""
    pass


class SessionStatus(StrEnum):
    ACTIVE = "active"
    IDLE = "idle"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"
    ARCHIVED = "archived"


_SESSION_TRANSITIONS: dict[SessionStatus, frozenset[SessionStatus]] = {
    SessionStatus.ACTIVE: frozenset(
        {
            SessionStatus.IDLE,
            SessionStatus.INTERRUPTED,
            SessionStatus.COMPLETED,
            SessionStatus.ARCHIVED,
        }
    ),
    SessionStatus.IDLE: frozenset(
        {
            SessionStatus.ACTIVE,
            SessionStatus.COMPLETED,
            SessionStatus.ARCHIVED,
        }
    ),
    SessionStatus.INTERRUPTED: frozenset(
        {
            SessionStatus.ACTIVE,
            SessionStatus.COMPLETED,
            SessionStatus.ARCHIVED,
        }
    ),
    SessionStatus.COMPLETED: frozenset(
        {
            SessionStatus.ACTIVE,
            SessionStatus.ARCHIVED,
        }
    ),
    SessionStatus.ARCHIVED: frozenset(),
}


def transition_session(
    current: SessionStatus | str, target: SessionStatus | str
) -> SessionStatus:
    current_status = SessionStatus(current)
    target_status = SessionStatus(target)
    if current_status == target_status:
        return current_status
    allowed = _SESSION_TRANSITIONS.get(current_status, frozenset())
    if target_status not in allowed:
        raise SessionTransitionError(
            f"illegal session transition: {current_status} -> {target_status}"
        )
    return target_status


class SessionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    title: str
    status: SessionStatus
    created_at: datetime
    updated_at: datetime
