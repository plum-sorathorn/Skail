from decimal import Decimal

from evals.report import compare_policies, generate_policy_summary
from evals.schema import EvaluationFixture, EvaluationPolicy, OracleSpec, OracleType, TaskEvalResult


def _result(
    *,
    policy: EvaluationPolicy,
    seed: int,
    repetition: int,
    wall_time_seconds: float,
    child_peak_active: int = 0,
) -> TaskEvalResult:
    return TaskEvalResult(
        fixture_id="parallel-fixture",
        policy=policy,
        seed=seed,
        repetition=repetition,
        completed=True,
        passed_oracle=True,
        wall_time_seconds=wall_time_seconds,
        total_cost_usd=Decimal("1.00"),
        models_used=("eval-model",),
        assignments_count=1,
        escalations_count=0,
        interrupts_count=0,
        child_peak_active=child_peak_active,
    )


def test_paired_parallel_gate_uses_per_fixture_medians_for_each_seed() -> None:
    fixture = EvaluationFixture(
        id="parallel-fixture",
        title="Parallel fixture",
        category="parallel",
        prompt="Run parallel work",
        parallel_eligible=True,
        oracle=OracleSpec(type=OracleType.MULTI_ASSERT),
    )
    results = [
        _result(
            policy=EvaluationPolicy.AUTO,
            seed=42,
            repetition=1,
            wall_time_seconds=0.8,
            child_peak_active=2,
        ),
        _result(
            policy=EvaluationPolicy.AUTO,
            seed=42,
            repetition=2,
            wall_time_seconds=0.9,
            child_peak_active=2,
        ),
        _result(policy=EvaluationPolicy.SERIAL, seed=42, repetition=1, wall_time_seconds=1.0),
        _result(policy=EvaluationPolicy.SERIAL, seed=42, repetition=2, wall_time_seconds=1.0),
        _result(
            policy=EvaluationPolicy.AUTO,
            seed=100,
            repetition=1,
            wall_time_seconds=0.9,
            child_peak_active=2,
        ),
        _result(
            policy=EvaluationPolicy.AUTO,
            seed=100,
            repetition=2,
            wall_time_seconds=0.9,
            child_peak_active=2,
        ),
        _result(policy=EvaluationPolicy.SERIAL, seed=100, repetition=1, wall_time_seconds=1.0),
        _result(policy=EvaluationPolicy.SERIAL, seed=100, repetition=2, wall_time_seconds=1.0),
    ]
    summaries = {
        policy.value: generate_policy_summary(results, policy)
        for policy in (EvaluationPolicy.AUTO, EvaluationPolicy.SERIAL)
    }

    comparison = compare_policies(
        summaries,
        results,
        [fixture],
        paired_seeds=(42, 100),
        repetitions=2,
    )

    assert comparison.parallel_pairing_complete
    assert comparison.parallel_seed_speedups_pct == {42: 15.0, 100: 10.0}
    assert comparison.parallel_cross_seed_spread_pct == 5.0
    assert not comparison.gate_parallel_passed


def test_paired_parallel_gate_rejects_missing_repetitions() -> None:
    fixture = EvaluationFixture(
        id="parallel-fixture",
        title="Parallel fixture",
        category="parallel",
        prompt="Run parallel work",
        parallel_eligible=True,
        oracle=OracleSpec(type=OracleType.MULTI_ASSERT),
    )
    results = [
        _result(policy=EvaluationPolicy.AUTO, seed=42, repetition=1, wall_time_seconds=0.8),
        _result(policy=EvaluationPolicy.SERIAL, seed=42, repetition=1, wall_time_seconds=1.0),
    ]
    summaries = {
        policy.value: generate_policy_summary(results, policy)
        for policy in (EvaluationPolicy.AUTO, EvaluationPolicy.SERIAL)
    }

    comparison = compare_policies(
        summaries,
        results,
        [fixture],
        paired_seeds=(42,),
        repetitions=2,
    )

    assert not comparison.parallel_pairing_complete
    assert comparison.parallel_pair_count == 0
    assert not comparison.gate_parallel_passed


