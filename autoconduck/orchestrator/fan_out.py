"""Harness subagent fan-out coordinator.

Translates internal multi-agent execution plans into explicit, harness-actionable
subagent assignments ("Agent 1 => X, Agent 2 => Y") and topological execution batches
for coding agents supporting parallel workers or background tasks.
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
    prompt: str = ""
    dependencies: list[str] = Field(default_factory=list)
    parallel_group: str | None = None
    scope: list[str] = Field(default_factory=list)
    verification: list[str] = Field(default_factory=list)
    tool_call_template: str = ""


class Batch(BaseModel):
    batch_index: int
    batch_label: str
    mode: str = "parallel"  # "parallel" or "sequential"
    agents: list[AgentAssignment] = Field(default_factory=list)


class FanOutPlan(BaseModel):
    can_fan_out: bool
    batches: list[Batch] = Field(default_factory=list)
    parallel_groups: dict[str, list[AgentAssignment]] = Field(default_factory=dict)
    sequential_fallback: list[AgentAssignment] = Field(default_factory=list)
    fan_out_directives: list[str] = Field(default_factory=list)

    def to_contract_dict(self) -> dict[str, Any]:
        """Produce machine-readable JSON structure for Session Execution Contract."""
        return {
            "supported": self.can_fan_out,
            "batches": [
                {
                    "batch_id": f"batch_{b.batch_index}",
                    "mode": b.mode,
                    "agents": [
                        {
                            "agent_id": a.agent_label,
                            "phase_id": a.phase_id,
                            "role": a.role,
                            "goal": a.goal,
                            "scope": a.scope,
                            "dependencies": a.dependencies,
                            "tool_template": a.tool_call_template,
                        }
                        for a in b.agents
                    ],
                }
                for b in self.batches
            ],
            "fallback_order": [a.phase_id for a in self.sequential_fallback],
        }


def _build_precooked_prompt(role: str, goal: str, scope: list[str], verify: list[str]) -> str:
    """Create a self-contained subagent prompt for tool invocation."""
    scope_str = ", ".join(scope) if scope else "workspace root"
    if role in ("recon", "read", "explore"):
        return f"Analyze the codebase for: {goal}. Files in scope: {scope_str}. Return key architectural symbols, patterns, and relevant line numbers."
    elif role in ("verify", "test"):
        v_str = f" Run verification: {', '.join(verify)}." if verify else ""
        return f"Run verification tests and validate resolution for: {goal}.{v_str}"
    else:
        v_str = f" Verify using: {', '.join(verify)}." if verify else ""
        return f"Implement required code modifications for: {goal}. Target scope: {scope_str}.{v_str}"


def _format_tool_call(role: str, goal: str, prompt: str, verify: list[str], client_type: str | None = None) -> str:
    """Format exact tool call syntax expected by specific harness types."""
    short_goal = goal if len(goal) <= 60 else goal[:57].rstrip() + "..."
    escaped_prompt = prompt.replace('"', '\"')

    if client_type in ("omp", "pi"):
        crit = verify[0] if verify else short_goal
        return f'task(goal="{short_goal}", criteria="{crit}")'
    elif client_type == "opencode":
        agent_type = "Explore" if role in ("recon", "read") else "Build"
        return f'subagent(type="{agent_type}", prompt="{escaped_prompt}")'
    else:
        # Default / Claude Code Task & Agent tool format
        return f'Task(description="{short_goal}", prompt="{escaped_prompt}")'


def build_harness_fan_out_plan(
    plan: Any,
    max_subagents: int = 4,
    client_type: str | None = None,
) -> FanOutPlan:
    """Build structured subagent assignments with topological batching from an ExecutionPlan."""
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

        prompt = _build_precooked_prompt(role, goal, scope, verify or [])
        tool_call = _format_tool_call(role, goal, prompt, verify or [], client_type=client_type)

        assignment = AgentAssignment(
            agent_index=i,
            agent_label=f"Agent {i}",
            role=role,
            phase_id=st_id,
            goal=goal,
            prompt=prompt,
            dependencies=deps,
            parallel_group=pg,
            scope=scope,
            verification=verify or [],
            tool_call_template=tool_call,
        )
        assignments.append(assignment)

        group_key = pg or ("independent" if not deps else f"dependent_{deps[0]}")
        parallel_groups.setdefault(group_key, []).append(assignment)

        dep_str = f" (requires: {', '.join(deps)})" if deps else " (independent)"
        scope_str = f" [Scope: {', '.join(scope[:2])}]" if scope else ""
        directives.append(f"• Agent {i} ({role}){dep_str} => {goal}{scope_str}")

    # Topological batching: Level 0 = zero deps, Level 1 = deps satisfied by Level 0, etc.
    batches: list[Batch] = []
    remaining = list(assignments)
    completed_ids: set[str] = set()
    batch_idx = 1

    while remaining:
        # Pick tasks whose dependencies are satisfied
        ready = [a for a in remaining if not a.dependencies or all(d in completed_ids for d in a.dependencies)]
        if not ready:
            # Cycle / unresolved dependency fallback: take the first remaining task
            ready = [remaining[0]]

        for a in ready:
            remaining.remove(a)
            completed_ids.add(a.phase_id)

        mode = "parallel" if len(ready) > 1 else "sequential"
        label = f"Batch {batch_idx} ({'Parallel — Execute Concurrently Now' if mode == 'parallel' else 'Sequential'})"
        batches.append(Batch(batch_index=batch_idx, batch_label=label, mode=mode, agents=ready))
        batch_idx += 1

    can_fan_out = any(b.mode == "parallel" for b in batches) or len(assignments) > 1

    return FanOutPlan(
        can_fan_out=can_fan_out,
        batches=batches,
        parallel_groups=parallel_groups,
        sequential_fallback=assignments,
        fan_out_directives=directives,
    )


def render_fan_out_directives(
    fan_out_plan: FanOutPlan,
    client_type: str | None = None,
) -> str:
    """Render full markdown execution directives with explicit tool triggers and batch separation."""
    lines: list[str] = [
        "### Execution Directives & Harness Subagent Fan-Out",
        "Proceed with implementation of the subtasks sequentially using available tools (`read`, `edit`, `write`, `bash`).",
    ]

    if not fan_out_plan.can_fan_out or not fan_out_plan.batches:
        return "\n".join(lines)

    lines.append("\n**To the Lead Agent / Harness:**")
    lines.append(
        "If you have a delegation tool (`Task`, `Agent`, `task`, or `subagent`), **invoke multiple tool calls in parallel "
        "in your current turn** for independent tasks in Batch 1. Do not perform Batch 1 sequentially if parallel tools are available."
    )

    for b in fan_out_plan.batches:
        lines.append(f"\n#### {b.batch_label}:")
        for a in b.agents:
            scope_str = ", ".join(a.scope) if a.scope else "general workspace"
            dep_str = ", ".join(a.dependencies) if a.dependencies else "None (Independent)"
            lines.append(f"- **{a.agent_label}** [Role: `{a.role}`, Phase: `{a.phase_id}`]")
            lines.append(f"  - **Goal**: {a.goal}")
            if a.tool_call_template:
                lines.append(f"  - **Tool Call**: `{a.tool_call_template}`")
            lines.append(f"  - **Scope**: `{scope_str}`")
            lines.append(f"  - **Dependencies**: {dep_str}")

    # Fallback instructions
    fallback_seq = " → ".join(a.phase_id for a in fan_out_plan.sequential_fallback)
    lines.append("\n#### Single-Threaded Fallback:")
    lines.append(f"If your harness does not support parallel subagent tools, execute the phases sequentially: {fallback_seq}.")

    return "\n".join(lines)
