#!/usr/bin/env python
from __future__ import annotations

import argparse
import platform
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from evals.evidence import (  # noqa: E402
    catalog_digest,
    evaluate_recorded_oracle,
    fixture_digest,
    policy_digest,
    source_identity,
    workspace_evidence_matches,
)
from evals.fixtures_loader import load_fixtures  # noqa: E402
from evals.report import compare_policies, generate_policy_summary  # noqa: E402
from evals.runner import default_eval_candidates  # noqa: E402
from evals.schema import (  # noqa: E402
    CANONICAL_PAIRED_RUNTIME_PROFILE,
    EvaluationFixture,
    EvaluationPolicy,
    EvaluationReport,
)


def validate_eval_report(
    report: EvaluationReport | dict[str, object],
    *,
    expected_fixture_ids: set[str],
    expected_parallel_fixture_ids: set[str] | None = None,
    expected_fixture_digest: str | None = None,
    expected_catalog_digest: str | None = None,
    expected_policy_digest: str | None = None,
    expected_source_commit: str | None = None,
    expected_source_digest: str | None = None,
    expected_fixtures: Sequence[EvaluationFixture] | None = None,
    require_release_scale: bool = False,
    require_synthetic_cost_gate: bool = False,
    now: datetime | None = None,
    max_age: timedelta = timedelta(minutes=15),
) -> EvaluationReport:
    parsed = (
        report if isinstance(report, EvaluationReport) else EvaluationReport.model_validate(report)
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
    provenance = parsed.provenance
    if provenance is None:
        raise AssertionError("evaluation provenance is missing")
    if provenance.operating_system != platform.platform():
        raise AssertionError("evaluation platform does not match the validating platform")
    if provenance.python_version != platform.python_version():
        raise AssertionError("evaluation Python version does not match the validating runtime")
    if not provenance.command:
        raise AssertionError("evaluation invoking command is missing")
    if provenance.policy_digest != policy_digest(parsed.policy_controls):
        raise AssertionError("evaluation policy digest does not match policy controls")
    if expected_fixture_digest is not None and provenance.fixture_digest != expected_fixture_digest:
        raise AssertionError("evaluation fixture digest does not match the approved fixtures")
    if expected_catalog_digest is not None and provenance.catalog_digest != expected_catalog_digest:
        raise AssertionError("evaluation catalog digest does not match the approved catalog")
    if expected_policy_digest is not None and provenance.policy_digest != expected_policy_digest:
        raise AssertionError("evaluation policy digest does not match the approved controls")
    if expected_source_commit is not None and provenance.source_commit != expected_source_commit:
        raise AssertionError("evaluation source commit does not match the candidate")
    if expected_source_digest is not None and provenance.source_digest != expected_source_digest:
        raise AssertionError("evaluation source digest does not match the candidate checkout")
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
        or len({result.execution_order for result in parsed.results}) != len(parsed.results)
    ):
        raise AssertionError(
            "evaluation fixture-policy-seed-repetition coverage is incomplete or duplicated"
        )
    if parsed.fixture_count != len(expected_fixture_ids):
        raise AssertionError("evaluation fixture count does not match the manifest")
    if require_release_scale and parsed.fixture_count < 50:
        raise AssertionError("release evaluation requires at least 50 approved fixtures")
    if require_release_scale and (
        expected_fixtures is None
        or any(fixture.metadata.get("approved") is not True for fixture in expected_fixtures)
    ):
        raise AssertionError("release evaluation requires approved fixture definitions")
    if require_release_scale and (
        parsed.run_profile_id != CANONICAL_PAIRED_RUNTIME_PROFILE.id
        or parsed.paired_seeds != CANONICAL_PAIRED_RUNTIME_PROFILE.paired_seeds
        or parsed.repetitions != CANONICAL_PAIRED_RUNTIME_PROFILE.repetitions
    ):
        raise AssertionError("release evaluation requires the complete paired runtime profile")
    if set(parsed.policy_summaries) != {policy.value for policy in policies}:
        raise AssertionError("evaluation policy summaries are incomplete")
    fixture_by_id = {fixture.id: fixture for fixture in expected_fixtures or ()}
    if fixture_by_id and set(fixture_by_id) != expected_fixture_ids:
        raise AssertionError("expected fixture definitions do not match fixture identities")
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
        or len({record.execution_order for record in parsed.raw_records}) != len(parsed.raw_records)
    ):
        raise AssertionError("raw invocation coverage is incomplete or duplicated")
    raw_by_identity = dict(zip(raw_identities, parsed.raw_records, strict=True))
    if any(
        raw_by_identity[identity].usage_cost_usd != result.total_cost_usd
        or sum(raw_by_identity[identity].usage_records, start=Decimal("0.00"))
        != raw_by_identity[identity].usage_cost_usd
        or raw_by_identity[identity].execution_order != result.execution_order
        or raw_by_identity[identity].wall_time_seconds != result.wall_time_seconds
        or any(cost < 0 or not cost.is_finite() for cost in raw_by_identity[identity].usage_records)
        or len(raw_by_identity[identity].assignments) != result.assignments_count
        or tuple(dict.fromkeys(item.model for item in raw_by_identity[identity].assignments))
        != result.models_used
        or any(
            item.catalog_revision != parsed.catalog_revision
            for item in raw_by_identity[identity].assignments
        )
        for identity, result in zip(actual_identities, parsed.results, strict=True)
    ):
        raise AssertionError("scored results do not match raw execution identity or costs")

    for identity, result in zip(actual_identities, parsed.results, strict=True):
        fixture = fixture_by_id.get(result.fixture_id)
        expected_status = "completed" if fixture is None else fixture.expected_run_status
        raw = raw_by_identity[identity]
        if fixture is not None and not workspace_evidence_matches(raw):
            raise AssertionError("raw workspace evidence does not match immutable content digests")
        oracle_passed = (
            result.passed_oracle
            if fixture is None
            else evaluate_recorded_oracle(raw, fixture.oracle)
        )
        if result.passed_oracle != oracle_passed:
            raise AssertionError("serialized oracle result does not match raw workspace evidence")
        contract_passed = raw.run_status == expected_status and oracle_passed
        if result.contract_passed != contract_passed or not contract_passed:
            raise AssertionError(
                "evaluation contains an unexpected contract outcome or oracle failure"
            )

    economic_results = [
        result
        for result in parsed.results
        if fixture_by_id.get(result.fixture_id) is None
        or fixture_by_id[result.fixture_id].economic_eligible
    ]

    recomputed_summaries = {
        policy.value: generate_policy_summary(economic_results, policy) for policy in policies
    }
    if parsed.policy_summaries != recomputed_summaries:
        raise AssertionError("serialized policy summaries do not match raw recomputation")
    comparison = parsed.comparison
    if comparison is None:
        raise AssertionError("evaluation comparison is missing")
    recomputed_comparison = compare_policies(
        recomputed_summaries,
        economic_results,
        (),
        paired_seeds=parsed.paired_seeds,
        repetitions=parsed.repetitions,
        parallel_fixture_ids=expected_parallel_fixture_ids or set(),
    )
    if comparison != recomputed_comparison:
        raise AssertionError("serialized comparison does not match raw recomputation")
    engineering_gates_passed = (
        recomputed_comparison.gate_completion_passed
        and recomputed_comparison.gate_parallel_passed
        and recomputed_comparison.gate_safety_passed
    )
    if not engineering_gates_passed or (
        require_synthetic_cost_gate and not recomputed_comparison.gate_cost_passed
    ):
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
        [sys.executable, "-m", "mypy", "src/skail"],
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
        ROOT / "docs" / "skail" / "SPEC.md",
        ROOT / "docs" / "skail" / "ARCHITECTURE.md",
        ROOT / "docs" / "skail" / "CLI.md",
        ROOT / "docs" / "skail" / "FEATURES.md",
        ROOT / "docs" / "skail" / "EVALUATION.md",
        ROOT / "docs" / "skail" / "THREAT_MODEL.md",
        ROOT / "docs" / "skail" / "PERFORMANCE.md",
        ROOT / "evals" / "manifest.toml",
    ]
    for doc in required_docs:
        if not doc.exists():
            raise FileNotFoundError(f"Missing required documentation: {doc}")
    print("  -> All 10 core documentation files and manifests present.")


