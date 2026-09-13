from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from evals.report import compare_policies, generate_policy_summary
from evals.schema import (
    EvaluationFixture,
    EvaluationPolicy,
    EvaluationReport,
    OracleSpec,
    OracleType,
    RawExecutionRecord,
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
            total_cost_usd=(
                Decimal("0.50") if policy is EvaluationPolicy.AUTO else Decimal("1.00")
            ),
            models_used=("model",),
            assignments_count=1,
            escalations_count=0,
            interrupts_count=0,
        )
        for policy in policies
    )
    summaries = {policy.value: generate_policy_summary(results, policy) for policy in policies}
    comparison = compare_policies(summaries, results, [])
    return EvaluationReport(
        run_id="eval-test",
        timestamp=timestamp or datetime.now(UTC),
        catalog_revision="catalog-test",
        provider_mode="fake",
        fixture_count=1,
        policy_summaries=summaries,
        comparison=comparison,
        raw_records=tuple(
            RawExecutionRecord(
                fixture_id=result.fixture_id,
                policy=result.policy,
                script_digest="a" * 64,
                run_status="completed",
                usage_cost_usd=result.total_cost_usd,
                usage_records=(result.total_cost_usd,),
            )
            for result in results
        ),
        results=results,
    )


def test_release_eval_validation_requires_exact_fresh_policy_coverage() -> None:
    validate_eval_report(_report(), expected_fixture_ids={"fixture-1"})

    missing = _report().model_copy(update={"results": _report().results[:-1]})
    with pytest.raises(AssertionError, match="fixture-policy-seed-repetition coverage"):
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


def test_release_eval_validation_rejects_forged_summaries_and_costs() -> None:
    report = _report()
    forged_comparison = report.comparison.model_copy(update={"all_gates_passed": True})
    forged_summary = report.policy_summaries[EvaluationPolicy.AUTO.value].model_copy(
        update={"total_cost_usd": Decimal("0.01")}
    )
    forged = report.model_copy(
        update={
            "comparison": forged_comparison,
            "policy_summaries": {
                **report.policy_summaries,
                EvaluationPolicy.AUTO.value: forged_summary,
            },
        }
    )

    with pytest.raises(AssertionError, match="summaries do not match raw recomputation"):
        validate_eval_report(forged, expected_fixture_ids={"fixture-1"})

    edited_cost = report.model_copy(
        update={
            "raw_records": (
                report.raw_records[0].model_copy(update={"usage_cost_usd": Decimal("0.01")}),
                *report.raw_records[1:],
            )
        }
    )
    with pytest.raises(AssertionError, match="raw execution identity or costs"):
        validate_eval_report(edited_cost, expected_fixture_ids={"fixture-1"})


def test_release_eval_validation_rejects_passing_gates_over_failing_raw_data() -> None:
    report = _report()
    auto_index = next(
        index
        for index, result in enumerate(report.results)
        if result.policy is EvaluationPolicy.AUTO
    )
    failing_result = report.results[auto_index].model_copy(
        update={"total_cost_usd": Decimal("1.00")}
    )
    failing_raw = report.raw_records[auto_index].model_copy(
        update={
            "usage_cost_usd": Decimal("1.00"),
            "usage_records": (Decimal("1.00"),),
        }
    )
    forged = report.model_copy(
        update={
            "results": (
                *report.results[:auto_index],
                failing_result,
                *report.results[auto_index + 1 :],
            ),
            "raw_records": (
                *report.raw_records[:auto_index],
                failing_raw,
                *report.raw_records[auto_index + 1 :],
            ),
        }
    )

    assert forged.comparison is not None and forged.comparison.all_gates_passed
    with pytest.raises(AssertionError, match="summaries do not match raw recomputation"):
        validate_eval_report(forged, expected_fixture_ids={"fixture-1"})


def test_release_eval_validation_rejects_duplicate_raw_invocations() -> None:
    report = _report()
    duplicated = report.model_copy(
        update={"raw_records": (*report.raw_records, report.raw_records[0])}
    )

    with pytest.raises(AssertionError, match="raw invocation coverage"):
        validate_eval_report(duplicated, expected_fixture_ids={"fixture-1"})


def test_release_eval_validation_rejects_missing_paired_repetition() -> None:
    policies = tuple(EvaluationPolicy)
    results = tuple(
        TaskEvalResult(
            fixture_id="parallel-fixture",
            policy=policy,
            repetition=repetition,
            completed=True,
            passed_oracle=True,
            wall_time_seconds=0.7 if policy is EvaluationPolicy.AUTO else 1.0,
            total_cost_usd=Decimal("0.50") if policy is EvaluationPolicy.AUTO else Decimal("1.00"),
            models_used=("model",),
            assignments_count=1,
            escalations_count=0,
            interrupts_count=0,
        )
        for repetition in (1, 2)
        for policy in policies
    )
    summaries = {policy.value: generate_policy_summary(results, policy) for policy in policies}
    fixture = EvaluationFixture(
        id="parallel-fixture",
        title="Parallel fixture",
        category="parallel",
        prompt="Run parallel work",
        oracle=OracleSpec(type=OracleType.MULTI_ASSERT),
        parallel_eligible=True,
    )
    report = EvaluationReport(
        run_id="eval-paired",
        timestamp=datetime.now(UTC),
        catalog_revision="catalog-test",
        provider_mode="fake",
        fixture_count=1,
        paired_seeds=(42,),
        repetitions=2,
        policy_summaries=summaries,
        comparison=compare_policies(summaries, results, [fixture], repetitions=2),
        results=results,
        raw_records=tuple(
            RawExecutionRecord(
                fixture_id=result.fixture_id,
                policy=result.policy,
                repetition=result.repetition,
                script_digest="a" * 64,
                run_status="completed",
                usage_cost_usd=result.total_cost_usd,
                usage_records=(result.total_cost_usd,),
            )
            for result in results
        ),
    )
    incomplete = report.model_copy(
        update={
            "results": report.results[:-1],
            "raw_records": report.raw_records[:-1],
        }
    )

    with pytest.raises(AssertionError, match="fixture-policy-seed-repetition coverage"):
        validate_eval_report(
            incomplete,
            expected_fixture_ids={"parallel-fixture"},
            expected_parallel_fixture_ids={"parallel-fixture"},
        )
