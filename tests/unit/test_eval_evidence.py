from __future__ import annotations

from decimal import Decimal

from evals.fixtures_loader import load_fixtures
from evals.report import generate_policy_summary
from evals.runner import EvaluationRunner
from evals.schema import (
    EvaluationFixture,
    EvaluationPolicy,
    ExecutionScript,
    OracleSpec,
    OracleType,
    ScriptedModelResponse,
    ScriptedToolCall,
    ScriptedUsage,
    TaskEvalResult,
)


def _result(*, completed: bool, cost: str) -> TaskEvalResult:
    return TaskEvalResult(
        fixture_id="evidence-fixture",
        policy=EvaluationPolicy.AUTO,
        completed=completed,
        passed_oracle=completed,
        wall_time_seconds=1.0,
        total_cost_usd=Decimal(cost),
        models_used=(),
        assignments_count=0,
        escalations_count=0,
        interrupts_count=0,
    )


def test_policy_summary_includes_failed_spend_in_cost_per_success() -> None:
    summary = generate_policy_summary(
        [_result(completed=True, cost="2.00"), _result(completed=False, cost="1.00")],
        EvaluationPolicy.AUTO,
    )

    assert summary.failed_work_cost_usd == Decimal("1.00")
    assert summary.cost_per_successful_task_usd == Decimal("3.00")


def test_policy_summary_marks_cost_per_success_unavailable_without_successes() -> None:
    summary = generate_policy_summary(
        [_result(completed=False, cost="1.00")], EvaluationPolicy.AUTO
    )

    assert summary.failed_work_cost_usd == Decimal("1.00")
    assert summary.cost_per_successful_task_usd is None


def test_report_captures_replayable_local_provenance() -> None:
    fixture = EvaluationFixture(
        id="provenance-fixture",
        title="Provenance fixture",
        category="trivial",
        prompt="Write result.txt",
        execution=ExecutionScript(
            responses=(
                ScriptedModelResponse(
                    tool_calls=(
                        ScriptedToolCall(
                            name="write_file",
                            args={"file_path": "result.txt", "content": "done"},
                            id="write-result",
                        ),
                    ),
                    usage=ScriptedUsage(input_tokens=1, output_tokens=1, cost_usd=Decimal("0.01")),
                ),
            ),
            final_response=ScriptedModelResponse(
                content="done",
                usage=ScriptedUsage(input_tokens=1, output_tokens=1, cost_usd=Decimal("0.01")),
            ),
        ),
        oracle=OracleSpec(type=OracleType.FILE_CONTENT, target="result.txt", expected="done"),
    )

    report = EvaluationRunner(fixtures=[fixture], policies=[EvaluationPolicy.AUTO]).run()

    assert report.provenance is not None
    assert report.provenance.source_commit
    assert len(report.provenance.source_digest) == 64
    assert len(report.provenance.fixture_digest) == 64
    assert len(report.provenance.catalog_digest) == 64
    assert len(report.provenance.policy_digest) == 64
    assert report.provenance.python_version
    assert report.provenance.command == ("EvaluationRunner.run",)
    assert report.timestamp.tzinfo is not None
    raw = report.raw_records[0]
    assert raw.assignments
    assert raw.usage_records


def test_report_retains_the_invoking_command_in_provenance() -> None:
    fixture = EvaluationFixture(
        id="command-fixture",
        title="Command fixture",
        category="trivial",
        prompt="No-op",
        execution=ExecutionScript(
            final_response=ScriptedModelResponse(
                content="done",
                usage=ScriptedUsage(input_tokens=1, output_tokens=1, cost_usd=Decimal("0.00")),
            )
        ),
        oracle=OracleSpec(type=OracleType.MULTI_ASSERT),
    )

    report = EvaluationRunner(
        fixtures=[fixture],
        policies=[EvaluationPolicy.AUTO],
        command=("python", "scripts/eval_routing.py", "--paired-runtime"),
    ).run()

    assert report.provenance is not None
    assert report.provenance.command == ("python", "scripts/eval_routing.py", "--paired-runtime")


def test_parallel_fixture_completes_the_same_serialized_writes_under_auto() -> None:
    fixture = next(fixture for fixture in load_fixtures() if fixture.id == "par-01")

    report = EvaluationRunner(fixtures=[fixture], policies=[EvaluationPolicy.AUTO]).run()

    assert report.results[0].passed_oracle
    assert report.results[0].child_peak_active == 3


def test_runtime_timeout_retains_a_failed_cell_record() -> None:
    fixture = next(fixture for fixture in load_fixtures() if fixture.id == "par-01")

    report = EvaluationRunner(
        fixtures=[fixture],
        policies=[EvaluationPolicy.AUTO],
        cell_timeout_seconds=0.001,
    ).run()

    assert not report.results[0].completed
    assert report.raw_records[0].error == "runtime execution timed out after 0.0s"
