from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from rudder.domain.ids import (
    AttemptId,
    EventId,
    InvocationId,
    RunId,
    SessionId,
    TaskId,
    ensure_uuid4,
)

REDACTED = "[REDACTED]"
_SENSITIVE_KEYS = frozenset({"api_key", "apikey", "authorization", "password", "secret", "token"})
ALLOWED_EVENT_TYPES = frozenset(
    {
        "session.created",
        "session.started",
        "session.idle",
        "session.interrupted",
        "session.completed",
        "session.archived",
        "run.started",
        "run.completed",
        "run.failed",
        "run.cancelled",
        "run.blocked",
        "lead.delta",
        "lead.completed",
        "model.started",
        "model.delta",
        "model.completed",
        "model.failed",
        "task.proposed",
        "task.queued",
        "task.started",
        "task.succeeded",
        "task.failed",
        "task.blocked",
        "task.budget_blocked",
        "task.cancelled",
        "task.returned_to_lead",
        "plan.admitted",
        "plan.revised",
        "plan.node_admitted",
        "plan.node_ready",
        "plan.node_launching",
        "plan.node_running",
        "plan.node_succeeded",
        "plan.node_failed",
        "plan.node_blocked",
        "plan.node_cancelled",
        "route.selected",
        "route.failed",
        "route.fallback",
        "route.escalated",
        "tool.requested",
        "tool.approved",
        "tool.rejected",
        "tool.started",
        "tool.completed",
        "tool.failed",
        "budget.reserved",
        "budget.released",
        "budget.charged",
        "budget.warned",
        "budget.blocked",
        "checkpoint.created",
        "checkpoint.resumed",
        "checkpoint.compacted",
        "user.question",
        "user.answer",
        "user.cancellation",
        "invariant.failed",
        "diagnostic.error",
        "diagnostic.warning",
    }
)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: REDACTED if str(key).lower() in _SENSITIVE_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


@dataclass(frozen=True)
class SecretRedactor:
    secrets: tuple[str, ...] = ()

    def __init__(self, secrets: tuple[str, ...] | list[str] = ()) -> None:
        object.__setattr__(
            self,
            "secrets",
            tuple(sorted({secret for secret in secrets if secret}, key=len, reverse=True)),
        )

    def scrub(self, value: Any) -> Any:
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, REDACTED)
            return value
        if isinstance(value, dict):
            return {
                self.scrub(key) if isinstance(key, str) else key: self.scrub(item)
                for key, item in value.items()
            }
        if isinstance(value, tuple):
            return tuple(self.scrub(item) for item in value)
        if isinstance(value, list):
            return [self.scrub(item) for item in value]
        if isinstance(value, (set, frozenset)):
            return [self.scrub(item) for item in sorted(value, key=repr)]
        if isinstance(value, BaseModel):
            try:
                data = {k: self.scrub(v) for k, v in value.__dict__.items()}
                return value.model_copy(update=data)
            except Exception:
                return value
        return value


class PayloadBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LifecyclePayload(PayloadBase):
    family: Literal["lifecycle"] = "lifecycle"
    status: str


class ModelPayload(PayloadBase):
    family: Literal["model"] = "model"
    model: str
    delta: str | None = None


class TaskPayload(PayloadBase):
    family: Literal["task"] = "task"
    status: str
    profile: str | None = None


class PlanPayload(PayloadBase):
    family: Literal["plan"] = "plan"
    action: str
    plan_id: str
    revision: int = Field(ge=1)
    node_id: str | None = None

    @model_validator(mode="after")
    def validate_ids(self) -> PlanPayload:
        ensure_uuid4(self.plan_id)
        if self.node_id is not None:
            ensure_uuid4(self.node_id)
        return self


class RoutePayload(PayloadBase):
    family: Literal["route"] = "route"
    action: str
    assignment_id: str | None = None


class ToolPayload(PayloadBase):
    family: Literal["tool"] = "tool"
    tool: str
    status: str


class BudgetPayload(PayloadBase):
    family: Literal["budget"] = "budget"
    action: str
    amount_usd: Decimal

    @field_serializer("amount_usd")
    def serialize_amount(self, value: Decimal) -> str:
        return format(value, "f")


class CheckpointPayload(PayloadBase):
    family: Literal["checkpoint"] = "checkpoint"
    action: str
    checkpoint_id: str | None = None


class UserPayload(PayloadBase):
    family: Literal["user"] = "user"
    action: str
    content: str | None = None


class DiagnosticPayload(PayloadBase):
    family: Literal["diagnostic"] = "diagnostic"
    code: str
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def redact_details(cls, value: Any) -> Any:
        return redact(value)


EventPayload = Annotated[
    LifecyclePayload
    | ModelPayload
    | TaskPayload
    | PlanPayload
    | RoutePayload
    | ToolPayload
    | BudgetPayload
    | CheckpointPayload
    | UserPayload
    | DiagnosticPayload,
    Field(discriminator="family"),
]


class EventEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    event_id: EventId
    session_id: SessionId
    run_id: RunId
    invocation_id: InvocationId | None = None
    task_id: TaskId | None = None
    attempt_id: AttemptId | None = None
    sequence: int = Field(ge=1)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    type: str = Field(min_length=1)
    payload: EventPayload

    @model_validator(mode="after")
    def validate_envelope(self) -> EventEnvelope:
        for required_identifier in (self.event_id, self.session_id, self.run_id):
            ensure_uuid4(str(required_identifier))
        for optional_identifier in (self.invocation_id, self.task_id, self.attempt_id):
            if optional_identifier is not None:
                ensure_uuid4(str(optional_identifier))
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must include a timezone")
        if self.type not in ALLOWED_EVENT_TYPES:
            raise ValueError(f"unknown event type: {self.type}")
        prefix = self.type.split(".", maxsplit=1)[0]
        expected_family = {
            "session": "lifecycle",
            "run": "lifecycle",
            "lead": "model",
            "model": "model",
            "task": "task",
            "plan": "plan",
            "route": "route",
            "tool": "tool",
            "budget": "budget",
            "checkpoint": "checkpoint",
            "user": "user",
            "invariant": "diagnostic",
            "diagnostic": "diagnostic",
        }.get(prefix)
        assert expected_family is not None
        if self.payload.family != expected_family:
            raise ValueError(
                f"event type {self.type} requires payload family {expected_family}"
            )
        suffix = self.type.split(".", maxsplit=1)[1]
        state_value: str | None = None
        if isinstance(self.payload, (LifecyclePayload, TaskPayload, ToolPayload)):
            state_value = self.payload.status
        elif isinstance(
            self.payload,
            (RoutePayload, PlanPayload, BudgetPayload, CheckpointPayload, UserPayload),
        ):
            state_value = self.payload.action
        if state_value is not None and state_value != suffix:
            raise ValueError(
                f"event type {self.type} conflicts with payload state {state_value}"
            )
        return self

    def redacted(self, redactor: SecretRedactor) -> EventEnvelope:
        return EventEnvelope.model_validate(redactor.scrub(self.model_dump(mode="json")))

    def to_json(self, redactor: SecretRedactor | None = None) -> str:
        value = self.model_dump(mode="json")
        if redactor is not None:
            value = redactor.scrub(value)
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)

    @classmethod
    def from_json(cls, value: str) -> EventEnvelope:
        return cls.model_validate_json(value)
