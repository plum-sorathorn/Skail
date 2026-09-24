from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from statistics import median

from evals.schema import (
    EvaluationComparison,
    EvaluationFixture,
    EvaluationPolicy,
    EvaluationReport,
    PairedSpeedup,
    PolicySummary,
    TaskEvalResult,
)


def generate_policy_summary(
    results: Sequence[TaskEvalResult], policy: EvaluationPolicy
) -> PolicySummary:
    policy_results = [r for r in results if r.policy == policy]
    total_runs = len(policy_results)
    if total_runs == 0:
        return PolicySummary(
            policy=policy,
            total_runs=0,
            completed_count=0,
            completion_rate=0.0,
            oracle_pass_rate=0.0,
            total_cost_usd=Decimal("0.00"),
            failed_work_cost_usd=Decimal("0.00"),
            cost_per_successful_task_usd=None,
            median_cost_usd=Decimal("0.00"),
            mean_cost_usd=Decimal("0.00"),
            median_wall_time_seconds=0.0,
            total_escalations=0,
            total_interrupts=0,
            safety_defect_count=0,
        )

    completed_count = sum(1 for r in policy_results if r.completed and r.passed_oracle)
    oracle_pass_count = sum(1 for r in policy_results if r.passed_oracle)
    costs = [r.total_cost_usd for r in policy_results]
    total_cost = sum(costs, Decimal("0.00"))
    failed_work_cost = sum(
        (
            result.total_cost_usd
            for result in policy_results
            if not (result.completed and result.passed_oracle)
        ),
        Decimal("0.00"),
    )
    wall_times = [r.wall_time_seconds for r in policy_results]

    return PolicySummary(
        policy=policy,
        total_runs=total_runs,
        completed_count=completed_count,
        completion_rate=round(completed_count / total_runs, 4),
        oracle_pass_rate=round(oracle_pass_count / total_runs, 4),
        total_cost_usd=total_cost,
        failed_work_cost_usd=failed_work_cost,
        cost_per_successful_task_usd=(
            total_cost / completed_count if completed_count else None
        ),
        median_cost_usd=Decimal(str(round(float(median(costs)), 4))),
        mean_cost_usd=Decimal(str(round(float(total_cost / total_runs), 4))),
        median_wall_time_seconds=round(float(median(wall_times)), 4),
        total_escalations=sum(r.escalations_count for r in policy_results),
        total_interrupts=sum(r.interrupts_count for r in policy_results),
        safety_defect_count=sum(len(r.safety_defects) for r in policy_results),
    )


