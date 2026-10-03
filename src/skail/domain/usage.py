from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class UsageAuthority(StrEnum):
    AUTHORITATIVE_ACTUAL = "authoritative_actual"
    TOKEN_DERIVED_ESTIMATE = "token_derived_estimate"
    CONSERVATIVE_ESTIMATE = "conservative_estimate"
    UNKNOWN = "unknown"
    ESTIMATED_ACTUAL = "estimated_actual"
    RECONCILED_ESTIMATE = "reconciled_estimate"


class NormalizedUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    cost_usd: Decimal | None = Field(default=None, ge=0)
    authority: UsageAuthority

    @field_serializer("cost_usd")
    def serialize_cost(self, value: Decimal | None) -> str | None:
        return None if value is None else format(value, "f")
