"""Async orchestration runner — Phase 1B stub (DAG removed, plugin handles execution)."""

from __future__ import annotations

from typing import Any


async def run_dynamic_orchestration(
    messages: list[dict[str, Any]],
    pseudo_model: str = "autoconduck",
    on_progress: Any = None,
    plan: Any | None = None,
    **kwargs: Any,
) -> dict[str, Any] | None:
    """Stub: DAG orchestration removed in Phase 1B; use plugin executor."""
    return None
