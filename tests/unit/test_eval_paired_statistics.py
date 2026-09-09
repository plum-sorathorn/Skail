from decimal import Decimal

from evals.report import compare_policies, generate_policy_summary
from evals.schema import EvaluationFixture, EvaluationPolicy, OracleSpec, OracleType, TaskEvalResult


def _result(
    *, policy: EvaluationPolicy, seed: int, repetition: int, wall_time_seconds: float
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
        _result(policy=EvaluationPolicy.AUTO, seed=42, repetition=1, wall_time_seconds=0.8),
        _result(policy=EvaluationPolicy.AUTO, seed=42, repetition=2, wall_time_seconds=0.9),
        _result(policy=EvaluationPolicy.SERIAL, seed=42, repetition=1, wall_time_seconds=1.0),
        _result(policy=EvaluationPolicy.SERIAL, seed=42, repetition=2, wall_time_seconds=1.0),
        _result(policy=EvaluationPolicy.AUTO, seed=100, repetition=1, wall_time_seconds=0.9),
        _result(policy=EvaluationPolicy.AUTO, seed=100, repetition=2, wall_time_seconds=0.9),
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
        _result(policy=EvaluationPolicy.AUTO, seed=42, repetition=1, wall_time_seconds=0.7),
        _result(policy=EvaluationPolicy.AUTO, seed=42, repetition=2, wall_time_seconds=0.7),
        _result(policy=EvaluationPolicy.SERIAL, seed=42, repetition=1, wall_time_seconds=1.0),
        _result(policy=EvaluationPolicy.SERIAL, seed=42, repetition=2, wall_time_seconds=1.0),
        _result(policy=EvaluationPolicy.AUTO, seed=100, repetition=1, wall_time_seconds=0.85),
        _result(policy=EvaluationPolicy.AUTO, seed=100, repetition=2, wall_time_seconds=0.85),
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