def check_wheel_contents() -> None:
    print("[6/8] Building and verifying a fresh wheel...")
    with tempfile.TemporaryDirectory(prefix="skail-release-build-") as directory:
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
                if name.startswith(("evals/", "scripts/", "tests/")):
                    raise AssertionError(f"Development-only content packaged in wheel: {name}")
                if name.startswith("legacy/"):
                    raise AssertionError(f"Forbidden legacy content packaged in wheel: {name}")
                if "skail" in name.lower() and not name.startswith("skail_harness-"):
                    raise AssertionError(f"Forbidden legacy skail reference in wheel: {name}")

            skail_files = [n for n in namelist if n.startswith("skail/")]
            if not skail_files:
                raise AssertionError("Wheel contains no skail package files!")
            print(f"  -> Verified {len(skail_files)} package files; 0 legacy files.")


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
    source_commit, source_digest = source_identity()
    expected_fixture_digest = fixture_digest(fixtures)
    expected_catalog_digest = catalog_digest("eval-v1", default_eval_candidates())
    expected_controls = {policy.value: policy.controls() for policy in EvaluationPolicy}
    expected_policy_digest = policy_digest(expected_controls)
    with tempfile.TemporaryDirectory(prefix="skail-release-eval-") as directory:
        output = Path(directory) / "paired-runtime-report.json"
        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "eval_routing.py"),
                "--fixtures",
                "evals/manifest.toml",
                "--paired-runtime",
                "--output",
                str(output),
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        if proc.returncode not in {0, 1} or not output.exists():
            raise RuntimeError(f"Evaluation failed:\n{proc.stderr or proc.stdout}")
        report = EvaluationReport.model_validate_json(output.read_text(encoding="utf-8"))
        validate_eval_report(
            report,
            expected_fixture_ids=expected_ids,
            expected_parallel_fixture_ids=parallel_ids,
            expected_fixture_digest=expected_fixture_digest,
            expected_catalog_digest=expected_catalog_digest,
            expected_policy_digest=expected_policy_digest,
            expected_source_commit=source_commit,
            expected_source_digest=source_digest,
            expected_fixtures=fixtures,
            require_release_scale=True,
        )
    print("  -> Fresh complete paired evaluation passed with bounded timing variance.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a Skail release candidate")
    parser.parse_args(argv)
    print("=== Skail Release Candidate Verification ===")
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