def compare_policies(
    summaries: dict[str, PolicySummary],
    results: Sequence[TaskEvalResult],
    fixtures: Sequence[EvaluationFixture],
    *,
    paired_seeds: Sequence[int] | None = None,
    repetitions: int = 1,
    parallel_fixture_ids: set[str] | None = None,
) -> EvaluationComparison:
    auto_summary = summaries.get(
        EvaluationPolicy.AUTO.value, generate_policy_summary(results, EvaluationPolicy.AUTO)
    )
    quality_summary = summaries.get(
        EvaluationPolicy.QUALITY.value, generate_policy_summary(results, EvaluationPolicy.QUALITY)
    )

    auto_comp = auto_summary.completion_rate
    qual_comp = quality_summary.completion_rate
    comp_delta = round(auto_comp - qual_comp, 4)

    auto_med_cost = auto_summary.median_cost_usd
    qual_med_cost = quality_summary.median_cost_usd
    auto_cost_per_success = auto_summary.cost_per_successful_task_usd
    quality_cost_per_success = quality_summary.cost_per_successful_task_usd
    if (
        auto_cost_per_success is not None
        and quality_cost_per_success is not None
        and quality_cost_per_success > Decimal("0.00")
    ):
        cost_red = round(
            float(
                (quality_cost_per_success - auto_cost_per_success)
                / quality_cost_per_success
                * 100
            ),
            2,
        )
    else:
        cost_red = 0.0

    # The aggregate medians remain informational. The speed gate uses only complete
    # per-fixture auto/serial repetition pairs for each configured seed.
    if parallel_fixture_ids is None:
        parallel_fixture_ids = {f.id for f in fixtures if f.parallel_eligible}
        if not parallel_fixture_ids:
            parallel_fixture_ids = {
                r.fixture_id for r in results if "parallel" in r.fixture_id.lower()
            }

    auto_parallel_times = [
        r.wall_time_seconds
        for r in results
        if r.policy == EvaluationPolicy.AUTO and r.fixture_id in parallel_fixture_ids
    ]
    serial_times = [
        r.wall_time_seconds
        for r in results
        if r.policy == EvaluationPolicy.SERIAL and r.fixture_id in parallel_fixture_ids
    ]

    parallel_med_time = float(median(auto_parallel_times)) if auto_parallel_times else 0.0
    serial_med_time = float(median(serial_times)) if serial_times else 0.0
    expected_seeds = tuple(paired_seeds or sorted({r.seed for r in results}))
    paired_speedups, expected_pair_count = _paired_speedups(
        results=results,
        fixture_ids=parallel_fixture_ids,
        seeds=expected_seeds,
        repetitions=repetitions,
    )
    seed_speedups = {}
    for seed in expected_seeds:
        fixture_speedups = [item.speedup_pct for item in paired_speedups if item.seed == seed]
        if fixture_speedups:
            seed_speedups[seed] = round(float(median(fixture_speedups)), 2)
    pairing_complete = len(paired_speedups) == expected_pair_count
    speedup_pct = round(float(median(seed_speedups.values())), 2) if seed_speedups else 0.0
    spread_pct = (
        round(max(seed_speedups.values()) - min(seed_speedups.values()), 2)
        if len(seed_speedups) > 1
        else None
    )

    # SPEC.md section 21 initial gates:
    # 1. Completion rate within 5 percentage points of fixed quality
    gate_completion = comp_delta >= -0.05
    # 2. Total spend per independently successful task is at least 20% below fixed quality.
    gate_cost = cost_red >= 20.0
    # 3. Each seed needs >=15% paired speedup, with at most 10 points of cross-seed spread.
    gate_parallel = (
        not parallel_fixture_ids
        or (
            pairing_complete
            and len(seed_speedups) == len(expected_seeds)
            and all(speedup >= 15.0 for speedup in seed_speedups.values())
            and (spread_pct is None or spread_pct <= 10.0)
        )
    )
    # 4. Zero safety / data-loss defects
    total_defects = sum(len(r.safety_defects) for r in results)
    gate_safety = total_defects == 0

    all_passed = gate_completion and gate_cost and gate_parallel and gate_safety

    return EvaluationComparison(
        auto_completion_rate=auto_comp,
        quality_completion_rate=qual_comp,
        completion_delta=comp_delta,
        auto_median_cost_usd=auto_med_cost,
        quality_median_cost_usd=qual_med_cost,
        cost_reduction_pct=cost_red,
        parallel_median_wall_time=parallel_med_time,
        serial_median_wall_time=serial_med_time,
        speedup_pct=speedup_pct,
        parallel_fixture_speedups=tuple(paired_speedups),
        parallel_seed_speedups_pct=seed_speedups,
        parallel_pair_count=len(paired_speedups),
        parallel_expected_pair_count=expected_pair_count,
        parallel_pairing_complete=pairing_complete,
        parallel_cross_seed_spread_pct=spread_pct,
        gate_completion_passed=gate_completion,
        gate_cost_passed=gate_cost,
        gate_parallel_passed=gate_parallel,
        gate_safety_passed=gate_safety,
        all_gates_passed=all_passed,
    )


def _paired_speedups(
    *,
    results: Sequence[TaskEvalResult],
    fixture_ids: set[str],
    seeds: Sequence[int],
    repetitions: int,
) -> tuple[list[PairedSpeedup], int]:
    if repetitions < 1:
        raise ValueError("repetitions must be at least one")

    paired: list[PairedSpeedup] = []
    expected_pair_count = len(fixture_ids) * len(seeds)
    expected_repetitions = set(range(1, repetitions + 1))
    for fixture_id in sorted(fixture_ids):
        for seed in seeds:
            runs = {
                policy: [
                    result
                    for result in results
                    if result.fixture_id == fixture_id
                    and result.seed == seed
                    and result.policy is policy
                ]
                for policy in (EvaluationPolicy.AUTO, EvaluationPolicy.SERIAL)
            }
            if any(
                {run.repetition for run in policy_runs} != expected_repetitions
                or len(policy_runs) != repetitions
                for policy_runs in runs.values()
            ):
                continue
            auto_runs = runs[EvaluationPolicy.AUTO]
            if any(run.child_peak_active < 2 for run in auto_runs):
                continue
            auto_time = float(
                median([run.wall_time_seconds for run in auto_runs])
            )
            serial_time = float(
                median([run.wall_time_seconds for run in runs[EvaluationPolicy.SERIAL]])
            )
            if serial_time <= 0.0:
                continue
            paired.append(
                PairedSpeedup(
                    fixture_id=fixture_id,
                    seed=seed,
                    auto_median_wall_time=round(auto_time, 4),
                    serial_median_wall_time=round(serial_time, 4),
                    speedup_pct=round((serial_time - auto_time) / serial_time * 100, 2),
                )
            )
    return paired, expected_pair_count


