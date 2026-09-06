from __future__ import annotations

import pytest
from pydantic import ValidationError

from rudder.domain.plans import ExecutionPlan, PlanNode, PlanNodeKind


def _node(local_id: str, *depends_on: str) -> PlanNode:
    return PlanNode(
        local_id=local_id,
        kind=PlanNodeKind.AGENT,
        objective=local_id,
        depends_on=depends_on,
    )


def test_execution_plan_round_trips_a_valid_dependency_graph() -> None:
    plan = ExecutionPlan(
        schema_version=1,
        policy_version="adaptive-v1",
        revision=1,
        nodes=(_node("inspect"), _node("implement", "inspect")),
    )
    assert ExecutionPlan.model_validate_json(plan.model_dump_json()) == plan


@pytest.mark.parametrize(
    ("nodes", "code"),
    [
        ((_node("a", "missing"),), "plan.invalid_dependency"),
        ((_node("a"), _node("a")), "plan.duplicate_node"),
        ((_node("a", "b"), _node("b", "a")), "plan.cycle"),
    ],
)
def test_execution_plan_rejects_invalid_graphs(nodes: tuple[PlanNode, ...], code: str) -> None:
    with pytest.raises(ValidationError, match=code):
        ExecutionPlan(schema_version=1, policy_version="adaptive-v1", revision=1, nodes=nodes)
