"""Persistent, best-effort usage accounting."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import home_dir
from .routing import pricing

import time

_latest_selection: dict[str, Any] = {}
_active_routing: dict[str, Any] = {
    "active": False,
    "path": "FAST",
    "pseudo_model": "skail",
    "selected_model": "none",
    "task_value": 0.0,
    "node": "idle",
    "step_detail": "Idle",
    "plan_id": "",
    "start_time": 0.0,
    "updated_at": 0.0,
}


def active_routing_path() -> Path:
    return home_dir() / "run" / "active_routing.json"


def update_active_routing(**kwargs: Any) -> None:
    _active_routing.update(kwargs)
    _active_routing["updated_at"] = time.time()
    try:
        target = active_routing_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as f:
            json.dump(_active_routing, f)
    except Exception:
        pass


def get_active_routing() -> dict[str, Any]:
    try:
        target = active_routing_path()
        if target.exists():
            with target.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if time.time() - float(data.get("updated_at", 0)) < 6.0:
                    return data
                return {
                    "active": False,
                    "path": "FAST",
                    "pseudo_model": "skail",
                    "selected_model": data.get("selected_model", "none"),
                    "task_value": 0.0,
                    "node": "idle",
                    "step_detail": "Idle",
                }
    except Exception:
        pass
    return dict(_active_routing)


def record_selection(
    task_value: float, target_scaled_cost: float, model: str, config
) -> None:
    if getattr(getattr(config, "selection", None), "expose_value_in_stats", True):
        _latest_selection.update(
            last_task_value=task_value,
            last_target_scaled_cost=target_scaled_cost,
            last_selected_model=model,
        )


def stats_path() -> Path:
    return home_dir() / "run" / "stats.jsonl"


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate cost using catalog entry (price_in/price_out per 1M tokens)."""
    try:
        # Try ModelPool entry first (covers custom + preset merged catalog)
        try:
            from skail.config import get_config
            from skail.routing.model_pool import ModelPool

            cfg = get_config()
            pool = ModelPool(cfg)
            entries = pool._get_model_entries()
            found = next((e for e in entries if e.id == model), None)
            if found is not None:
                price_in = float(getattr(found, "price_in", 0) or getattr(found, "cost_input", 0) or 0)
                price_out = float(getattr(found, "price_out", 0) or getattr(found, "cost_output", 0) or 0)
                if price_in or price_out:
                    return (prompt_tokens * price_in + completion_tokens * price_out) / 1_000_000
        except Exception:
            pass
        # Fallback to curated catalog / litellm costs (PRESETS is provider->list)
        try:
            from skail.presets.model_presets import curated_model_catalog
            for row in curated_model_catalog():
                if row.get("id") == model:
                    price_in = float(row.get("price_in", 0) or 0)
                    price_out = float(row.get("price_out", 0) or 0)
                    if price_in or price_out:
                        return (prompt_tokens * price_in + completion_tokens * price_out) / 1_000_000
                    break
        except Exception:
            pass
        try:
            from skail.presets.presets_ingest import _ingest_litellm_costs
            vals = _ingest_litellm_costs().get(model)
            if isinstance(vals, dict):
                price_in = float(vals.get("price_in", 0) or 0)
                price_out = float(vals.get("price_out", 0) or 0)
                if price_in or price_out:
                    return (prompt_tokens * price_in + completion_tokens * price_out) / 1_000_000
        except Exception:
            pass
        return 0.0
    except Exception:
        return 0.0


import threading
import queue

_stats_queue = queue.Queue()
_OMA_OUTCOMES = frozenset({"not_eligible", "started", "completed", "failed_soft"})

def _stats_worker():
    while True:
        try:
            target, row = _stats_queue.get()
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(row, separators=(",", ":")) + "\n")
            except Exception:
                pass
            finally:
                _stats_queue.task_done()
        except Exception:
            pass

_stats_thread = threading.Thread(target=_stats_worker, daemon=True)
_stats_thread.start()


def flush_stats() -> None:
    try:
        _stats_queue.join()
    except Exception:
        pass


def record_oma_outcomes(session_id: str | None, outcomes: list[str]) -> None:
    """Queue completed OMA gate outcomes without counting them as LLM completions."""
    try:
        for outcome in outcomes:
            if outcome not in _OMA_OUTCOMES:
                continue
            _stats_queue.put(
                (
                    stats_path(),
                    {
                        "stats_version": 2,
                        "event_id": uuid.uuid4().hex,
                        "session_id": session_id or "unknown",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "event_kind": "oma_gate",
                        "oma_outcome": outcome,
                    },
                )
            )
    except Exception:
        pass


