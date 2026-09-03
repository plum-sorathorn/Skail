from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from rudder.domain.ids import AttemptId, RunId, TaskId, ensure_uuid4
from rudder.domain.routing import TaskAssignment
from rudder.domain.usage import NormalizedUsage


class DomainTransitionError(ValueError):
    pass


class TaskStatus(StrEnum):
    PROPOSED = "proposed"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETURNED_TO_LEAD = "returned_to_lead"
    BLOCKED = "blocked"
    BUDGET_BLOCKED = "budget_blocked"
    CANCELLED = "cancelled"


class AttemptStatus(StrEnum):
    ASSIGNED = "assigned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


TERMINAL_TASK_STATUSES = frozenset(
    {
        TaskStatus.SUCCEEDED,
        TaskStatus.RETURNED_TO_LEAD,
        TaskStatus.BLOCKED,
        TaskStatus.BUDGET_BLOCKED,
        TaskStatus.CANCELLED,
    }
)

_TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PROPOSED: frozenset({TaskStatus.QUEUED, TaskStatus.BLOCKED}),
    TaskStatus.QUEUED: frozenset({TaskStatus.RUNNING, TaskStatus.BLOCKED, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.SUCCEEDED,
            TaskStatus.FAILED,
            TaskStatus.RETURNED_TO_LEAD,
            TaskStatus.BLOCKED,
            TaskStatus.BUDGET_BLOCKED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.FAILED: frozenset({TaskStatus.QUEUED, TaskStatus.RETURNED_TO_LEAD}),
}

_ATTEMPT_TRANSITIONS: dict[AttemptStatus, frozenset[AttemptStatus]] = {
    AttemptStatus.ASSIGNED: frozenset(
        {
            AttemptStatus.RUNNING,
            AttemptStatus.BLOCKED,
            AttemptStatus.CANCELLED,
            AttemptStatus.INTERRUPTED,
        }
    ),
    AttemptStatus.RUNNING: frozenset(
        {
            AttemptStatus.SUCCEEDED,
            AttemptStatus.FAILED,
            AttemptStatus.BLOCKED,
            AttemptStatus.CANCELLED,
            AttemptStatus.INTERRUPTED,
        }
    ),
}


def transition_task(
    current: TaskStatus, target: TaskStatus, *, attempt_number: int = 1
) -> TaskStatus:
    if current == target and current in TERMINAL_TASK_STATUSES:
        return current
    if target not in _TASK_TRANSITIONS.get(current, frozenset()):
        raise DomainTransitionError(f"illegal task transition: {current} -> {target}")
    if current is TaskStatus.FAILED and target is TaskStatus.QUEUED and attempt_number != 1:
        raise DomainTransitionError("only attempt one may transition a failed task back to queued")
    return target


def transition_attempt(current: AttemptStatus, target: AttemptStatus) -> AttemptStatus:
    if current == target and current not in {AttemptStatus.ASSIGNED, AttemptStatus.RUNNING}:
        return current
    if target not in _ATTEMPT_TRANSITIONS.get(current, frozenset()):
        raise DomainTransitionError(f"illegal attempt transition: {current} -> {target}")
    return target


class TaskRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    description: str = Field(min_length=1, max_length=20_000)
    profile: str = "general-purpose"
    success_criteria: tuple[str, ...] = ()
    depends_on: tuple[TaskId, ...] = ()
    write_scope: tuple[str, ...] = ()
    model_policy: ModelConstraint | None = None
    budget_usd: Decimal | None = Field(default=None, ge=0)
    background: bool = False

    @field_serializer("budget_usd")
    def serialize_budget(self, value: Decimal | None) -> str | None:
        return None if value is None else format(value, "f")


class TaskSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: TaskId
    run_id: RunId
    parent_task_id: TaskId | None = None
    depth: int = Field(ge=0)
    fingerprint: str = Field(min_length=1)
    request: TaskRequest
    requirements: CapabilityRequirements
    permission_set: PermissionSet

    def model_post_init(self, context: object) -> None:
        del context
        ensure_uuid4(str(self.task_id))
        ensure_uuid4(str(self.run_id))
        if self.parent_task_id is not None:
            ensure_uuid4(str(self.parent_task_id))


class FailureReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    summary: str
    evidence: tuple[str, ...] = ()


class ModelConstraint(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider: str | None = None
    model: str | None = None
    minimum_capability: float | None = Field(default=None, ge=0, le=1)


class CapabilityRequirements(BaseModel):
    model_config = ConfigDict(frozen=True)
    capability_floor: float | None = Field(ge=0, le=1)
    tools_required: bool = False
    structured_output_required: bool = False
    minimum_context_tokens: int = Field(default=0, ge=0)
    minimum_output_tokens: int = Field(default=0, ge=0)
    modalities: tuple[str, ...] = ("text",)


class PermissionSet(BaseModel):
    model_config = ConfigDict(frozen=True)
    read: bool = True
    write: bool = False
    execute: bool = False
    allowed_paths: tuple[str, ...] = ()


class TaskAttempt(BaseModel):
    model_config = ConfigDict(frozen=True)

    attempt_id: AttemptId
    assignment: TaskAssignment
    started_at: datetime
    ended_at: datetime | None = None
    status: AttemptStatus
    failure: FailureReport | None = None
    actual_usage: NormalizedUsage | None = None

    @model_validator(mode="after")
    def validate_attempt(self) -> TaskAttempt:
        ensure_uuid4(str(self.attempt_id))
        if self.assignment.attempt_number == 2 and self.status is AttemptStatus.ASSIGNED:
            return self
        return self


class ArtifactRef(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: str
    path: str
    digest: str | None = None


class VerificationResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    criterion: str
    passed: bool
    evidence: str | None = None


class AttemptSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    attempt_id: AttemptId
    number: Literal[1, 2]
    status: AttemptStatus
    model: str


class TaskResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: TaskId
    status: Literal[
        "succeeded",
        "failed",
        "blocked",
        "cancelled",
        "budget_blocked",
        "returned_to_lead",
    ]
    summary: str
    artifacts: tuple[ArtifactRef, ...] = ()
    verification: tuple[VerificationResult, ...] = ()
    attempts: tuple[AttemptSummary, ...] = ()
    changed_paths: tuple[str, ...] = ()
    follow_up: str | None = None

    def model_post_init(self, context: object) -> None:
        del context
        ensure_uuid4(str(self.task_id))


TaskRequest.model_rebuild()
TaskSpec.model_rebuild()