def render_markdown_report(report: EvaluationReport) -> str:
    lines: list[str] = [
        "# Skail Routing & Orchestration Evaluation Report",
        "",
        f"- **Run ID**: `{report.run_id}`",
        f"- **Timestamp**: `{report.timestamp.isoformat()}`",
        f"- **Catalog Revision**: `{report.catalog_revision}`",
        f"- **Provider Mode**: `{report.provider_mode}`",
        f"- **Evidence Class**: `{report.evidence_class}`",
        "- **Qualification**: Offline engineering evidence only; "
        "not production economic qualification",
        f"- **Total Fixtures**: `{report.fixture_count}`",
        "",
    ]

    if report.comparison is not None:
        comp = report.comparison
        overall_status = (
            "SYNTHETIC GATES PASSED — NOT PRODUCTION QUALIFIED"
            if comp.all_gates_passed
            else "SYNTHETIC GATES FAILED"
        )
        lines.extend(
            [
                "## SPEC.md Section 21 Acceptance Gates",
                "",
                "| Gate | Criterion | Measured | Status |",
                "|---|---|---|---|",
                (
                    f"| **Completion Margin** | Auto completion within 5% of Quality | "
                    f"{comp.completion_delta:+.2%} | "
                    f"{'PASS' if comp.gate_completion_passed else 'FAIL'} |"
                ),
                (
                    "| **Cost Reduction** | Cost per successful task reduction >= 20% "
                    "vs Quality | "
                    f"{comp.cost_reduction_pct:.1f}% | "
                    f"{'PASS' if comp.gate_cost_passed else 'FAIL'} |"
                ),
                (
                    f"| **Parallel Speedup** | End-to-end wall-time reduction >= 15% vs Serial | "
                    f"{comp.speedup_pct:.1f}% | "
                    f"{'PASS' if comp.gate_parallel_passed else 'FAIL'} |"
                ),
                (
                    f"| **Parallel Wall Time** | Auto / Serial full-wall medians | "
                    f"{comp.parallel_median_wall_time:.2f}s / "
                    f"{comp.serial_median_wall_time:.2f}s | Informational |"
                ),
                (
                    f"| **Safety Defect Gate** | Zero safety or boundary defects | "
                    f"{sum(s.safety_defect_count for s in report.policy_summaries.values())} "
                    f"defects | {'PASS' if comp.gate_safety_passed else 'FAIL'} |"
                ),
                (
                    f"| **Overall Result** | All synthetic engineering gates pass | — | "
                    f"**{overall_status}** |"
                ),
                "",
            ]
        )

    lines.extend(
        [
            "## Policy Comparison Summary",
            "",
            "| Policy | Runs | Completion | Oracle Pass | Median Cost | "
            "Median Time | Cost / Success | Failed Spend | Escalations | Defects |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
    )

    for pol_name, summary in report.policy_summaries.items():
        cost_per_success = (
            str(summary.cost_per_successful_task_usd)
            if summary.cost_per_successful_task_usd is not None
            else "unavailable"
        )
        lines.append(
            f"| `{pol_name}` | {summary.total_runs} | {summary.completion_rate:.1%} | "
            f"{summary.oracle_pass_rate:.1%} | ${summary.median_cost_usd} | "
            f"{summary.median_wall_time_seconds:.2f}s | "
            f"${cost_per_success} | "
            f"${summary.failed_work_cost_usd} | {summary.total_escalations} | "
            f"{summary.safety_defect_count} |"
        )
    lines.append("")

    context_metrics = [result.context_metrics for result in report.results]
    lines.extend(
        [
            "## Context Evidence Summary",
            "",
            f"- **Selected tokens (estimated)**: "
            f"{sum(item.selected_tokens for item in context_metrics)}",
            f"- **Recorded omissions**: "
            f"{sum(item.omissions_count for item in context_metrics)}",
            f"- **Observed artifact retrievals**: "
            f"{sum(item.artifact_retrievals for item in context_metrics)}",
            f"- **Persisted failure-handoff bytes**: "
            f"{sum(item.handoff_bytes for item in context_metrics)}",
            "",
        ]
    )

    return "\n".join(lines)


def save_report_json(report: EvaluationReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(report.model_dump_json())
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
