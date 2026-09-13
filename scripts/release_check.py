#!/usr/bin/env python
from __future__ import annotations

import subprocess
import sys
import tempfile
import zipfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from evals.fixtures_loader import load_fixtures
from evals.report import compare_policies, generate_policy_summary
from evals.schema import EvaluationPolicy, EvaluationReport

ROOT = Path(__file__).resolve().parents[1]


def validate_eval_report(
    report: EvaluationReport | dict[str, object],
    *,
    expected_fixture_ids: set[str],
    expected_parallel_fixture_ids: set[str] | None = None,
    now: datetime | None = None,
    max_age: timedelta = timedelta(minutes=15),
) -> EvaluationReport:
    parsed = (
        report
        if isinstance(report, EvaluationReport)
        else EvaluationReport.model_validate(report)
    )
    current = now or datetime.now(UTC)
    if parsed.timestamp.tzinfo is None:
        raise AssertionError("evaluation report must be fresh and timezone-aware")
    if parsed.timestamp > current:
        raise AssertionError("evaluation report timestamp cannot be in the future")
    if current - parsed.timestamp > max_age:
        raise AssertionError("evaluation report must be fresh and timezone-aware")
    if parsed.provider_mode != "fake":
        raise AssertionError("offline release evaluation must use fake provider mode")
    policies = set(EvaluationPolicy)
    expected_identities = {
        (fixture_id, policy, seed, repetition)
        for fixture_id in expected_fixture_ids
        for policy in policies
        for seed in parsed.paired_seeds
        for repetition in range(1, parsed.repetitions + 1)
    }
    actual_identities = [
        (result.fixture_id, result.policy, result.seed, result.repetition)
        for result in parsed.results
    ]
    if (
        len(actual_identities) != len(set(actual_identities))
        or set(actual_identities) != expected_identities
    ):
        raise AssertionError(
            "evaluation fixture-policy-seed-repetition coverage is incomplete or duplicated"
        )
    if parsed.fixture_count != len(expected_fixture_ids):
        raise AssertionError("evaluation fixture count does not match the manifest")
    if set(parsed.policy_summaries) != {policy.value for policy in policies}:
        raise AssertionError("evaluation policy summaries are incomplete")
    if any(not result.completed for result in parsed.results):
        raise AssertionError("evaluation contains incomplete runtime executions")
    if any(not result.passed_oracle for result in parsed.results):
        raise AssertionError("evaluation contains an oracle failure")
    if any(result.safety_defects for result in parsed.results):
        raise AssertionError("evaluation contains safety or runtime-integrity defects")
    if any(result.assignments_count < 1 for result in parsed.results):
        raise AssertionError("evaluation result is missing a persisted assignment")
    raw_identities = [
        (record.fixture_id, record.policy, record.seed, record.repetition)
        for record in parsed.raw_records
    ]
    if (
        len(raw_identities) != len(set(raw_identities))
        or set(raw_identities) != expected_identities
    ):
        raise AssertionError("raw invocation coverage is incomplete or duplicated")
    raw_by_identity = dict(zip(raw_identities, parsed.raw_records, strict=True))
    if any(
        raw_by_identity[identity].usage_cost_usd != result.total_cost_usd
        or sum(raw_by_identity[identity].usage_records, start=Decimal("0.00"))
        != raw_by_identity[identity].usage_cost_usd
        or raw_by_identity[identity].execution_order != result.execution_order
        for identity, result in zip(actual_identities, parsed.results, strict=True)
    ):
        raise AssertionError("scored results do not match raw execution identity or costs")

    recomputed_summaries = {
        policy.value: generate_policy_summary(parsed.results, policy) for policy in policies
    }
    if parsed.policy_summaries != recomputed_summaries:
        raise AssertionError("serialized policy summaries do not match raw recomputation")
    comparison = parsed.comparison
    if comparison is None:
        raise AssertionError("evaluation comparison is missing")
    recomputed_comparison = compare_policies(
        recomputed_summaries,
        parsed.results,
        (),
        paired_seeds=parsed.paired_seeds,
        repetitions=parsed.repetitions,
        parallel_fixture_ids=expected_parallel_fixture_ids or set(),
    )
    if comparison != recomputed_comparison:
        raise AssertionError("serialized comparison does not match raw recomputation")
    if not recomputed_comparison.all_gates_passed:
        raise AssertionError("evaluation acceptance gates did not pass")
    return parsed


def _run_checked(label: str, command: list[str]) -> str:
    print(label)
    proc = subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{label} failed:\n{proc.stdout}\n{proc.stderr}")
    return proc.stdout


def check_clean_worktree() -> None:
    output = _run_checked(
        "[1/8] Verifying clean Git worktree...",
        ["git", "status", "--porcelain", "--untracked-files=all"],
    )
    if output.strip():
        raise AssertionError(f"release worktree is not clean:\n{output}")