def record(
    path: str,
    pseudo_model: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    *,
    cost: float | None = None,
    success: bool = True,
    complexity: float | None = None,
    task_value: float | None = None,
    plan: Any = None,
    route: str | None = None,
    tier: str | None = None,
    latency_ms: float | None = None,
    event_id: str | None = None,
    session_id: str | None = None,
    upstream_model: str | None = None,
    selection: dict[str, Any] | None = None,
    cache_read_tokens: int | None = None,
    cache_write_tokens: int | None = None,
) -> None:
    try:
        prompt_tokens, completion_tokens = int(prompt_tokens), int(completion_tokens)
        # pricing.record_usage is optional (no-op if pricing backend lacks it); isolate so failure never aborts jsonl write
        try:
            fn = getattr(pricing, "record_usage", None)
            if callable(fn):
                fn(model, prompt_tokens, completion_tokens, cost=cost, success=success)
        except Exception:
            pass
        row: dict[str, Any] = {
            "stats_version": 2,
            "event_id": event_id or uuid.uuid4().hex,
            "session_id": session_id or "unknown",
            "ts": datetime.now(timezone.utc).isoformat(),
            "path": path,
            "pseudo_model": pseudo_model,
            "model": model,
            "upstream_model": upstream_model or model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost": cost
            if cost is not None
            else estimate_cost(model, prompt_tokens, completion_tokens),
            "success": bool(success),
        }
        if complexity is not None:
            row["complexity"] = float(complexity)
        if task_value is not None:
            row["task_value"] = float(task_value)
        if route is not None:
            row["route"] = route
        if tier is not None:
            row["tier"] = tier
        if latency_ms is not None:
            row["latency_ms"] = float(latency_ms)
            row["turn_latency_ms"] = float(latency_ms)
        if cache_read_tokens is not None:
            row["cache_read_tokens"] = int(cache_read_tokens)
        if cache_write_tokens is not None:
            row["cache_write_tokens"] = int(cache_write_tokens)
        if selection:
            row["selection"] = selection
        if plan is not None:
            if hasattr(plan, "model_dump"):
                row["plan"] = plan.model_dump()
            elif isinstance(plan, dict):
                row["plan"] = plan
        
        _stats_queue.put((stats_path(), row))
    except Exception:
        pass


