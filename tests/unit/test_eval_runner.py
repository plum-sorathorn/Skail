from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from evals.report import compare_policies, generate_policy_summary, render_markdown_report
from evals.runner import (
    EvaluationRunner,
    check_route_invariants,
    default_eval_candidates,
    evaluate_oracle,
)
from evals.schema import (
    EvaluationFixture,
    EvaluationPolicy,
    ExecutionScript,
    OracleSpec,
    OracleType,
    RouteInvariants,
    ScriptedModelResponse,
    ScriptedToolCall,
    ScriptedUsage,
    TaskEvalResult,
)
from rudder.domain.ids import new_assignment_id, new_reservation_id, new_task_id
from rudder.domain.routing import RoutingMode, TaskAssignment
from rudder.routing.requirements import RequirementBuilder, TaskRisk
from rudder.routing.selector import RouteFailure, select_model


def _execution_script(*, target: str, content: str) -> ExecutionScript:
    return ExecutionScript(
        responses=(
            ScriptedModelResponse(
                tool_calls=(
                    ScriptedToolCall(
                        name="write_file",
                        args={"file_path": target, "content": content},
                        id="write-result",
                    ),
                ),
                usage=ScriptedUsage(
                    input_tokens=11,
                    output_tokens=7,
                    cost_usd=Decimal("0.012"),
                ),
            ),
        ),
        final_response=ScriptedModelResponse(
            content="Fixture work completed through Rudder tools.",
            usage=ScriptedUsage(
                input_tokens=13,
                output_tokens=5,
                cost_usd=Decimal("0.008"),
            ),
        ),
    )


def test_oracle_evaluation_file_exists_and_content(tmp_path: Path) -> None:
    test_file = tmp_path / "output.txt"
    test_file.write_text("hello world\nline 2", encoding="utf-8")

    # Positive exists
    spec_exists = OracleSpec(type=OracleType.FILE_EXISTS, target="output.txt")
    passed, err = evaluate_oracle(tmp_path, spec_exists)
    assert passed
    assert err is None

    # Negative exists
    spec_missing = OracleSpec(type=OracleType.FILE_EXISTS, target="missing.txt")
    passed, err = evaluate_oracle(tmp_path, spec_missing)
    assert not passed
    assert "does not exist" in str(err)

    # Positive contains
    passed, err = evaluate_oracle(
        tmp_path,
        OracleSpec(type=OracleType.FILE_CONTAINS, target="output.txt", expected="hello world"),
    )
    assert passed

    # Negative contains
    passed, err = evaluate_oracle(
        tmp_path,
        OracleSpec(type=OracleType.FILE_CONTAINS, target="output.txt", expected="goodbye"),
    )
    assert not passed

    # Positive content
    exact_file = tmp_path / "exact.txt"
    exact_file.write_text("exact content", encoding="utf-8")
    passed, err = evaluate_oracle(
        tmp_path,
        OracleSpec(type=OracleType.FILE_CONTENT, target="exact.txt", expected="exact content"),
    )
    assert passed


