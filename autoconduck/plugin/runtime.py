"""Plugin runtime — deterministic orchestration entrypoint."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _new_task_id() -> str:
    return uuid.uuid4().hex[:8]


def _sanitize_goal(goal: str) -> str:
    s = str(goal or "").strip()
    if len(s) > 8000:
        s = s[:8000] + "...[truncated]"
    return s


async def start_task(
    session_id: str,
    goal: str,
    checks: list[str] | None = None,
    *,
    workspace_root: Path | str | None = None,
    allowed_scope: list[str] | None = None,
    cfg: Any | None = None,
    client: Any | None = None,
    model: str | None = None,
    max_rounds: int | None = None,
    time_budget_s: float | None = None,
) -> dict[str, Any]:
    """
    Internal task execution entrypoint.
    Note: Python proof-path executor loop (executor_loop.py, synthesis.py, tools.py)
    was removed in Phase 1.
    """
    if cfg is None:
        try:
            from autoconduck.config.manager import get_config as _gc

            cfg = _gc()
        except Exception:
            cfg = None

    if not getattr(getattr(cfg, "plugins", None), "execute_enabled", False):
        return {"status": "disabled", "error": "execute_enabled must be true to use internal executor."}

    return {
        "status": "disabled",
        "error": "Legacy Python executor proof path removed in Phase 1.",
    }
