from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from rudder.domain.ids import AssignmentId, ReservationId, TaskId, ensure_uuid4


class RoutingMode(StrEnum):
    AUTO = "auto"
    ECONOMY = "economy"
    QUALITY = "quality"
    MANUAL = "manual"


class TaskAssignment(BaseModel):
    model_config = ConfigDict(frozen=True)

    assignment_id: AssignmentId
    task_id: TaskId
    attempt_number: Literal[1, 2]
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    routing_mode: RoutingMode
    capability_floor: float | None = Field(default=None, ge=0, le=1)
    estimated_attempt_cost_usd: Decimal = Field(ge=0)
    reservation_id: ReservationId
    explanation: tuple[str, ...] = ()
    catalog_revision: str = Field(min_length=1)

    def model_post_init(self, context: object) -> None:
        del context
        ensure_uuid4(str(self.assignment_id))
        ensure_uuid4(str(self.task_id))
        ensure_uuid4(str(self.reservation_id))

    @field_serializer("estimated_attempt_cost_usd")
    def serialize_cost(self, value: Decimal) -> str:
        return format(value, "f")
