"""Daemon-side plugin control plane (fail-soft, off the hot path)."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

ALLOWED_EVENT_KINDS = frozenset({"tool_call", "tool_result", "task_start", "task_progress", "task_done"})
DURABLE_VIA_EVENTS = frozenset({"task_start"})
ALLOWED_ESCALATE_REASONS = frozenset({"consecutive_errors", "repeated_calls", "requested_review", "acceptance_failed"})


def _plugins_enabled() -> bool:
    try:
        from autoconduck.config.manager import get_config

        cfg = get_config()
        plugins = getattr(cfg, "plugins", None)
        return bool(getattr(plugins, "enabled", False)) if plugins is not None else False
    except Exception:
        return False


def _get_plugins_cfg() -> Any:
    try:
        from autoconduck.config.manager import get_config

        return getattr(get_config(), "plugins", None)
    except Exception:
        return None


async def _events_handler(request: Request):  # type: ignore[no-untyped-def]
    try:
        if not _plugins_enabled():
            return JSONResponse(content={"status": "ignored"})
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(content={"status": "ignored", "reason": "invalid_json"})
        if not isinstance(body, dict):
            return JSONResponse(content={"status": "ignored", "reason": "invalid_json"})
        session_id = str(body.get("session_id") or "")
        task_id = str(body.get("task_id") or body.get("taskId") or uuid.uuid4().hex[:8])
        kind = str(body.get("kind") or "")
        data = body.get("data")
        if kind not in ALLOWED_EVENT_KINDS:
            return JSONResponse(content={"status": "ignored", "reason": "unknown_kind"})
        try:
            from autoconduck.plugin.ledger import get_ledger

            ledger = get_ledger()
            if kind in DURABLE_VIA_EVENTS:
                ledger.enqueue(session_id, task_id, kind, data if isinstance(data, dict) else {"data": data})
            else:
                ledger.count_in_memory(session_id, kind)
        except Exception as exc:
            logger.warning("plugin /events ledger error: %s", exc)
        return JSONResponse(content={"status": "ok"})
    except Exception as exc:
        logger.warning("plugin /events handler error: %s", exc)
        return JSONResponse(content={"status": "ignored"})


async def _contract_handler(request: Request):  # type: ignore[no-untyped-def]
    try:
        session_id = str(request.query_params.get("session") or request.query_params.get("session_id") or "")
        try:
            from autoconduck.plugin.ledger import get_ledger

            ledger = get_ledger()
            events = ledger.query_events(session_id=session_id or None, limit=20) if session_id else []
            counts = ledger.get_counts(session_id or None) if session_id else {}
        except Exception:
            events, counts = [], {}
        return JSONResponse(content={
            "schema_version": "0.5",
            "session_id": session_id,
            "execution_authority": "plugin-deterministic",
            "brain": "deterministic-first (SLM optional, LLM via router)",
            "acceptance_checks": [],
            "notes": f"events={len(events)} counts={counts}" if session_id else "no session",
        })
    except Exception as exc:
        logger.warning("plugin /contract handler error: %s", exc)
        return JSONResponse(content={
            "schema_version": "0.5",
            "session_id": "",
            "execution_authority": "plugin-deterministic",
            "brain": "deterministic-first (SLM optional, LLM via router)",
            "acceptance_checks": [],
            "notes": f"error: {exc}",
        })


async def _escalate_handler(request: Request):  # type: ignore[no-untyped-def]
    try:
        if not _plugins_enabled():
            return JSONResponse(content={"status": "ignored"})
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(content={"status": "rejected", "reason": "invalid_json"})
        if not isinstance(body, dict):
            return JSONResponse(content={"status": "rejected", "reason": "invalid_json"})
        session_id = str(body.get("session_id") or "")
        reason = str(body.get("reason") or "")
        if reason not in ALLOWED_ESCALATE_REASONS:
            return JSONResponse(content={"status": "rejected", "reason": "unknown_trigger"})
        if not session_id:
            return JSONResponse(content={"status": "rejected", "reason": "missing_session_id"})
        plugins_cfg = _get_plugins_cfg()
        bump = 0.15
        ttl = 10
        try:
            if plugins_cfg is not None:
                bump = float(getattr(plugins_cfg, "escalation_floor_bump", 0.15))
                ttl = int(getattr(plugins_cfg, "escalation_ttl_turns", 10))
        except Exception:
            pass
        try:
            from autoconduck.plugin.bias import get_bias_store

            applied = get_bias_store().apply_escalation(session_id, bump, ttl)
        except Exception as exc:
            logger.warning("bias apply failed: %s", exc)
            applied = bump
        try:
            from autoconduck.plugin.ledger import get_ledger

            ledger = get_ledger()
            ledger.enqueue(session_id, uuid.uuid4().hex[:8], "escalation", {"reason": reason, "bump": applied, "ttl": ttl})
        except Exception as exc:
            logger.warning("escalate ledger enqueue failed: %s", exc)
        return JSONResponse(content={"status": "ok", "floor_bump": applied, "ttl_turns": ttl, "session_id": session_id})
    except Exception as exc:
        logger.warning("plugin /escalate handler error: %s", exc)
        return JSONResponse(content={"status": "ignored"})


async def _execute_handler(request: Request):  # type: ignore[no-untyped-def]
    try:
        if not _plugins_enabled():
            return JSONResponse(content={"status": "disabled"})
        plugins_cfg = _get_plugins_cfg()
        allow = False
        try:
            if plugins_cfg is not None:
                allow = bool(getattr(plugins_cfg, "execute_enabled", False))
        except Exception:
            allow = False
        if not allow:
            return JSONResponse(content={"status": "disabled"})
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(content={"status": "rejected", "reason": "invalid_json"})
        if not isinstance(body, dict):
            return JSONResponse(content={"status": "rejected", "reason": "invalid_json"})
        session_id = str(body.get("session_id") or "default")
        goal = str(body.get("goal") or "")
        checks = body.get("checks") or []
        if not goal:
            return JSONResponse(content={"status": "rejected", "reason": "missing_goal"})
        try:
            from autoconduck.plugin.runtime import start_task
            from pathlib import Path

            ws = body.get("workspace_root")
            scope = body.get("allowed_scope")
            res = await start_task(
                session_id=session_id,
                goal=goal,
                checks=list(checks) if isinstance(checks, list) else [],
                workspace_root=Path(ws) if ws else None,
                allowed_scope=list(scope) if isinstance(scope, list) else None,
            )
            return JSONResponse(content={"status": "ok", "result": res})
        except Exception as exc:
            logger.warning("plugin /execute failed: %s", exc)
            return JSONResponse(content={"status": "error", "error": str(exc)[:2000]})
    except Exception as exc:
        logger.warning("plugin /execute handler error: %s", exc)
        return JSONResponse(content={"status": "ignored"})


def install_plugin_routes(app: Any, BaseModel: Any = None, Field: Any = None) -> Any:
    """Mount plugin control endpoints onto the FastAPI app. Never raises."""
    try:
        app.add_api_route("/plugin/events", _events_handler, methods=["POST"])
    except Exception as exc:
        logger.warning("mount /plugin/events failed: %s", exc)
    try:
        app.add_api_route("/plugin/contract", _contract_handler, methods=["GET"])
    except Exception as exc:
        logger.warning("mount /plugin/contract failed: %s", exc)
    try:
        app.add_api_route("/plugin/escalate", _escalate_handler, methods=["POST"])
    except Exception as exc:
        logger.warning("mount /plugin/escalate failed: %s", exc)
    try:
        app.add_api_route("/plugin/execute", _execute_handler, methods=["POST"])
    except Exception as exc:
        logger.warning("mount /plugin/execute failed: %s", exc)
    return app