def load_records(limit: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with stats_path().open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        rows.append(row)
                except (ValueError, TypeError):
                    continue
    except OSError:
        return []
    return rows[-limit:] if limit is not None else rows


def _record_timestamp(row: dict[str, Any]) -> datetime | None:
    value = row.get("ts")
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _deduplicated(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_event_ids: set[str] = set()
    result: list[dict[str, Any]] = []
    for row in records:
        event_id = row.get("event_id")
        if isinstance(event_id, str) and event_id:
            if event_id in seen_event_ids:
                continue
            seen_event_ids.add(event_id)
        result.append(row)
    return result


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost": 0.0,
        "estimated_frontier_cost": 0.0,
        "estimated_savings_usd": 0.0,
        "savings_percentage": 0.0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }
    models: dict[str, dict[str, Any]] = {}
    pseudo_models: dict[str, dict[str, Any]] = {}
    paths: dict[str, int] = {}
    pseudos: dict[str, int] = {}
    routes: dict[str, int] = {}
    oma_outcomes: dict[str, int] = {}

    # Frontier baseline: ~$5.00/1M in, $15.00/1M out
    FRONTIER_IN_PER_M = 5.00
    FRONTIER_OUT_PER_M = 15.00

    latencies: list[float] = []
    observed_at: list[datetime] = []
    for row in _deduplicated(records):
        if row.get("event_kind") == "oma_gate":
            outcome = row.get("oma_outcome")
            if outcome in _OMA_OUTCOMES:
                oma_outcomes[outcome] = oma_outcomes.get(outcome, 0) + 1
            continue
        selection = row.get("selection")
        oma = selection.get("oma") if isinstance(selection, dict) else None
        outcomes = oma.get("outcomes") if isinstance(oma, dict) else []
        if isinstance(outcomes, list):
            for outcome in outcomes:
                if outcome in _OMA_OUTCOMES:
                    oma_outcomes[outcome] = oma_outcomes.get(outcome, 0) + 1
        p, c = (
            int(row.get("prompt_tokens", 0) or 0),
            int(row.get("completion_tokens", 0) or 0),
        )
        cost = float(row.get("cost", 0) or 0)
        frontier_cost = (p * FRONTIER_IN_PER_M + c * FRONTIER_OUT_PER_M) / 1_000_000

        totals["calls"] += 1
        totals["prompt_tokens"] += p
        totals["completion_tokens"] += c
        totals["total_tokens"] += p + c
        totals["cost"] += cost
        totals["estimated_frontier_cost"] += frontier_cost
        totals["cache_read_tokens"] += int(row.get("cache_read_tokens", 0) or 0)
        totals["cache_write_tokens"] += int(row.get("cache_write_tokens", 0) or 0)

        lat = row.get("latency_ms") or row.get("turn_latency_ms")
        if lat is not None:
            try:
                latencies.append(float(lat))
            except (ValueError, TypeError):
                pass

        model = str(row.get("upstream_model") or row.get("model", "unknown"))
        item = models.setdefault(
            model,
            {
                "calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost": 0.0,
            },
        )
        item["calls"] += 1
        item["prompt_tokens"] += p
        item["completion_tokens"] += c
        item["total_tokens"] += p + c
        item["cost"] += cost

        pseudo = str(row.get("pseudo_model", "unknown"))
        pseudo_item = pseudo_models.setdefault(
            pseudo,
            {
                "calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost": 0.0,
            },
        )
        pseudo_item["calls"] += 1
        pseudo_item["prompt_tokens"] += p
        pseudo_item["completion_tokens"] += c
        pseudo_item["total_tokens"] += p + c
        pseudo_item["cost"] += cost

        paths[str(row.get("path", "unknown"))] = (
            paths.get(str(row.get("path", "unknown")), 0) + 1
        )
        pseudos[pseudo] = pseudos.get(pseudo, 0) + 1
        if "route" in row:
            routes[str(row.get("route"))] = routes.get(str(row.get("route")), 0) + 1
        timestamp = _record_timestamp(row)
        if timestamp is not None:
            observed_at.append(timestamp)

    savings = max(0.0, totals["estimated_frontier_cost"] - totals["cost"])
    totals["estimated_savings_usd"] = savings
    totals["savings_percentage"] = (
        (savings / totals["estimated_frontier_cost"] * 100.0)
        if totals["estimated_frontier_cost"] > 0
        else 0.0
    )
    totals["avg_latency_ms"] = round(sum(latencies) / len(latencies), 1) if latencies else 0.0
    if len(observed_at) >= 2:
        observed_days = max((max(observed_at) - min(observed_at)).total_seconds() / 86400, 1 / 24)
        totals["monthly_projected_cost"] = round(totals["cost"] * 30 / observed_days, 6)
    else:
        totals["monthly_projected_cost"] = 0.0

    result = {
        "totals": totals,
        "models": dict(
            sorted(
                models.items(),
                key=lambda x: (-x[1]["cost"], -x[1]["total_tokens"], x[0]),
            )
        ),
        "pseudo_models": dict(
            sorted(
                pseudo_models.items(),
                key=lambda x: (-x[1]["cost"], -x[1]["total_tokens"], x[0]),
            )
        ),
        "paths": paths,
        "pseudos": pseudos,
        "routes": routes,
        "oma": {"outcomes": oma_outcomes},
    }
    result.update(_latest_selection)
    return result


_WINDOWS_MINUTES = {"15m": 15, "1h": 60, "1d": 1_440, "7d": 10_080, "30d": 43_200}
SUPPORTED_WINDOWS = tuple(_WINDOWS_MINUTES)


def filter_records(
    records: list[dict[str, Any]],
    *,
    session_id: str | None = None,
    window: str | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return unique records in the requested session/window scope."""
    rows = _deduplicated(records)
    if session_id is not None:
        rows = [row for row in rows if row.get("session_id", "unknown") == session_id]
    if window is not None:
        cutoff = (now or datetime.now(timezone.utc)) - timedelta(minutes=_WINDOWS_MINUTES[window])
        rows = [
            row
            for row in rows
            if (timestamp := _record_timestamp(row)) is not None and timestamp >= cutoff
        ]
    return rows


def aggregate_scopes(
    records: list[dict[str, Any]],
    *,
    session_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return backwards-compatible aggregates plus durable scope views."""
    all_rows = _deduplicated(records)
    current_time = now or datetime.now(timezone.utc)
    windows = {
        name: aggregate(filter_records(all_rows, window=name, now=current_time))
        for name in SUPPORTED_WINDOWS
    }
    session_rows = filter_records(all_rows, session_id=session_id)
    session_aggregate = aggregate(session_rows)
    return {
        "all_time": aggregate(all_rows),
        "session": {
            "id": session_id,
            "usage": session_aggregate["totals"],
            "models": session_aggregate["models"],
            "pseudo_models": session_aggregate["pseudo_models"],
            "paths": session_aggregate["paths"],
            "pseudos": session_aggregate["pseudos"],
            "routes": session_aggregate["routes"],
            "oma": session_aggregate["oma"],
        },
        "windows": windows,
    }


def render_table(agg: dict[str, Any]) -> str:
    total = agg["totals"]
    lines = [
        "MODEL | CALLS | PROMPT TOK | COMPL TOK | TOTAL TOK | EST COST ($)",
        "-" * 76,
    ]
    for model, row in agg["models"].items():
        lines.append(
            f"{model} | {row['calls']} | {row['prompt_tokens']} | {row['completion_tokens']} | {row['total_tokens']} | {row['cost']:.4f}"
        )
    lines.append(
        f"TOTAL | {total['calls']} | {total['prompt_tokens']} | {total['completion_tokens']} | {total['total_tokens']} | {total['cost']:.4f}"
    )
    if total["cost"] == 0:
        lines.append("EST COST: n/a (no price data for these models)")
    lines.append(
        "PATHS: " + ", ".join(f"{k}={v}" for k, v in sorted(agg["paths"].items()))
    )
    lines.append(
        "PSEUDOS: " + ", ".join(f"{k}={v}" for k, v in sorted(agg["pseudos"].items()))
    )
    return "\n".join(lines)


def render_json(agg: dict[str, Any]) -> str:
    return json.dumps(agg, indent=2)


def _usage(obj: Any) -> tuple[int, int]:
    usage = getattr(obj, "usage", None)
    if isinstance(obj, dict):
        usage = obj.get("usage", usage)
    if isinstance(usage, dict):
        return int(usage.get("prompt_tokens", 0) or 0), int(
            usage.get("completion_tokens", 0) or 0
        )
    return int(getattr(usage, "prompt_tokens", 0) or 0), int(
        getattr(usage, "completion_tokens", 0) or 0
    )


def _cache_usage(obj: Any) -> tuple[int | None, int | None]:
    try:
        usage = getattr(obj, "usage", None)
        if isinstance(obj, dict):
            usage = obj.get("usage", usage)
        if usage is None:
            return None, None
        if isinstance(usage, dict):
            details = usage.get("prompt_tokens_details") or {}
            read = usage.get("cache_read_input_tokens", details.get("cached_tokens"))
            write = usage.get("cache_creation_input_tokens")
        else:
            details = getattr(usage, "prompt_tokens_details", None) or {}
            read = getattr(usage, "cache_read_input_tokens", None)
            if read is None:
                read = (
                    details.get("cached_tokens")
                    if isinstance(details, dict)
                    else getattr(details, "cached_tokens", None)
                )
            write = getattr(usage, "cache_creation_input_tokens", None)
        return (
            int(read) if read is not None else None,
            int(write) if write is not None else None,
        )
    except (TypeError, ValueError):
        return None, None


def install_recorder(llm: Any) -> None:
    original = getattr(llm, "acompletion", None)
    if original is None or getattr(original, "_skail_recorder", False):
        return

    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        t0 = time.perf_counter()
        path = kwargs.pop("_path", "unknown")
        pseudo = kwargs.pop("_pseudo", "unknown")
        complexity = kwargs.pop("_complexity", None)
        route_val = kwargs.pop("_route", None)
        tier_val = kwargs.pop("_tier", None)
        plan_val = kwargs.pop("_plan", None)
        event_id = kwargs.pop("_stats_event_id", None)
        session_id = kwargs.pop("_stats_session_id", None)
        upstream_model = kwargs.pop("_stats_upstream_model", None)
        selection = kwargs.pop("_stats_selection", None)
        model = str(kwargs.get("model", "unknown"))
        try:
            if not kwargs.get("stream"):
                result = await original(*args, **kwargs)
                lat_ms = round((time.perf_counter() - t0) * 1000, 1)
                p, c = _usage(result)
                if p == 0 and kwargs.get("messages"):
                    try:
                        from skail.server.messages_api import count_tokens
                        p = count_tokens(json.dumps(kwargs.get("messages")))
                    except Exception:
                        pass
                if c == 0 and hasattr(result, "choices") and result.choices:
                    try:
                        from skail.server.messages_api import count_tokens
                        c = count_tokens(str(result.choices[0].message.content or ""))
                    except Exception:
                        pass
                hidden = getattr(result, "_hidden_params", {}) or {}
                cache_read_tokens, cache_write_tokens = _cache_usage(result)
                record(
                    path,
                    pseudo,
                    model,
                    p,
                    c,
                    cost=hidden.get("response_cost"),
                    complexity=complexity,
                    task_value=complexity,
                    route=route_val,
                    tier=tier_val,
                    plan=plan_val,
                    latency_ms=lat_ms,
                    event_id=event_id,
                    session_id=session_id,
                    upstream_model=upstream_model,
                    selection=selection,
                    cache_read_tokens=cache_read_tokens,
                    cache_write_tokens=cache_write_tokens,
                )
                return result
            options = dict(kwargs.get("stream_options") or {})
            options.setdefault("include_usage", True)
            kwargs["stream_options"] = options
            response = await original(*args, **kwargs)
            prompt = completion = 0
            final_usage: tuple[int, int] | None = None
            cache_read_tokens = cache_write_tokens = None
            generated_tokens = 0

            async def relay():
                nonlocal prompt, completion, final_usage, generated_tokens, cache_read_tokens, cache_write_tokens
                try:
                    async for chunk in response:
                        p, c = _usage(chunk)
                        prompt = max(prompt, p)
                        completion += c
                        if _usage(chunk) != (0, 0):
                            final_usage = _usage(chunk)
                        chunk_cache_read, chunk_cache_write = _cache_usage(chunk)
                        if chunk_cache_read is not None:
                            cache_read_tokens = chunk_cache_read
                        if chunk_cache_write is not None:
                            cache_write_tokens = chunk_cache_write
                        if hasattr(chunk, "choices") and chunk.choices:
                            delta = getattr(chunk.choices[0], "delta", None)
                            if delta and getattr(delta, "content", None):
                                generated_tokens += len(str(delta.content).split())
                        yield chunk
                    lat_ms = round((time.perf_counter() - t0) * 1000, 1)
                    if not final_usage and prompt == 0:
                        try:
                            from skail.server.messages_api import count_tokens
                            p = count_tokens(json.dumps(kwargs.get("messages", [])))
                            c = max(completion, int(generated_tokens * 1.3))
                            final_usage = (p, c)
                        except Exception:
                            pass
                    record(
                        path,
                        pseudo,
                        model,
                        *(final_usage or (prompt, completion)),
                        complexity=complexity,
                        task_value=complexity,
                        route=route_val,
                        tier=tier_val,
                        plan=plan_val,
                        latency_ms=lat_ms,
                        event_id=event_id,
                        session_id=session_id,
                        upstream_model=upstream_model,
                        selection=selection,
                        cache_read_tokens=cache_read_tokens,
                        cache_write_tokens=cache_write_tokens,
                    )
                except Exception as exc:
                    lat_ms = round((time.perf_counter() - t0) * 1000, 1)
                    exc_str = str(exc)
                    if (
                        "Error building chunks" in exc_str
                        or "stream_chunk_builder" in exc_str
                        or "list index out of range" in exc_str
                    ):
                        record(
                            path,
                            pseudo,
                            model,
                            *(final_usage or (prompt, completion)),
                            complexity=complexity,
                            task_value=complexity,
                            route=route_val,
                            tier=tier_val,
                            plan=plan_val,
                            latency_ms=lat_ms,
                            event_id=event_id,
                            session_id=session_id,
                            upstream_model=upstream_model,
                            selection=selection,
                            cache_read_tokens=cache_read_tokens,
                            cache_write_tokens=cache_write_tokens,
                        )
                        return
                    pricing.record_error(model)
                    raise

            return relay()
        except Exception:
            pricing.record_error(model)
            raise

    wrapped._skail_recorder = True
    llm.acompletion = wrapped
