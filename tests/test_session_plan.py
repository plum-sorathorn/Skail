import pytest
from pydantic import ValidationError

from autoconduck.routing.slm_planner import (
    ExecutionPlan,
    Phase,
    PlanMutation,
    apply_plan_mutation,
    plan_completion_decision,
)
from autoconduck.orchestrator.handoff import format_execution_handoff


def make_plan() -> ExecutionPlan:
    return ExecutionPlan(
        route="dynamic_dag",
        task_type="refactor",
        plan_id="plan-test",
        phases=[
            Phase(id="recon", goal="Inspect the code", execution_mode="autoconduck_recon"),
            Phase(id="verify", goal="Run verification", dependencies=["recon"], verify=["pytest"], status="pending"),
        ],
    )


def test_explicit_session_phases_reject_duplicate_ids_and_cycles():
    with pytest.raises(ValidationError):
        ExecutionPlan(phases=[Phase(id="x", goal="one"), Phase(id="x", goal="two")])
    with pytest.raises(ValidationError):
        ExecutionPlan(phases=[Phase(id="a", goal="a", dependencies=["b"]), Phase(id="b", goal="b", dependencies=["a"])])


def test_parallel_annotation_cannot_depend_directly():
    with pytest.raises(ValidationError):
        ExecutionPlan(phases=[
            Phase(id="a", goal="a"),
            Phase(id="b", goal="b", dependencies=["a"], parallel_to=["a"]),
        ])


def test_mutation_uses_compare_and_swap_and_preserves_ledger():
    plan = make_plan()
    updated = apply_plan_mutation(plan, PlanMutation(
        plan_id="plan-test", base_revision=0, action="set_status", phase_id="recon", status="completed",
        reason="observed file references",
    ))
    assert updated.revision == 1
    assert updated.phases[0].status == "completed"
    assert updated.ledger[-1]["action"] == "set_status"
    with pytest.raises(ValueError, match="stale"):
        apply_plan_mutation(plan, PlanMutation(plan_id="plan-test", base_revision=1, action="keep"))


def test_append_and_end_are_terminal_only_with_evidence():
    plan = make_plan()
    appended = apply_plan_mutation(plan, PlanMutation(
        plan_id="plan-test", action="append", phase=Phase(id="followup", goal="Follow up"),
    ))
    assert {phase.id for phase in appended.phases} == {"recon", "verify", "followup"}
    terminal = make_plan().model_copy(update={
        "phases": [
            Phase(id="recon", goal="Inspect", status="completed", evidence=["file.py"]),
            Phase(id="verify", goal="Verify", dependencies=["recon"], verify=["pytest"], status="completed", evidence=["2 passed"]),
        ]
    })
    assert plan_completion_decision(terminal) == "completed"
    ended = apply_plan_mutation(terminal, PlanMutation(
        plan_id="plan-test", base_revision=0, action="end", terminal_decision="completed",
    ))
    assert ended.session_status == "terminal"


def test_handoff_contains_versioned_contract_and_remains_string_compatible():
    handoff = format_execution_handoff(make_plan(), {}, "", decision="keep")
    assert isinstance(handoff, str)
    assert '"schema_version": "0.4"' in handoff
    assert '"execution_mode": "autoconduck_recon"' in handoff
