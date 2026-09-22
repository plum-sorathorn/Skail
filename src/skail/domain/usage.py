from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class UsageAuthority(StrEnum):
    AUTHORITATIVE_ACTUAL = "authoritative_actual"
    ESTIMATED_ACTUAL = "estimated_actual"
    # TODO(flag/D-12): part 2 remains. Until the estimate-on-reconcile
    # resolution lands, unknown usage stays NULL with authority='unknown' (the
    # event's usage fields stay None; provider_calls keeps the journaled
    # truth). Remaining work: add UsageAuthority.RECONCILED_ESTIMATE and settle
    # ambiguous calls to the frozen estimated_attempt_cost_usd WITHOUT
    # overwriting `unknown`, plus a resolution CLI verb.


class NormalizedUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: Decimal = Field(ge=0)
    authority: UsageAuthority

    @field_serializer("cost_usd")
    def serialize_cost(self, value: Decimal) -> str:
        return format(value, "f")
