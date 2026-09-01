"""Health checks, OpenAI /v1/models listing, and /stats accounting handlers."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

import autoconduck.config as config_module
from autoconduck.stats import SUPPORTED_WINDOWS, aggregate, aggregate_scopes, filter_records, load_records


def handle_healthz() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


async def handle_models(serve_model_ids: Any) -> dict[str, Any]:
    """List available and virtual routing model IDs."""
    return {
        "object": "list",
        "data": [
            {"id": m, "object": "model", "owned_by": "autoconduck"}
            for m in serve_model_ids(config_module.get_config())
        ],
    }


async def handle_stats(
    decisions: list[dict[str, Any]],
    *,
    session_id: str | None = None,
    window: str | None = None,
) -> dict[str, Any]:
    """Aggregate real-time usage and cost savings statistics."""
    if window is not None and window not in SUPPORTED_WINDOWS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported stats window {window!r}; use one of {', '.join(SUPPORTED_WINDOWS)}",
        )
    records = load_records()
    scopes = aggregate_scopes(records, session_id=session_id)
    usage = scopes["all_time"]
    selected = aggregate(filter_records(records, session_id=session_id, window=window))
    response = {
        "counts": decisions,
        "cost_saved_metered": 0.0,
        "cost_saved_subscription": 0.0,
        "cache_hit_ratio": 0.0,
        "usage": selected["totals"],
        "models": selected["models"],
        "path_counts": selected["paths"],
        "pseudo_counts": selected["pseudos"],
        "oma": selected["oma"],
        "all_time": usage,
        "session": scopes["session"],
        "windows": scopes["windows"],
    }
    try:
        from autoconduck.routing.benchmarks import snapshot_status
        response["benchmark_snapshot"] = snapshot_status()
    except Exception:
        response["benchmark_snapshot"] = {"available": False, "fresh": False, "coverage_models": 0}
    return response