def test_oracle_evaluation_multi_assert(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")

    spec = OracleSpec(
        type=OracleType.MULTI_ASSERT,
        assertions=(
            {"type": "file_exists", "target": "a.txt"},
            {"type": "file_content", "target": "b.txt", "expected": "b"},
        ),
    )
    passed, err = evaluate_oracle(tmp_path, spec)
    assert passed
    assert err is None


def test_route_invariants_detect_floor_and_cost_violations() -> None:
    fixture = EvaluationFixture(
        id="fix-1",
        title="Check invariants",
        category="complex",
        role="implementer",
        prompt="Do something complex",
        oracle=OracleSpec(type=OracleType.FILE_EXISTS, target="out.txt"),
        route_invariants=RouteInvariants(
            min_floor=0.70,
            max_cost_usd=Decimal("0.50"),
            forbid_models=("forbidden-model",),
        ),
    )

    asgn = TaskAssignment(
        assignment_id=new_assignment_id(),
        task_id=new_task_id(),
        attempt_number=1,
        provider="prov",
        model="forbidden-model",
        routing_mode=RoutingMode.AUTO,
        capability_floor=0.50,
        estimated_attempt_cost_usd=Decimal("1.00"),
        reservation_id=new_reservation_id(),
        catalog_revision="rev1",
    )

    defects = check_route_invariants(fixture, [asgn], Decimal("1.00"))
    assert len(defects) == 3
    assert any("floor" in d for d in defects)
    assert any("forbidden" in d for d in defects)
    assert any("exceeded max" in d for d in defects)


def test_evaluation_runner_runs_deterministic_fake_suite() -> None:
    fixtures = [
        EvaluationFixture(
            id="test-trivial",
            title="Trivial task",
            category="trivial",
            role="implementer",
            risk=TaskRisk.TRIVIAL,
            prompt="Write hello.txt",
            execution=_execution_script(target="hello.txt", content="hello\n"),
            oracle=OracleSpec(type=OracleType.FILE_EXISTS, target="hello.txt"),
        ),
        EvaluationFixture(
            id="test-parallel",
            title="Parallel task",
            category="parallel",
            role="implementer",
            risk=TaskRisk.ROUTINE,
            prompt="Write math.txt",
            parallel_eligible=True,
            execution=_execution_script(target="math.txt", content="math\n"),
            oracle=OracleSpec(type=OracleType.FILE_EXISTS, target="math.txt"),
        ),
    ]

    runner = EvaluationRunner(
        fixtures=fixtures,
        policies=(
            EvaluationPolicy.AUTO,
            EvaluationPolicy.QUALITY,
            EvaluationPolicy.ECONOMY,
            EvaluationPolicy.SERIAL,
            EvaluationPolicy.NO_DELEGATION,
        ),
    )

    report = runner.run()

    assert report.fixture_count == 2
    assert len(report.results) == 10  # 2 fixtures * 5 policies
    assert report.policy_summaries[EvaluationPolicy.AUTO.value].completion_rate == 1.0
    assert report.policy_summaries[EvaluationPolicy.QUALITY.value].completion_rate == 1.0, [
        (result.error, result.safety_defects)
        for result in report.results
        if result.policy is EvaluationPolicy.QUALITY
    ]
    assert report.comparison is not None
    # The fixture executor uses real Rudder tools.  This small suite does not
    # create a genuine parallel workload, so it must not manufacture a speedup.
    assert not report.comparison.all_gates_passed

    # Scripted provider usage is runtime evidence, not a route estimate.
    auto_cost = report.policy_summaries[EvaluationPolicy.AUTO.value].median_cost_usd
    quality_cost = report.policy_summaries[EvaluationPolicy.QUALITY.value].median_cost_usd
    assert auto_cost == quality_cost == Decimal("0.02")

    # Markdown rendering should produce formatted tables
    md = render_markdown_report(report)
    assert "Rudder Routing & Orchestration Evaluation Report" in md
    assert "SPEC.md Section 21 Acceptance Gates" in md
    assert "GATES FAILED" in md


def test_oracle_mutation_changes_scoring_without_changing_execution_record() -> None:
    fixture = EvaluationFixture(
        id="oracle-independent",
        title="Oracle-independent execution",
        category="trivial",
        prompt="Write result.txt",
        execution=_execution_script(target="result.txt", content="expected\n"),
        oracle=OracleSpec(
            type=OracleType.FILE_CONTENT,
            target="result.txt",
            expected="expected",
        ),
    )
    policy = [EvaluationPolicy.AUTO]

    passing = EvaluationRunner(fixtures=[fixture], policies=policy).run()
    failing = EvaluationRunner(
        fixtures=[
            fixture.model_copy(
                update={"oracle": fixture.oracle.model_copy(update={"expected": "different"})}
            )
        ],
        policies=policy,
    ).run()

    assert passing.results[0].completed
    assert not failing.results[0].completed
    assert passing.raw_records[0].model_copy(update={"wall_time_seconds": 0.0}) == (
        failing.raw_records[0].model_copy(update={"wall_time_seconds": 0.0})
    )
    assert passing.raw_records[0].evidence_class == "synthetic_offline"


def test_scripted_usage_is_recorded_independently_of_route_estimates() -> None:
    fixture = EvaluationFixture(
        id="scripted-usage",
        title="Scripted usage",
        category="trivial",
        prompt="Write cost.txt",
        execution=_execution_script(target="cost.txt", content="cost\n"),
        oracle=OracleSpec(type=OracleType.FILE_CONTENT, target="cost.txt", expected="cost"),
    )
    inflated_candidates = tuple(
        candidate.model_copy(update={"estimated_cost_usd": Decimal("99.00")})
        for candidate in default_eval_candidates()
    )

    report = EvaluationRunner(
        fixtures=[fixture], policies=[EvaluationPolicy.AUTO], candidates=inflated_candidates
    ).run()

    assert report.results[0].total_cost_usd == Decimal("0.020")
    assert report.raw_records[0].usage_cost_usd == Decimal("0.020")


def test_disabling_runtime_writes_fails_a_required_mutation_fixture() -> None:
    fixture = EvaluationFixture(
        id="writes-disabled",
        title="Writes disabled",
        category="trivial",
        prompt="Write blocked.txt",
        execution=_execution_script(target="blocked.txt", content="blocked\n"),
        oracle=OracleSpec(
            type=OracleType.FILE_CONTENT,
            target="blocked.txt",
            expected="blocked",
        ),
    )

    report = EvaluationRunner(
        fixtures=[fixture],
        policies=[EvaluationPolicy.AUTO],
        runtime_writes_enabled=False,
    ).run()

    assert not report.results[0].completed
    assert not report.results[0].passed_oracle


def test_missing_execution_script_cannot_be_scored_as_completed() -> None:
    fixture = EvaluationFixture(
        id="missing-script",
        title="Missing script",
        category="trivial",
        prompt="Do no work",
        initial_files={"already-there.txt": "present\n"},
        oracle=OracleSpec(type=OracleType.FILE_EXISTS, target="already-there.txt"),
    )

    report = EvaluationRunner(fixtures=[fixture], policies=[EvaluationPolicy.AUTO]).run()

    assert not report.results[0].completed
    assert not report.results[0].passed_oracle
    assert report.raw_records[0].error == "fixture execution script is required"


def test_child_run_gate_records_concurrent_timing() -> None:
    import asyncio

    from rudder.runtime.deepagents_adapter import ChildRunGate

    async def scenario() -> ChildRunGate:
        gate = ChildRunGate(max_children=3)

        async def op() -> str:
            await asyncio.sleep(0.05)
            return "ok"

        await asyncio.gather(*(gate.run(f"t{i}", op) for i in range(3)))
        return gate

    gate = asyncio.run(scenario())
    assert gate.peak_active == 3
    assert gate.child_wall_seconds < 0.15
    assert gate.child_total_seconds >= 0.15
    assert len(gate.completed) == 3


def test_task_eval_result_child_metric_defaults() -> None:
    result = TaskEvalResult(
        fixture_id="par-01",
        policy=EvaluationPolicy.AUTO,
        completed=True,
        passed_oracle=True,
        wall_time_seconds=0.5,
        total_cost_usd=Decimal("0.00"),
        models_used=("fake",),
        assignments_count=1,
        escalations_count=0,
        interrupts_count=0,
    )
    assert result.child_wall_seconds == 0.0
    assert result.child_peak_active == 0
    assert result.child_count == 0


def test_default_candidates_include_manual_child_pin() -> None:
    candidates = default_eval_candidates()
    pins = {(c.profile.provider, c.profile.model) for c in candidates}
    assert ("fake", "explorer") in pins

    reqs = RequirementBuilder().build(
        role="explorer", risk=TaskRisk.ROUTINE, mode=RoutingMode.MANUAL
    )
    selection = select_model(candidates, reqs, manual_model=("fake", "explorer"))
    assert not isinstance(selection, RouteFailure)
    assert selection.candidate.profile.model == "explorer"
    assert not selection.candidate.profile.auto_eligible


def test_fixed_model_baselines_pin_models_and_record_executed_assignments() -> None:
    fixture = EvaluationFixture(
        id="fixed-baseline",
        title="Fixed baseline",
        category="routine",
        role="implementer",
        risk=TaskRisk.ROUTINE,
        prompt="Write baseline.txt",
        execution=_execution_script(target="baseline.txt", content="baseline\n"),
        oracle=OracleSpec(type=OracleType.FILE_EXISTS, target="baseline.txt"),
    )

    report = EvaluationRunner(
        fixtures=[fixture],
        policies=(EvaluationPolicy.ECONOMY, EvaluationPolicy.QUALITY),
    ).run()

    expected_models = {
        EvaluationPolicy.ECONOMY: "eval-provider:eval-mini",
        EvaluationPolicy.QUALITY: "eval-provider:eval-flagship",
    }
    for policy, expected_model in expected_models.items():
        controls = report.policy_controls[policy.value]
        assert controls.lead_model == expected_model
        assert controls.child_model == expected_model

        raw_record = next(record for record in report.raw_records if record.policy is policy)
        assert raw_record.assignments
        assert {
            f"{assignment.provider}:{assignment.model}" for assignment in raw_record.assignments
        } == {expected_model}
        assert {assignment.routing_mode for assignment in raw_record.assignments} == {
            RoutingMode.MANUAL
        }


def test_fixed_model_baseline_records_delegated_assignment_lineage() -> None:
    fixture = EvaluationFixture(
        id="fixed-child-baseline",
        title="Fixed child baseline",
        category="routine",
        role="implementer",
        risk=TaskRisk.ROUTINE,
        prompt="Ask an explorer to inspect the workspace",
        initial_files={"input.txt": "input\n"},
        execution=ExecutionScript(
            responses=(
                ScriptedModelResponse(
                    content="Delegating the inspection.",
                    tool_calls=(
                        ScriptedToolCall(
                            name="task",
                            args={
                                "description": "Inspect the workspace",
                                "subagent_type": "explorer",
                            },
                            id="delegated-inspection",
                        ),
                    ),
                    usage=ScriptedUsage(
                        input_tokens=11,
                        output_tokens=7,
                        cost_usd=Decimal("0.012"),
                    ),
                ),
            ),
            final_response=ScriptedModelResponse(
                content=(
                    '{"status":"succeeded","summary":"Inspection completed.",'
                    '"verification":[{"criterion":"inspection","passed":true,'
                    '"evidence":"input.txt:1"}]}'
                ),
                usage=ScriptedUsage(
                    input_tokens=13,
                    output_tokens=5,
                    cost_usd=Decimal("0.008"),
                ),
            ),
        ),
        oracle=OracleSpec(type=OracleType.MULTI_ASSERT),
    )

    report = EvaluationRunner(
        fixtures=[fixture],
        policies=(EvaluationPolicy.ECONOMY,),
    ).run()

    assignments = report.raw_records[0].assignments
    assert len(assignments) > 1
    assert assignments[0].model == "eval-mini"
    assert assignments[1].model == "eval-mini"
    assert assignments[0].routing_mode is RoutingMode.MANUAL
    assert assignments[1].routing_mode is RoutingMode.MANUAL
    assert assignments[-1].model == "eval-mini"


def test_parallel_gate_uses_end_to_end_wall_time_not_child_only_timing() -> None:
    fixture = EvaluationFixture(
        id="parallel-wall",
        title="Parallel wall time",
        category="parallel",
        role="implementer",
        prompt="Run parallel work",
        parallel_eligible=True,
        oracle=OracleSpec(type=OracleType.FILE_EXISTS, target="done.txt"),
    )
    results = [
        TaskEvalResult(
            fixture_id=fixture.id,
            policy=EvaluationPolicy.AUTO,
            completed=True,
            passed_oracle=True,
            wall_time_seconds=1.0,
            total_cost_usd=Decimal("1.00"),
            models_used=("model",),
            assignments_count=1,
            escalations_count=0,
            interrupts_count=0,
            child_wall_seconds=0.2,
            child_count=3,
        ),
        TaskEvalResult(
            fixture_id=fixture.id,
            policy=EvaluationPolicy.SERIAL,
            completed=True,
            passed_oracle=True,
            wall_time_seconds=0.9,
            total_cost_usd=Decimal("1.00"),
            models_used=("model",),
            assignments_count=1,
            escalations_count=0,
            interrupts_count=0,
            child_wall_seconds=0.6,
            child_count=3,
        ),
    ]
    summaries = {
        policy.value: generate_policy_summary(results, policy)
        for policy in (EvaluationPolicy.AUTO, EvaluationPolicy.SERIAL)
    }

    comparison = compare_policies(summaries, results, [fixture])

    assert comparison.speedup_pct < 0
    assert not comparison.gate_parallel_passed


def test_evaluator_reports_only_runtime_observed_escalations() -> None:
    fixture = EvaluationFixture(
        id="complex-no-failure",
        title="Complex successful task",
        category="complex",
        role="implementer",
        risk=TaskRisk.COMPLEX,
        prompt="Write result.txt",
        execution=_execution_script(target="result.txt", content="result\n"),
        oracle=OracleSpec(type=OracleType.FILE_EXISTS, target="result.txt"),
    )

    report = EvaluationRunner(
        fixtures=[fixture],
        policies=[EvaluationPolicy.ECONOMY],
    ).run()

    assert report.results[0].escalations_count == 0
