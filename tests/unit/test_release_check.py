from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from evals.schema import (
    EvaluationComparison,
    EvaluationPolicy,
    EvaluationReport,
    PolicySummary,
    TaskEvalResult,
)
from scripts.release_check import validate_eval_report


def _report(*, timestamp: datetime | None = None) -> EvaluationReport:
    policies = tuple(EvaluationPolicy)
    results = tuple(
        TaskEvalResult(
            fixture_id="fixture-1",
            policy=policy,
            completed=True,
            passed_oracle=True,
            wall_time_seconds=1.0,
            total_cost_usd=Decimal("1.00"),
            models_used=("model",),
            assignments_count=1,
            escalations_count=0,
            interrupts_count=0,
        )
        for policy in policies
    )
    summaries = {
        policy.value: PolicySummary(
            policy=policy,
            total_runs=1,
            completed_count=1,
            completion_rate=1.0,
            oracle_pass_rate=1.0,
            total_cost_usd=Decimal("1.00"),
            median_cost_usd=Decimal("1.00"),
            mean_cost_usd=Decimal("1.00"),
            median_wall_time_seconds=1.0,
            total_escalations=0,
            total_interrupts=0,
            safety_defect_count=0,
        )
        for policy in policies
    }
    return EvaluationReport(
        run_id="eval-test",
        timestamp=timestamp or datetime.now(UTC),
        catalog_revision="catalog-test",
        provider_mode="fake",
        fixture_count=1,
        policy_summaries=summaries,
        comparison=EvaluationComparison(
            auto_completion_rate=1.0,
            quality_completion_rate=1.0,
            completion_delta=0.0,
            auto_median_cost_usd=Decimal("0.50"),
            quality_median_cost_usd=Decimal("1.00"),
            cost_reduction_pct=50.0,
            parallel_median_wall_time=0.7,
            serial_median_wall_time=1.0,
            speedup_pct=30.0,
            gate_completion_passed=True,
            gate_cost_passed=True,
            gate_parallel_passed=True,
            gate_safety_passed=True,
            all_gates_passed=True,
        ),
        results=results,
    )


def test_release_eval_validation_requires_exact_fresh_policy_coverage() -> None:
    validate_eval_report(_report(), expected_fixture_ids={"fixture-1"})

    missing = _report().model_copy(update={"results": _report().results[:-1]})
    with pytest.raises(AssertionError, match="fixture-policy coverage"):
        validate_eval_report(missing, expected_fixture_ids={"fixture-1"})

    stale = _report(timestamp=datetime.now(UTC) - timedelta(hours=1))
    with pytest.raises(AssertionError, match="fresh"):
        validate_eval_report(stale, expected_fixture_ids={"fixture-1"})

    future = _report(timestamp=datetime.now(UTC) + timedelta(hours=1))
    with pytest.raises(AssertionError, match="future"):
        validate_eval_report(future, expected_fixture_ids={"fixture-1"})


def test_release_eval_validation_recomputes_outcome_requirements() -> None:
    failed_result = _report().results[0].model_copy(update={"passed_oracle": False})
    report = _report().model_copy(
        update={"results": (failed_result, *_report().results[1:])}
    )

    with pytest.raises(AssertionError, match="oracle"):
        validate_eval_report(report, expected_fixture_ids={"fixture-1"})
