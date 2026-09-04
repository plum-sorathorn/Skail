from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from evals.report import render_markdown_report
from evals.runner import (
    EvaluationRunner,
    _default_eval_candidates,
    check_route_invariants,
    evaluate_oracle,
)
from evals.schema import (
    EvaluationFixture,
    EvaluationPolicy,
    OracleSpec,
    OracleType,
    RouteInvariants,
    TaskEvalResult,
)
from rudder.domain.ids import new_assignment_id, new_reservation_id, new_task_id
from rudder.domain.routing import RoutingMode, TaskAssignment
from rudder.routing.requirements import RequirementBuilder, TaskRisk
from rudder.routing.selector import select_model


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
    assert report.policy_summaries[EvaluationPolicy.QUALITY.value].completion_rate == 1.0
    assert report.comparison is not None
    # The fixture executor uses real Rudder tools.  This small suite does not
    # create a genuine parallel workload, so it must not manufacture a speedup.
    assert not report.comparison.all_gates_passed

    # Auto cost should be substantially lower than quality cost
    auto_cost = report.policy_summaries[EvaluationPolicy.AUTO.value].median_cost_usd
    quality_cost = report.policy_summaries[EvaluationPolicy.QUALITY.value].median_cost_usd
    assert auto_cost < quality_cost

    # Markdown rendering should produce formatted tables
    md = render_markdown_report(report)
    assert "Rudder Routing & Orchestration Evaluation Report" in md
    assert "SPEC.md Section 21 Acceptance Gates" in md
    assert "GATES FAILED" in md
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
    candidates = _default_eval_candidates()
    pins = {(c.profile.provider, c.profile.model) for c in candidates}
    assert ("fake", "explorer") in pins

    reqs = RequirementBuilder().build(
        role="explorer", risk=TaskRisk.ROUTINE, mode=RoutingMode.MANUAL
    )
    selection = select_model(candidates, reqs, manual_model=("fake", "explorer"))
    assert selection.candidate.profile.model == "explorer"
    assert not selection.candidate.profile.auto_eligible
