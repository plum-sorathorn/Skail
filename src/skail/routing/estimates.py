from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_MILLION = Decimal("1000000")
_USD_QUANTUM = Decimal("0.000001")


class AttemptEstimateInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    context_tokens: int = Field(ge=0)
    tool_result_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(ge=0)
    expected_calls: int = Field(default=1, ge=1)
    input_usd_per_million: Decimal | None = Field(ge=0)
    output_usd_per_million: Decimal | None = Field(ge=0)
    cached_input_usd_per_million: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def cached_tokens_fit_context(self) -> AttemptEstimateInput:
        if self.cached_input_tokens > self.context_tokens:
            raise ValueError("cached_input_tokens cannot exceed context_tokens")
        return self


class AttemptCostEstimate(BaseModel):
    model_config = ConfigDict(frozen=True)

    estimated_input_tokens: int
    estimated_output_tokens: int
    expected_calls: int
    cost_usd: Decimal | None
    missing_price_fields: tuple[str, ...] = ()
    assumptions: tuple[str, ...]


def estimate_attempt_cost(value: AttemptEstimateInput) -> AttemptCostEstimate:
    missing = tuple(
        name
        for name, price in (
            ("input_usd_per_million", value.input_usd_per_million),
            ("output_usd_per_million", value.output_usd_per_million),
        )
        if price is None
    )
    input_tokens = value.context_tokens + value.tool_result_tokens
    cost: Decimal | None = None
    if not missing:
        assert value.input_usd_per_million is not None
        assert value.output_usd_per_million is not None
        cached_price = (
            value.input_usd_per_million
            if value.cached_input_usd_per_million is None
            else value.cached_input_usd_per_million
        )
        ordinary_input = input_tokens - value.cached_input_tokens
        per_call = (
            Decimal(ordinary_input) * value.input_usd_per_million
            + Decimal(value.cached_input_tokens) * cached_price
            + Decimal(value.output_tokens) * value.output_usd_per_million
        ) / _MILLION
        cost = (per_call * value.expected_calls).quantize(_USD_QUANTUM, rounding=ROUND_HALF_UP)
    assumptions = (
        f"context_tokens={value.context_tokens}",
        f"tool_result_tokens={value.tool_result_tokens}",
        f"cached_input_tokens={value.cached_input_tokens}",
        f"output_tokens={value.output_tokens}",
        f"expected_calls={value.expected_calls}",
    )
    return AttemptCostEstimate(
        estimated_input_tokens=input_tokens,
        estimated_output_tokens=value.output_tokens,
        expected_calls=value.expected_calls,
        cost_usd=cost,
        missing_price_fields=missing,
        assumptions=assumptions,
    )
