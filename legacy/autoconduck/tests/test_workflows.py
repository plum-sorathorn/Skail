from pathlib import Path

import pytest

from autoconduck.plugin.workflows import TaskPlan, WorkflowStore, approve_verifier, validate_patch_paths


def test_workflow_store_round_trips_a_durable_task_plan(tmp_path):
    store = WorkflowStore(tmp_path)
    plan = TaskPlan.new("s1", "refactor", ["src/**"], ["python -m pytest"], risk="high")
    store.save(plan)

    loaded = store.load(plan.id)
    assert loaded.goal == "refactor"
    assert loaded.status == "pending"
    assert loaded.acceptance_checks == ["python -m pytest"]


def test_patch_validation_rejects_paths_outside_declared_scope():
    assert validate_patch_paths(["src/a.py", "src/b.py"], ["src/**"]) == []
    assert validate_patch_paths(["src/a.py", "README.md"], ["src/**"]) == ["README.md"]


def test_task_plan_requires_an_acceptance_check_for_high_risk_work():
    with pytest.raises(ValueError, match="acceptance check"):
        TaskPlan.new("s1", "refactor", ["src/**"], [], risk="high")


def test_verifier_rejection_keeps_workflow_in_review(tmp_path):
    plan = TaskPlan.new("s1", "change", ["src/**"], ["python -m pytest"])
    approve_verifier(plan, approved=False, evidence=["test failed"])
    assert plan.status == "needs_review"
    assert plan.verifier["approved"] is False
