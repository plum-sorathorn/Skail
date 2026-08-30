"""Plugin synthesis — deterministic template from ledger facts."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def render_report(
    session_id: str,
    task_id: str,
    goal: str,
    outcome: str,
    rounds: int,
    tools_used: list[str],
    files_touched: list[str],
    errors: list[str],
    extra_notes: str | None = None,
    llm_synthesis_enabled: bool = False,
) -> str:
    """
    Deterministic markdown report from ledger facts.
    If llm_synthesis_enabled is True, append honest stub annotation (no LLM call).
    """
    try:
        lines: list[str] = []
        lines.append(f"# Task Report — {task_id}")
        lines.append("")
        lines.append(f"**Session:** `{session_id}`  |  **Task:** `{task_id}`")
        lines.append("")
        lines.append(f"**Goal:** {goal or '(none)'}")
        lines.append("")
        lines.append(f"**Outcome:** {outcome or 'unknown'}")
        lines.append("")
        lines.append(f"**Rounds:** {rounds}")
        lines.append("")
        tools_line = ", ".join(f"`{t}`" for t in tools_used) if tools_used else "(none)"
        lines.append(f"**Tools used:** {tools_line}")
        lines.append("")
        files_line = ", ".join(f"`{f}`" for f in files_touched) if files_touched else "(none)"
        lines.append(f"**Files touched:** {files_line}")
        lines.append("")
        if errors:
            lines.append("**Errors:**")
            for e in errors[:20]:
                lines.append(f"- {e}")
            lines.append("")
        else:
            lines.append("**Errors:** none")
            lines.append("")
        if extra_notes:
            lines.append("**Notes:**")
            lines.append(extra_notes.strip())
            lines.append("")
        if llm_synthesis_enabled:
            lines.append("> _llm-synthesis-not-wired: config `plugins.llm_synthesis_enabled` is True, "
                         "but no LLM call was made in v1. This is the deterministic template._")
            lines.append("")
        lines.append("---")
        lines.append("_Generated deterministically from ledger facts (no SLM/LLM). _")
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("render_report failed: %s", exc)
        return f"# Task Report — {task_id}\n\nOutcome: {outcome}\n[render error: {exc}]"


def llm_synthesis_stub(facts: dict[str, Any]) -> str:
    """Honest stub — returns deterministic render with annotation."""
    return render_report(
        session_id=str(facts.get("session_id", "")),
        task_id=str(facts.get("task_id", "")),
        goal=str(facts.get("goal", "")),
        outcome=str(facts.get("outcome", "")),
        rounds=int(facts.get("rounds", 0) or 0),
        tools_used=list(facts.get("tools_used", []) or []),
        files_touched=list(facts.get("files_touched", []) or []),
        errors=list(facts.get("errors", []) or []),
        extra_notes=facts.get("notes"),
        llm_synthesis_enabled=True,
    )
