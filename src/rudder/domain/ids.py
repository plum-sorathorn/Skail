from __future__ import annotations

from typing import NewType
from uuid import UUID, uuid4

SessionId = NewType("SessionId", str)
RunId = NewType("RunId", str)
TaskId = NewType("TaskId", str)
AttemptId = NewType("AttemptId", str)
AssignmentId = NewType("AssignmentId", str)
EventId = NewType("EventId", str)
ReservationId = NewType("ReservationId", str)
ApprovalId = NewType("ApprovalId", str)


def new_uuid4() -> str:
    return str(uuid4())


def ensure_uuid4(value: str) -> str:
    parsed = UUID(value)
    if parsed.version != 4 or str(parsed) != value.lower():
        raise ValueError("identifier must be a canonical UUID4 string")
    return str(parsed)


def new_session_id() -> SessionId:
    return SessionId(new_uuid4())


def new_run_id() -> RunId:
    return RunId(new_uuid4())


def new_task_id() -> TaskId:
    return TaskId(new_uuid4())


def new_attempt_id() -> AttemptId:
    return AttemptId(new_uuid4())


def new_assignment_id() -> AssignmentId:
    return AssignmentId(new_uuid4())


def new_event_id() -> EventId:
    return EventId(new_uuid4())
