import hashlib
import os
import platform
import subprocess
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from evals.evidence import digest_value
from evals.report import compare_policies, generate_policy_summary
from evals.schema import (
    EvaluationFixture,
    EvaluationPolicy,
    EvaluationProvenance,
    EvaluationReport,
    ExecutedAssignment,
    OracleSpec,
    OracleType,
    RawExecutionRecord,
    TaskEvalResult,
)
from scripts import release_check
from scripts.release_check import check_smoke, check_wheel_contents, validate_eval_report
from skail.domain.routing import RoutingMode


def _report(*, timestamp: datetime | None = None) -> EvaluationReport:
    policies = tuple(EvaluationPolicy)
    results = tuple(
        TaskEvalResult(
            fixture_id="fixture-1",
            policy=policy,
            execution_order=index,
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
        for index, policy in enumerate(policies)
    )
    summaries = {policy.value: generate_policy_summary(results, policy) for policy in policies}
    comparison = compare_policies(summaries, results, [])
    policy_controls: dict[str, object] = {}
    provenance = EvaluationProvenance(
        source_commit="a" * 40,
        source_digest="b" * 64,
        fixture_digest=digest_value(["fixture-1"]),
        catalog_digest="c" * 64,
        policy_digest=digest_value(policy_controls),
        operating_system=platform.platform(),
        python_version=platform.python_version(),
        dependency_versions={},
        command=("test",),
    )
    return EvaluationReport(
        run_id="eval-test",
        timestamp=timestamp or datetime.now(UTC),
        catalog_revision="catalog-test",
        provider_mode="fake",
        fixture_count=1,
        provenance=provenance,
        policy_controls=policy_controls,
        policy_summaries=summaries,
        comparison=comparison,
        raw_records=tuple(
            RawExecutionRecord(
                fixture_id=result.fixture_id,
                policy=result.policy,
                execution_order=result.execution_order,
                script_digest="a" * 64,
                run_status="completed",
                wall_time_seconds=result.wall_time_seconds,
                usage_cost_usd=result.total_cost_usd,
                usage_records=(result.total_cost_usd,),
                assignments=(
                    ExecutedAssignment(
                        attempt_number=1,
                        provider="fake",
                        model="model",
                        routing_mode=RoutingMode.AUTO,
                        capability_floor=0.5,
                        estimated_attempt_cost_usd=Decimal("0.01"),
                        explanation=("test",),
                        catalog_revision="catalog-test",
                    ),
                ),
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
    report = _report().model_copy(update={"results": (failed_result, *_report().results[1:])})

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


def test_release_eval_validation_separates_engineering_from_synthetic_cost_gate() -> None:
    report = _report()
    results = tuple(
        result.model_copy(update={"total_cost_usd": Decimal("1.00")})
        if result.policy is EvaluationPolicy.AUTO
        else result
        for result in report.results
    )
    raw_records = tuple(
        record.model_copy(
            update={
                "usage_cost_usd": Decimal("1.00"),
                "usage_records": (Decimal("1.00"),),
            }
        )
        if record.policy is EvaluationPolicy.AUTO
        else record
        for record in report.raw_records
    )
    summaries = {
        policy.value: generate_policy_summary(results, policy) for policy in EvaluationPolicy
    }
    comparison = compare_policies(summaries, results, ())
    cost_unqualified = report.model_copy(
        update={
            "results": results,
            "raw_records": raw_records,
            "policy_summaries": summaries,
            "comparison": comparison,
        }
    )

    assert not comparison.gate_cost_passed
    validate_eval_report(cost_unqualified, expected_fixture_ids={"fixture-1"})
    with pytest.raises(AssertionError, match="acceptance gates"):
        validate_eval_report(
            cost_unqualified,
            expected_fixture_ids={"fixture-1"},
            require_synthetic_cost_gate=True,
        )


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
        provenance=_report().provenance,
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
                wall_time_seconds=result.wall_time_seconds,
                usage_cost_usd=result.total_cost_usd,
                usage_records=(result.total_cost_usd,),
                assignments=_report().raw_records[0].assignments,
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


def test_release_eval_validation_rejects_mismatched_bound_provenance() -> None:
    report = _report()

    with pytest.raises(AssertionError, match="fixture digest"):
        validate_eval_report(
            report,
            expected_fixture_ids={"fixture-1"},
            expected_fixture_digest="d" * 64,
        )

    with pytest.raises(AssertionError, match="source commit"):
        validate_eval_report(
            report,
            expected_fixture_ids={"fixture-1"},
            expected_source_commit="e" * 40,
        )

    with pytest.raises(AssertionError, match="catalog digest"):
        validate_eval_report(
            report,
            expected_fixture_ids={"fixture-1"},
            expected_catalog_digest="f" * 64,
        )

    with pytest.raises(AssertionError, match="policy digest"):
        validate_eval_report(
            report,
            expected_fixture_ids={"fixture-1"},
            expected_policy_digest="0" * 64,
        )

    wrong_platform = report.model_copy(
        update={
            "provenance": report.provenance.model_copy(
                update={"operating_system": "not-this-platform"}
            )
        }
    )
    with pytest.raises(AssertionError, match="platform"):
        validate_eval_report(wrong_platform, expected_fixture_ids={"fixture-1"})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("wall_time_seconds", float("nan")),
        ("wall_time_seconds", float("inf")),
        ("wall_time_seconds", -1.0),
        ("total_cost_usd", Decimal("-0.01")),
    ],
)
def test_release_report_rejects_invalid_numeric_observations(
    field: str, value: float | Decimal
) -> None:
    payload = _report().model_dump(mode="python")
    payload["results"][0][field] = value

    with pytest.raises(ValueError):
        EvaluationReport.model_validate(payload)


def test_release_eval_validation_separates_expected_failures_from_economics() -> None:
    report = _report()
    economic_fixture = EvaluationFixture(
        id="fixture-1",
        title="Economic fixture",
        category="routine",
        prompt="Complete work",
        oracle=OracleSpec(type=OracleType.MULTI_ASSERT),
    )
    failure_fixture = EvaluationFixture(
        id="expected-block",
        title="Expected block",
        category="failure",
        prompt="Require unavailable approval",
        oracle=OracleSpec(type=OracleType.MULTI_ASSERT),
        expected_run_status="blocked",
        economic_eligible=False,
    )
    blocked_results = tuple(
        TaskEvalResult(
            fixture_id=failure_fixture.id,
            policy=policy,
            execution_order=index + len(EvaluationPolicy),
            completed=False,
            passed_oracle=True,
            contract_passed=True,
            wall_time_seconds=1.0,
            total_cost_usd=Decimal("0.00"),
            models_used=("model",),
            assignments_count=1,
            escalations_count=0,
            interrupts_count=0,
        )
        for index, policy in enumerate(EvaluationPolicy)
    )
    blocked_raw = tuple(
        RawExecutionRecord(
            fixture_id=result.fixture_id,
            policy=result.policy,
            execution_order=result.execution_order,
            script_digest="b" * 64,
            run_status="blocked",
            wall_time_seconds=result.wall_time_seconds,
            usage_cost_usd=Decimal("0.00"),
            assignments=_report().raw_records[0].assignments,
        )
        for result in blocked_results
    )
    combined = report.model_copy(
        update={
            "fixture_count": 2,
            "results": (*report.results, *blocked_results),
            "raw_records": (*report.raw_records, *blocked_raw),
        }
    )

    validate_eval_report(
        combined,
        expected_fixture_ids={economic_fixture.id, failure_fixture.id},
        expected_fixtures=(economic_fixture, failure_fixture),
    )

    unexpected = combined.model_copy(
        update={
            "raw_records": (
                *combined.raw_records[:-1],
                combined.raw_records[-1].model_copy(update={"run_status": "failed"}),
            )
        }
    )
    with pytest.raises(AssertionError, match="unexpected contract outcome"):
        validate_eval_report(
            unexpected,
            expected_fixture_ids={economic_fixture.id, failure_fixture.id},
            expected_fixtures=(economic_fixture, failure_fixture),
        )


def test_release_eval_validation_recomputes_oracle_from_raw_workspace() -> None:
    report = _report()
    fixture = EvaluationFixture(
        id="fixture-1",
        title="Raw oracle fixture",
        category="routine",
        prompt="Write result",
        oracle=OracleSpec(
            type=OracleType.FILE_CONTENT,
            target="result.txt",
            expected="expected",
        ),
    )
    raw_records = tuple(
        record.model_copy(
            update={
                "workspace_files": (
                    (
                        "result.txt",
                        hashlib.sha256(b"expected").hexdigest(),
                    ),
                ),
                "workspace_text_files": (("result.txt", "expected"),),
            }
        )
        for record in report.raw_records
    )
    valid = report.model_copy(update={"raw_records": raw_records})

    validate_eval_report(
        valid,
        expected_fixture_ids={fixture.id},
        expected_fixtures=(fixture,),
    )

    forged = valid.model_copy(
        update={
            "raw_records": (
                valid.raw_records[0].model_copy(
                    update={"workspace_text_files": (("result.txt", "forged"),)}
                ),
                *valid.raw_records[1:],
            )
        }
    )
    with pytest.raises(AssertionError, match="workspace evidence"):
        validate_eval_report(
            forged,
            expected_fixture_ids={fixture.id},
            expected_fixtures=(fixture,),
        )


def test_evaluation_and_release_scripts_support_direct_and_module_help(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(root), str(root / "src")))
    commands = (
        (sys.executable, str(root / "scripts" / "eval_routing.py"), "--help"),
        (sys.executable, "-m", "scripts.eval_routing", "--help"),
        (sys.executable, str(root / "scripts" / "release_check.py"), "--help"),
        (sys.executable, "-m", "scripts.release_check", "--help"),
    )

    for command in commands:
        completed = subprocess.run(
            command,
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert completed.returncode == 0, completed.stderr
        assert "usage:" in completed.stdout.lower()


def test_integrated_release_wheel_check_accepts_canonical_skail_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def build_wheel(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        output = Path(command[command.index("--outdir") + 1])
        with zipfile.ZipFile(output / "skail_harness-0.1.0-py3-none-any.whl", "w") as archive:
            archive.writestr("skail/__init__.py", "")
            archive.writestr("skail_harness-0.1.0.dist-info/METADATA", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", build_wheel)

    check_wheel_contents()


def test_release_smoke_uses_an_isolated_runtime_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[dict[str, object]] = []

    def run_smoke(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.append(kwargs)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run_smoke)

    check_smoke()

    smoke_call = next(call for call in observed if "env" in call)
    workspace = Path(str(smoke_call["cwd"]))
    environment = smoke_call["env"]
    assert isinstance(environment, dict)
    assert workspace != Path(__file__).resolve().parents[2]
    assert environment["USERPROFILE"] == str(workspace)
    assert environment["APPDATA"] == str(workspace / "AppData")


def test_release_evals_use_an_isolated_runtime_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def run_evaluation(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.update(kwargs)
        output = Path(command[command.index("--output") + 1])
        output.write_text("{}", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run_evaluation)
    monkeypatch.setattr(release_check, "load_fixtures", lambda _: [])
    monkeypatch.setattr(release_check, "default_eval_candidates", lambda: ())
    monkeypatch.setattr(release_check, "source_identity", lambda: ("commit", "digest"))
    monkeypatch.setattr(release_check, "fixture_digest", lambda _: "fixtures")
    monkeypatch.setattr(release_check, "catalog_digest", lambda *_: "catalog")
    monkeypatch.setattr(release_check, "policy_digest", lambda _: "policy")
    monkeypatch.setattr(release_check.EvaluationReport, "model_validate_json", lambda _: object())
    monkeypatch.setattr(release_check, "validate_eval_report", lambda *args, **kwargs: None)

    release_check.check_evals()

    workspace = Path(str(observed["cwd"]))
    environment = observed["env"]
    assert isinstance(environment, dict)
    assert workspace != Path(__file__).resolve().parents[2]
    assert environment["USERPROFILE"] == str(workspace)
    assert environment["APPDATA"] == str(workspace / "AppData")
