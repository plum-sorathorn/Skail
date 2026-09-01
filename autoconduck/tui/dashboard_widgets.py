"""TUI dashboard rendering helpers, box formatting, and log visualizers."""

from __future__ import annotations

import re
from typing import Any


DASHBOARD_WINDOWS = ("15m", "1h", "1d", "7d", "30d")


def move_cursor(cursor: int, delta: int, length: int) -> int:
    """Clamp navigation cursor within [0, length - 1]."""
    return 0 if length <= 0 else max(0, min(length - 1, cursor + delta))


def render_log_rows(records: list[dict[str, Any]], cursor: int) -> str:
    """Render compact rich-formatted routing history rows."""
    if not records:
        return "(no routing decisions yet)"
    lines = []
    for index, record in enumerate(records):
        stamp = record.get("time", record.get("timestamp", "--"))
        route = record.get("route", "fast")
        model = record.get("model", record.get("model_used", "--"))
        prompt = (
            str(record.get("prompt", ""))
            .replace("\n", " ")[:40]
            .replace("[", "\\[")
        )
        confidence = record.get("confidence", "--")
        line = (
            f"› {stamp} {route} {model} {prompt} ({confidence})"
            if index == cursor
            else f"  {stamp} {route} {model} {prompt} ({confidence})"
        )
        lines.append(f"[reverse]{line}[/reverse]" if index == cursor else line)
    return "\n".join(lines)


def decision_path(record: dict[str, Any]) -> str:
    """Normalize audit-log routing names for the dashboard."""
    value = str(record.get("path", record.get("route", "FAST"))).upper()
    if "OMP" in value or "AGENT" in value or "DELEGAT" in value:
        return "OMP"
    if "FALLBACK" in value or value in {"ERROR", "UNKNOWN"}:
        return "FALLBACK"
    if value in {"SLOW", "DAG", "DYNAMIC", "SLM"}:
        return "SLOW"
    return "FAST"


def record_value(record: dict[str, Any], *keys: str, default: Any = "—") -> Any:
    for key in keys:
        value = record.get(key)
        if value is not None and value != "":
            return value
    return default


def decision_explanation(record: dict[str, Any]) -> str:
    """Render persisted selection evidence without inventing a decision reason."""
    selection = record.get("selection")
    if not isinstance(selection, dict):
        return "No persisted selection explanation"

    parts: list[str] = []
    task_type = selection.get("task_type")
    if task_type:
        parts.append(f"task={task_type}")
    constraint = selection.get("binding_constraint")
    if constraint:
        parts.append(f"constraint={constraint}")
    floor = selection.get("min_capability_score_applied")
    if floor is not None:
        try:
            parts.append(f"floor={float(floor):.2f}")
        except (TypeError, ValueError):
            pass
    capability_dim = selection.get("binding_capability_dim")
    if capability_dim:
        parts.append(f"dimension={capability_dim}")
    fallback = selection.get("fallback_reason")
    if fallback:
        parts.append(f"fallback={fallback}")
    oma = selection.get("oma")
    if isinstance(oma, dict) and oma.get("reason"):
        parts.append(f"oma={oma['reason']}")
    return "; ".join(parts) if parts else "No persisted selection explanation"


def _completion_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in records if row.get("event_kind") != "oma_gate"]


def _scope_evidence(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Describe which aggregate fields are observed, rather than treating zero as proof."""
    completions = _completion_rows(records)
    latest_selection: dict[str, Any] | None = None
    for row in reversed(completions):
        selection = row.get("selection")
        if isinstance(selection, dict):
            latest_selection = selection
            break

    floor = bias = None
    if latest_selection:
        floor = latest_selection.get("min_capability_score_applied")
        for key in ("session_bias", "bias", "escalation_bias"):
            if key in latest_selection:
                bias = latest_selection[key]
                break

    def has_priced_cost(row: dict[str, Any]) -> bool:
        try:
            return float(row.get("cost", 0) or 0) > 0
        except (TypeError, ValueError):
            return False

    return {
        "has_completions": bool(completions),
        # A persisted zero is ambiguous: it can represent a free model or absent
        # pricing. The dashboard therefore presents it as unknown instead of $0.
        "cost_known": any(has_priced_cost(row) for row in completions),
        "latency_reported": any(
            row.get("latency_ms") is not None or row.get("turn_latency_ms") is not None
            for row in completions
        ),
        "cache_reported": any(
            row.get("cache_read_tokens") is not None or row.get("cache_write_tokens") is not None
            for row in completions
        ),
        "floor": floor,
        "bias": bias,
    }


def build_dashboard_snapshot(
    records: list[dict[str, Any]],
    *,
    session_id: str | None,
    window: str,
    plugins_enabled: bool | None,
) -> dict[str, Any]:
    """Build TUI data from durable stats scopes, keeping global and session facts distinct."""
    if window not in DASHBOARD_WINDOWS:
        raise ValueError(f"Unsupported dashboard window: {window}")

    from autoconduck import stats

    known_session = (
        session_id.strip()
        if isinstance(session_id, str) and session_id.strip() and session_id.strip().lower() != "unknown"
        else None
    )
    persisted = list(records)
    scopes = stats.aggregate_scopes(persisted, session_id=known_session)
    window_rows = stats.filter_records(persisted, window=window)
    session_rows = (
        stats.filter_records(persisted, session_id=known_session) if known_session else []
    )
    session_window_rows = (
        stats.filter_records(persisted, session_id=known_session, window=window)
        if known_session
        else []
    )
    decisions = list(reversed(_completion_rows(session_window_rows)))
    session_scope = scopes["session"]

    return {
        "all_time": scopes["all_time"],
        "window": scopes["windows"][window],
        "window_name": window,
        "window_evidence": _scope_evidence(window_rows),
        "plugin_status": (
            "Enabled" if plugins_enabled is True else "Disabled" if plugins_enabled is False else "Unknown"
        ),
        "session": {
            "id": known_session,
            "status": known_session or "Unknown session",
            "usage": session_scope["usage"] if known_session else None,
            "models": session_scope["models"] if known_session else {},
            "paths": session_scope["paths"] if known_session else {},
            "pseudos": session_scope["pseudos"] if known_session else {},
            "oma": session_scope["oma"] if known_session else {"outcomes": {}},
            "evidence": _scope_evidence(session_rows) if known_session else _scope_evidence([]),
            "decisions": decisions,
        },
    }


def _cell_len(s: str) -> int:
    """Compute visual terminal cell width of markup string."""
    try:
        from rich.text import Text

        return Text.from_markup(s).cell_len
    except Exception:
        return len(re.sub(r"\[/?[a-zA-Z0-9_ =#,-]+\]", "", s))


def _format_box_lines(title: str, lines: list[str], width: int = 76) -> list[str]:
    """Render a structured border box with header title."""
    title_len = _cell_len(title)
    dashes = max(0, width - 6 - title_len)
    top = f"+-- {title} {'-' * dashes}+"
    bottom = f"+{'-' * (width - 2)}+"

    result = [top]
    for line in lines:
        if line.startswith("-") and set(line) == {"-"}:
            result.append(f"+{'-' * (width - 2)}+")
            continue
        l_len = _cell_len(line)
        pad = max(0, width - 4 - l_len)
        result.append(f"| {line}{' ' * pad} |")
    result.append(bottom)
    return result
