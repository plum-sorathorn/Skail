"""Execution handoff formatting for universal client coding harnesses."""
from __future__ import annotations

from typing import Any
import json


class ExecutionHandoff(str):
    """String subclass representing formatted handoff markdown with optional attached tool_calls."""

    content: str
    tool_calls: list[dict[str, Any]] | None

    def __new__(cls, content: str, tool_calls: list[dict[str, Any]] | None = None):
        obj = super().__new__(cls, content)
        obj.content = content
        obj.tool_calls = tool_calls
        return obj

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"content": self.content}
        if self.tool_calls:
            data["tool_calls"] = self.tool_calls
        return data


def render_plan_summary_for_user(plan: Any, subagent_outputs: dict[str, str] | None = None) -> str:
    """Format a clean, concise execution plan summary with agent assignments for user-visible stream."""
    if not plan:
        return "Execution plan ready."
    from autoconduck.orchestrator.fan_out import build_harness_fan_out_plan
    fan_out = build_harness_fan_out_plan(plan)
    lines = ["SYNTHESIZED EXECUTION PLAN & AGENT ASSIGNMENTS:"]
    task_type = getattr(plan, "task_type", None)
    confidence = getattr(plan, "confidence", None)
    if task_type:
        conf_str = f"{float(confidence) * 100:.0f}%" if confidence is not None else "n/a"
        lines.append(f"task: {task_type} | confidence: {conf_str}")
    if fan_out.batches:
        for b in fan_out.batches:
            lines.append(f"• {b.batch_label}:")
            for a in b.agents:
                scope_str = f" [{', '.join(a.scope[:2])}]" if a.scope else ""
                lines.append(f"  - {a.agent_label} ({a.role}) => {a.goal}{scope_str}")
    elif hasattr(plan, "summary") and plan.summary:
        lines.append(f"• {plan.summary}")
    else:
        lines.append("• Execute synthesized directives using available tools.")
    return "\n".join(lines)


def format_execution_handoff(
    plan: Any,
    subagent_outputs: dict[str, str],
    compacted: str,
    user_agent: str = "",
    client_type: str | None = None,
    is_nested: bool = False,
    decision: str | None = None,
) -> ExecutionHandoff:
    """Format a clean, structured implementation plan with verified context for the client agent.

    Translates the abstract execution DAG into harness-specific directives for outer
    agent execution (omp batching, Claude Code Task tools, OpenCode subagents, or generic checklists).
    """
    sections: list[str] = []

    summary_header = (plan.summary if plan and plan.summary else "Multi-agent task analysis completed.").strip()
    sections.append(f"## Implementation Plan & Verified Context\n\n{summary_header}")

    subtasks = plan.subtasks if plan and plan.subtasks else []

    if subtasks:
        sections.append("### Subtask Breakdown")
        for i, st in enumerate(subtasks, 1):
            st_id = getattr(st, "id", f"task_{i}")
            findings = subagent_outputs.get(st_id, "").strip()
            scope = getattr(st, "scope", []) or []
            scope_str = ", ".join(f"`{s}`" for s in scope) if scope else "General workspace"
            deps = getattr(st, "depends_on", []) or []
            deps_str = ", ".join(f"`{d}`" for d in deps) if deps else "None (independent)"
            contract = getattr(st, "output_contract", None)
            verify_list = getattr(contract, "verify", None) if contract and not isinstance(contract, str) else None
            verify_cmds = ", ".join(f"`{v}`" for v in verify_list) if verify_list else ""

            goal = getattr(st, "goal", "")
            st_block = [f"#### {i}. `{st_id}`: {goal}"]
            st_block.append(f"- **Scope**: {scope_str}")
            st_block.append(f"- **Dependencies**: {deps_str}")
            if verify_cmds:
                st_block.append(f"- **Verification**: {verify_cmds}")
            constraints = getattr(st, "constraints", []) or []
            if constraints:
                st_block.append(f"- **Constraints**: {'; '.join(constraints)}")
            verified_ctx = getattr(st, "verified_context", None)
            if findings:
                st_block.append(f"- **Analyst Findings & Key Symbols**:\n  {findings}")
            elif verified_ctx:
                st_block.append(f"- **Verified Context**:\n  " + "\n  ".join(f"• {c}" for c in verified_ctx))
            sections.append("\n".join(st_block))

    if compacted and not subtasks:
        sections.append(f"### Key Findings & Architecture\n\n{compacted}")

    from autoconduck.harnesses import resolve_adapter_for_request

    adapter = resolve_adapter_for_request(client_type=client_type, user_agent=user_agent)
    directives_md = adapter.render_plan(plan)
    sections.append(directives_md)

    # Structured content is additive: old consumers still receive the prose above.
    try:
        from autoconduck.orchestrator.fan_out import build_harness_fan_out_plan

        fan_out_plan = build_harness_fan_out_plan(plan, max_subagents=4, client_type=client_type)
        phases = getattr(plan, "phases", None) or [
            {"id": getattr(st, "id", ""), "goal": getattr(st, "goal", ""),
             "dependencies": getattr(st, "depends_on", []), "scope": getattr(st, "scope", []),
             "status": "pending", "execution_mode": "harness"}
            for st in subtasks
        ]
        phase_data = []
        for phase in phases:
            item = phase.model_dump() if hasattr(phase, "model_dump") else dict(phase)
            phase_data.append({key: item.get(key) for key in (
                "id", "goal", "dependencies", "parallel_group", "parallel_to",
                "post_condition", "verify", "status", "evidence", "execution_mode")})
        contract = {
            "schema_version": "0.4",
            "plan_id": getattr(plan, "plan_id", "") or None,
            "plan_revision": getattr(plan, "revision", 0),
            "decision": decision or ("end" if getattr(plan, "terminal_decision", None) else "keep"),
            "execution_authority": "harness",
            "phases": phase_data,
            "fan_out": fan_out_plan.to_contract_dict(),
            "ledger": (getattr(plan, "ledger", []) or [])[-8:],
        }
        sections.insert(1, "### Session Execution Contract\n```json\n" + json.dumps(contract, ensure_ascii=False) + "\n```")
        sections.insert(2, "Parallel annotations are advisory; the harness may fan out phases when safe and remains responsible for execution.")
    except Exception:
        pass

    return ExecutionHandoff("\n\n".join(sections), tool_calls=None)