def test_paired_parallel_gate_rejects_excessive_cross_seed_spread() -> None:
    fixture = EvaluationFixture(
        id="parallel-fixture",
        title="Parallel fixture",
        category="parallel",
        prompt="Run parallel work",
        parallel_eligible=True,
        oracle=OracleSpec(type=OracleType.MULTI_ASSERT),
    )
    results = [
        _result(
            policy=EvaluationPolicy.AUTO,
            seed=42,
            repetition=1,
            wall_time_seconds=0.7,
            child_peak_active=2,
        ),
        _result(
            policy=EvaluationPolicy.AUTO,
            seed=42,
            repetition=2,
            wall_time_seconds=0.7,
            child_peak_active=2,
        ),
        _result(policy=EvaluationPolicy.SERIAL, seed=42, repetition=1, wall_time_seconds=1.0),
        _result(policy=EvaluationPolicy.SERIAL, seed=42, repetition=2, wall_time_seconds=1.0),
        _result(
            policy=EvaluationPolicy.AUTO,
            seed=100,
            repetition=1,
            wall_time_seconds=0.85,
            child_peak_active=2,
        ),
        _result(
            policy=EvaluationPolicy.AUTO,
            seed=100,
            repetition=2,
            wall_time_seconds=0.85,
            child_peak_active=2,
        ),
        _result(policy=EvaluationPolicy.SERIAL, seed=100, repetition=1, wall_time_seconds=1.0),
        _result(policy=EvaluationPolicy.SERIAL, seed=100, repetition=2, wall_time_seconds=1.0),
    ]
    summaries = {
        policy.value: generate_policy_summary(results, policy)
        for policy in (EvaluationPolicy.AUTO, EvaluationPolicy.SERIAL)
    }

    comparison = compare_policies(
        summaries,
        results,
        [fixture],
        paired_seeds=(42, 100),
        repetitions=2,
    )

    assert comparison.parallel_pairing_complete
    assert comparison.parallel_cross_seed_spread_pct == 15.0
    assert not comparison.gate_parallel_passed


def test_cost_gate_uses_total_spend_per_success_including_failed_work() -> None:
    fixture = EvaluationFixture(
        id="parallel-fixture",
        title="Completed-work economics fixture",
        category="routine",
        prompt="Complete the same useful work",
        oracle=OracleSpec(type=OracleType.MULTI_ASSERT),
    )
    auto_success = _result(
        policy=EvaluationPolicy.AUTO,
        seed=42,
        repetition=1,
        wall_time_seconds=1.0,
    ).model_copy(update={"total_cost_usd": Decimal("0.10")})
    auto_failure = _result(
        policy=EvaluationPolicy.AUTO,
        seed=42,
        repetition=2,
        wall_time_seconds=1.0,
    ).model_copy(
        update={
            "completed": False,
            "passed_oracle": False,
            "total_cost_usd": Decimal("1.00"),
        }
    )
    quality_results = [
        _result(
            policy=EvaluationPolicy.QUALITY,
            seed=42,
            repetition=repetition,
            wall_time_seconds=1.0,
        )
        for repetition in (1, 2)
    ]
    results = [auto_success, auto_failure, *quality_results]
    summaries = {
        policy.value: generate_policy_summary(results, policy)
        for policy in (EvaluationPolicy.AUTO, EvaluationPolicy.QUALITY)
    }

    comparison = compare_policies(summaries, results, [fixture])

    assert comparison.auto_median_cost_usd == Decimal("0.55")
    assert summaries["auto"].cost_per_successful_task_usd == Decimal("1.10")
    assert summaries["quality"].cost_per_successful_task_usd == Decimal("1.00")
    assert comparison.cost_reduction_pct == -10.0
    assert not comparison.gate_cost_passed