def check_quality() -> None:
    _run_checked(
        "[2/8] Running Ruff...",
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "src",
            "tests",
            "scripts",
            "evals",
            "benchmarks",
        ],
    )
    _run_checked(
        "[3/8] Running mypy...",
        [sys.executable, "-m", "mypy", "src/rudder"],
    )
    _run_checked(
        "[4/8] Running complete offline test suite...",
        [sys.executable, "-m", "pytest", "-q"],
    )


def check_docs() -> None:
    print("[5/8] Verifying required documentation...")
    required_docs = [
        ROOT / "README.md",
        ROOT / "LICENSE",
        ROOT / "docs" / "rudder" / "SPEC.md",
        ROOT / "docs" / "rudder" / "ARCHITECTURE.md",
        ROOT / "docs" / "rudder" / "CLI.md",
        ROOT / "docs" / "rudder" / "FEATURES.md",
        ROOT / "docs" / "rudder" / "EVALUATION.md",
        ROOT / "docs" / "rudder" / "THREAT_MODEL.md",
        ROOT / "docs" / "rudder" / "PERFORMANCE.md",
        ROOT / "evals" / "manifest.toml",
    ]
    for doc in required_docs:
        if not doc.exists():
            raise FileNotFoundError(f"Missing required documentation: {doc}")
    print("  -> All 10 core documentation files and manifests present.")


def check_wheel_contents() -> None:
    print("[6/8] Building and verifying a fresh wheel...")
    with tempfile.TemporaryDirectory(prefix="rudder-release-build-") as directory:
        dist_dir = Path(directory)
        subprocess.run(
            [sys.executable, "-m", "build", "--outdir", str(dist_dir)],
            cwd=str(ROOT),
            check=True,
            capture_output=True,
            text=True,
        )
        wheels = list(dist_dir.glob("*.whl"))
        if len(wheels) != 1:
            raise AssertionError("fresh build must produce exactly one wheel")
        wheel_path = wheels[0]
        print(f"  -> Inspecting fresh wheel: {wheel_path.name}")

        with zipfile.ZipFile(wheel_path) as zf:
            namelist = zf.namelist()
            for name in namelist:
                if name.startswith("legacy/"):
                    raise AssertionError(f"Forbidden legacy content packaged in wheel: {name}")
                if "autoconduck" in name.lower() and not name.startswith("rudder_harness-"):
                    raise AssertionError(f"Forbidden legacy autoconduck reference in wheel: {name}")

            rudder_files = [n for n in namelist if n.startswith("rudder/")]
            if not rudder_files:
                raise AssertionError("Wheel contains no rudder package files!")
            print(f"  -> Verified {len(rudder_files)} package files; 0 legacy files.")


def check_smoke() -> None:
    print("[7/8] Running fake-provider smoke and benchmark verification...")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "smoke.py"), "--fake-provider"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Smoke test failed:\n{proc.stderr}")
    print("  -> Fake-provider smoke: OK.")
    _run_checked(
        "  -> Running benchmark thresholds...",
        [sys.executable, str(ROOT / "benchmarks" / "bench_runner.py"), "--json"],
    )


def check_evals() -> None:
    print("[8/8] Running and validating fresh evaluation results...")
    fixtures = load_fixtures(ROOT / "evals" / "manifest.toml")
    expected_ids = {fixture.id for fixture in fixtures}
    parallel_ids = {fixture.id for fixture in fixtures if fixture.parallel_eligible}
    reports: list[EvaluationReport] = []
    with tempfile.TemporaryDirectory(prefix="rudder-release-eval-") as directory:
        for seed in (42, 100):
            output = Path(directory) / f"report-{seed}.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "eval_routing.py"),
                    "--fixtures",
                    "evals/manifest.toml",
                    "--seed",
                    str(seed),
                    "--output",
                    str(output),
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"Evaluation seed {seed} failed:\n{proc.stderr or proc.stdout}")
            report = EvaluationReport.model_validate_json(output.read_text(encoding="utf-8"))
            reports.append(
                validate_eval_report(
                    report,
                    expected_fixture_ids=expected_ids,
                    expected_parallel_fixture_ids=parallel_ids,
                )
            )
    speedups = [report.comparison.speedup_pct for report in reports if report.comparison]
    if max(speedups) - min(speedups) > 10.0:
        raise AssertionError("parallel speedup variance exceeds 10 percentage points")
    print("  -> Two fresh complete evaluation runs passed with bounded timing variance.")


def main() -> int:
    print("=== Rudder Release Candidate Verification ===")
    try:
        check_clean_worktree()
        check_quality()
        check_docs()
        check_wheel_contents()
        check_smoke()
        check_evals()
        print("\n=== Release candidate verification PASSED cleanly! ===")
        return 0
    except Exception as exc:
        print(f"\n[ERROR] Release candidate verification failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
