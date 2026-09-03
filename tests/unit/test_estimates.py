from __future__ import annotations

from decimal import Decimal

import pytest

from rudder.routing.estimates import AttemptEstimateInput, estimate_attempt_cost


def test_attempt_estimate_includes_context_tools_output_and_expected_calls() -> None:
    estimate = estimate_attempt_cost(
        AttemptEstimateInput(
            context_tokens=1_000,
            tool_result_tokens=500,
            output_tokens=250,
            expected_calls=3,
            input_usd_per_million=Decimal("2"),
            output_usd_per_million=Decimal("8"),
        )
    )
    assert estimate.estimated_input_tokens == 1_500
    assert estimate.estimated_output_tokens == 250
    assert estimate.expected_calls == 3
    assert estimate.cost_usd == Decimal("0.015000")
    assert "expected_calls=3" in estimate.assumptions


def test_cached_input_uses_cache_price_only_for_declared_cached_tokens() -> None:
    estimate = estimate_attempt_cost(
        AttemptEstimateInput(
            context_tokens=1_000,
            cached_input_tokens=400,
            tool_result_tokens=0,
            output_tokens=0,
            expected_calls=1,
            input_usd_per_million=Decimal("2"),
            cached_input_usd_per_million=Decimal("0.5"),
            output_usd_per_million=Decimal("8"),
        )
    )
    assert estimate.cost_usd == Decimal("0.001400")


def test_explicit_zero_cache_price_is_not_replaced_by_input_price() -> None:
    estimate = estimate_attempt_cost(
        AttemptEstimateInput(
            context_tokens=1_000,
            cached_input_tokens=1_000,
            output_tokens=0,
            input_usd_per_million=Decimal("2"),
            cached_input_usd_per_million=Decimal("0"),
            output_usd_per_million=Decimal("0"),
        )
    )
    assert estimate.cost_usd == Decimal("0.000000")


def test_missing_price_is_distinct_from_a_real_zero_price() -> None:
    missing = estimate_attempt_cost(
        AttemptEstimateInput(
            context_tokens=100,
            output_tokens=100,
            input_usd_per_million=None,
            output_usd_per_million=Decimal("0"),
        )
    )
    free = estimate_attempt_cost(
        AttemptEstimateInput(
            context_tokens=100,
            output_tokens=100,
            input_usd_per_million=Decimal("0"),
            output_usd_per_million=Decimal("0"),
        )
    )
    assert missing.cost_usd is None
    assert missing.missing_price_fields == ("input_usd_per_million",)
    assert free.cost_usd == Decimal("0.000000")
    assert free.missing_price_fields == ()


def test_cost_rounding_is_decimal_half_up_to_one_millionth() -> None:
    estimate = estimate_attempt_cost(
        AttemptEstimateInput(
            context_tokens=1,
            output_tokens=0,
            input_usd_per_million=Decimal("0.5"),
            output_usd_per_million=Decimal("0"),
        )
    )
    assert estimate.cost_usd == Decimal("0.000001")


def test_cached_tokens_must_be_part_of_context() -> None:
    with pytest.raises(ValueError, match="cached_input_tokens"):
        AttemptEstimateInput(
            context_tokens=10,
            cached_input_tokens=11,
            output_tokens=1,
            input_usd_per_million=Decimal("1"),
            output_usd_per_million=Decimal("1"),
        )
