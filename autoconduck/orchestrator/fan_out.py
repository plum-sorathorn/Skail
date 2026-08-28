"""Harness subagent fan-out coordinator.

Translates internal multi-agent execution plans into explicit, harness-actionable
subagent assignments ("Agent 1 => X, Agent 2 => Y") for coding agents supporting
parallel workers or background tasks.
"""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class AgentAssignment(BaseModel):
    agent_index: int
    agent_label: str
    role: str
    phase_id: str
    goal: str
    dependencies: list[str] = Field(default_factory=list)
    parallel_group: str | None = None
    scope: list[str] = Field(default_factory=list)
    verification: list[str] = Field(default_factory=list)


class FanOutPlan(BaseModel):
    can_fan_out: bool
    parallel_groups: dict[str, list[AgentAssignment]] = Field(default_factory=dict)
    sequential_fallback: list[AgentAssignment] = Field(default_factory=list)
    fan_out_directives: list[str] = Field(default_factory=list)


def build_harness_fan_out_plan(
    plan: Any,
    max_subagents: int = 4,
) -> FanOutPlan:
    """Build structured subagent assignments from an ExecutionPlan.

    Produces clear 'Agent N => ...' assignments and groups them into parallel batches
    for harnesses capable of fanning out concurrent workers.
    """
    subtasks = getattr(plan, "subtasks", []) or []
    if not subtasks:
        return FanOutPlan(can_fan_out=False)

    assignments: list[AgentAssignment] = []
    parallel_groups: dict[str, list[AgentAssignment]] = {}
    directives: list[str] = []

    for i, st in enumerate(subtasks[:max_subagents], 1):
        st_id = getattr(st, "id", f"task_{i}")
        role = getattr(st, "role", "worker")
        goal = getattr(st, "goal", "")
        deps = getattr(st, "depends_on", []) or []
        pg = getattr(st, "parallel_group", None)
        scope = getattr(st, "scope", []) or []
        contract = getattr(st, "output_contract", None)
        verify = getattr(contract, "verify", None) if contract and not isinstance(contract, str) else []

        assignment = AgentAssignment(
            agent_index=i,
            agent_label=f"Agent {i}",
            role=role,
            phase_id=st_id,
            goal=goal,
            dependencies=deps,
            parallel_group=pg,
            scope=scope,
            verification=verify or [],
        )
        assignments.append(assignment)

        group_key = pg or ("independent" if not deps else f"dependent_{deps[0]}")
        parallel_groups.setdefault(group_key, []).append(assignment)

        dep_str = f" (requires: {', '.join(deps)})" if deps else " (independent)"
        scope_str = f" [Scope: {', '.join(scope[:2])}]" if scope else ""
        directives.append(f"• Agent {i} ({role}){dep_str} => {goal}{scope_str}")

    can_fan_out = len(assignments) > 1

    return FanOutPlan(
        can_fan_out=can_fan_out,
        parallel_groups=parallel_groups,
        sequential_fallback=assignments,
        fan_out_directives=directives,
    )
