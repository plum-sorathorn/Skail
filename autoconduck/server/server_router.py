"""Routing dispatcher integration, active tool turn detection, and upstream model resolution."""

from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Any

import autoconduck.config as config_module


_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")


def _normalize_session_id(value: Any) -> str | None:
    """Return a bounded, transport-safe session ID or no value."""
    if not isinstance(value, str):
        return None
    session_id = value.strip()
    return session_id if _SESSION_ID_PATTERN.fullmatch(session_id) else None


def is_active_tool_session(messages: list[Any]) -> bool:
    """Return True if the conversation is an active agentic tool loop.

    In an active tool loop, the client agent (Pi, Claude Code, OpenCode, etc.)
    is managing its own tool execution loop. AutoConduck relays requests
    directly to the selected model rather than hijacking the turn.
    """
    try:
        from autoconduck.server.turn_guard import TurnGuard

        res = TurnGuard().classify_turn(messages)
        return res.is_tool_loop
    except Exception:
        pass
    if not isinstance(messages, list) or not messages:
        return False
    for m in messages:
        if not isinstance(m, dict):
            continue
        if (
            m.get("role") in ("tool", "function", "toolResult")
            or "tool_calls" in m
            or "function_call" in m
        ):
            return True
        content = m.get("content")
        if isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") in ("tool_use", "tool_result")
            for b in content
        ):
            return True
    return False


async def call_litellm(
    model: str,
    body: Any,
    path: str | None = None,
    pseudo: str | None = None,
    messages: list[Any] | None = None,
    stats_metadata: dict[str, Any] | None = None,
    routing_metadata: dict[str, Any] | None = None,
    *,
    normalize_messages_for_llm: Any = None,
    sanitize_tools: Any = None,
    litellm_params_for: Any = None,
) -> dict[str, Any]:
    """Execute a single direct LiteLLM acompletion request."""
    from autoconduck.server.server_streaming import _litellm

    llm = _litellm()
    if llm is None:
        raise RuntimeError("litellm unavailable")
    kwargs = body.model_dump(exclude_none=True)
    kwargs.pop("autoconduck_session_id", None)
    if messages is not None and normalize_messages_for_llm is not None:
        kwargs["messages"] = normalize_messages_for_llm(messages)
    if kwargs.get("tools") and sanitize_tools is not None:
        kwargs["tools"] = sanitize_tools(kwargs["tools"])
    kwargs.update(model=model, drop_params=True)
    kwargs.pop("stream", None)
    if litellm_params_for is not None:
        kwargs.update(litellm_params_for(model, config_module.get_config()))
    kwargs["_path"] = path if path is not None else "unknown"
    kwargs["_pseudo"] = pseudo if pseudo is not None else "unknown"
    if routing_metadata:
        kwargs.update(routing_metadata)
    if stats_metadata:
        kwargs.update(stats_metadata)
    result = await llm.acompletion(**kwargs)
    return result.model_dump() if hasattr(result, "model_dump") else result


async def route_target(
    body_model: str,
    messages: list[Any],
    request: Any = None,
    on_progress: Any = None,
    client_type: str | None = None,
    decisions: list[dict[str, Any]] | None = None,
    *,
    PSEUDO_MODELS: set[str],
    litellm_params_for: Any,
    normalize_messages_for_llm: Any,
    tools: list[Any] | None = None,
    payload_session_id: Any = None,
) -> tuple[str | None, dict[str, Any]]:
    """Determine routing path, model selection, and return upstream target.

    Pure turn-by-turn router: Turn Guard -> dispatcher.route() (fast-only) -> selection -> upstream dispatch.
    """
    # Phase 7C Batch 2a compat: smart-dag pseudo-variant removed; tolerate via warn-once fallback
    try:
        from autoconduck.server.messages_models import normalize_pseudo_model

        body_model = normalize_pseudo_model(body_model)
    except Exception:
        if body_model and "smart-dag" in body_model:
            body_model = "autoconduck"
    started = time.perf_counter()
    cfg = config_module.get_config()
    target, path = body_model, "direct"
    request_depth = 0
    is_oma_sidecar = False
    if request is not None and hasattr(request, "headers"):
        try:
            request_depth = int(request.headers.get("x-autoconduck-depth", "0"))
        except (ValueError, TypeError):
            request_depth = 0
        try:
            hdr_val = str(request.headers.get("x-oma-sidecar", "0")).strip().lower()
            is_oma_sidecar = hdr_val in ("1", "true")
        except Exception:
            is_oma_sidecar = False
        if client_type is None:
            client_type = request.headers.get("x-agent-id", None)
        if client_type is None:
            ua = request.headers.get("user-agent", "").lower()
            if "omp" in ua or "oh-my-pi" in ua:
                client_type = "omp"
            elif "pi" in ua or "pi-coding-agent" in ua:
                client_type = "pi"
            elif "opencode" in ua:
                client_type = "opencode"
            elif "claude" in ua:
                client_type = "claude"
    decision = None
    plan = None
    session_id = _normalize_session_id(payload_session_id)
    if session_id is None and request is not None and hasattr(request, "headers"):
        try:
            header_session_id = (
                request.headers.get("x-autoconduck-session-id")
                or request.headers.get("x-session-id")
                or request.headers.get("x-conversation-id")
            )
            session_id = _normalize_session_id(header_session_id)
        except Exception:
            session_id = None

    # Derive a stable session_id from the initial conversation message if header was absent
    if not session_id and messages:
        try:
            import hashlib
            first_user_content = ""
            for m in messages:
                if isinstance(m, dict) and m.get("role") in ("user", "human"):
                    c = m.get("content")
                    if isinstance(c, str):
                        first_user_content = c
                    elif isinstance(c, list):
                        parts = [p.get("text", "") for p in c if isinstance(p, dict)]
                        first_user_content = " ".join(parts)
                    break
            if first_user_content:
                raw_prefix = first_user_content[:200]
                agent_tag = client_type if client_type else "anon"
                key = f"{agent_tag}:{raw_prefix}".encode("utf-8")
                session_id = f"auto_{hashlib.sha256(key).hexdigest()[:16]}"
        except Exception:
            session_id = None

    if session_id:
        try:
            from autoconduck.plugin.bias import get_bias_store

            get_bias_store().increment_turn(session_id)
        except Exception:
            pass

    if body_model in PSEUDO_MODELS:
        try:
            from autoconduck.routing.dispatcher import route

            history = decisions[-5:] if decisions else []
            decision = route(
                messages,
                history,
                pseudo_model=body_model,
                config=cfg,
                session_id=session_id,
            )
            path = getattr(decision, "path", "fast").upper()
            route_name = getattr(decision, "route", "fast_direct")
            tier = getattr(decision, "tier", "balanced")
            plan = getattr(decision, "plan", None)
            model = getattr(decision, "model", None)
        except Exception:
            decision, path, route_name, tier, plan, model = (
                None,
                "FAST",
                "fast_direct",
                "balanced",
                None,
                None,
            )
        task_complexity = float(getattr(decision, "complexity", 0.5) if decision else 0.5)
        if on_progress is not None:
            try:
                on_progress(
                    {"kind": "route", "path": path, "route": route_name, "tier": tier}
                )
            except Exception:
                pass
        try:
            from autoconduck.stats import update_active_routing
            subtasks_count = len(getattr(plan, "subtasks", [])) if plan and hasattr(plan, "subtasks") and plan.subtasks else 0
            update_active_routing(
                active=True,
                path=path,
                pseudo_model=body_model,
                selected_model=model or body_model,
                task_value=task_complexity,
                node="direct",
                step_detail=f"Dispatched -> {model or body_model} ({route_name})",
                start_time=time.time(),
                subtasks_total=subtasks_count,
                subtasks_completed=0,
                plan_id=getattr(plan, "plan_id", ""),
            )
        except Exception:
            pass
        if decisions is not None:
            decisions.append(
                {
                    "path": path,
                    "route": route_name,
                    "tier": tier,
                    "model": model or body_model,
                    "time": time.time(),
                    "candidates_considered": getattr(decision, "candidates_considered", 0),
                    "candidates_excluded_by": getattr(decision, "candidates_excluded_by", None),
                    "binding_constraint": getattr(decision, "binding_constraint", None),
                    "min_capability_score_applied": getattr(decision, "min_capability_score_applied", 0.0),
                    "spend_cap_engaged": getattr(decision, "spend_cap_engaged", False),
                    "fallback_reason": getattr(decision, "fallback_reason", None),
                    "benchmark_profile": getattr(decision, "benchmark_profile", None),
                    "benchmark_score": getattr(decision, "benchmark_score", None),
                    "benchmark_coverage_state": getattr(decision, "benchmark_coverage_state", None),
                    "benchmark_snapshot_age_hours": getattr(decision, "benchmark_snapshot_age_hours", None),
                }
            )
        logging.getLogger("autoconduck").info(
            "route=%s tier=%s model=%s ms=%.1f",
            route_name,
            tier,
            model or body_model,
            (time.perf_counter() - started) * 1000,
        )

        if not model:
            from autoconduck.config import resolve_orchestrator_model

            model = resolve_orchestrator_model(cfg)
            if not model:
                logging.getLogger("autoconduck").warning(
                    "Model pool is empty - no models configured; falling back to %s",
                    model,
                )
        if not model:
            logging.getLogger("autoconduck").warning(
                "No model available for request"
            )
        target = model
    selection = {
        "route": getattr(decision, "route", "direct") if decision else "direct",
        "tier": getattr(decision, "tier", None) if decision else None,
        "complexity": getattr(decision, "complexity", None) if decision else None,
        "task_type": getattr(plan, "task_type", None) if plan else None,
        "confidence": getattr(plan, "confidence", None) if plan else None,
        "candidates_considered": getattr(decision, "candidates_considered", None) if decision else None,
        "candidates_excluded_by": getattr(decision, "candidates_excluded_by", None) if decision else None,
        "binding_constraint": getattr(decision, "binding_constraint", None) if decision else None,
        "capability_fit_applied": getattr(decision, "capability_fit_applied", None) if decision else None,
        "binding_capability_dim": getattr(decision, "binding_capability_dim", None) if decision else None,
        "min_capability_score_applied": getattr(decision, "min_capability_score_applied", None) if decision else None,
        "spend_cap_engaged": getattr(decision, "spend_cap_engaged", None) if decision else None,
        "fallback_reason": getattr(decision, "fallback_reason", None) if decision else None,
        "benchmark_profile": getattr(decision, "benchmark_profile", None) if decision else None,
        "benchmark_score": getattr(decision, "benchmark_score", None) if decision else None,
        "benchmark_coverage_state": getattr(decision, "benchmark_coverage_state", None) if decision else None,
        "benchmark_snapshot_age_hours": getattr(decision, "benchmark_snapshot_age_hours", None) if decision else None,
    }
    stats_metadata = {
        "_stats_event_id": uuid.uuid4().hex,
        "_stats_session_id": session_id or "unknown",
        # The canonical ID is the final, provider-qualified LiteLLM target.
        "_stats_upstream_model": str(target or body_model),
        "_stats_selection": {key: value for key, value in selection.items() if value is not None},
    }
    extra = litellm_params_for(target, cfg)
    extra.update(
        _path=path if body_model in PSEUDO_MODELS else "direct",
        _pseudo=body_model,
    )
    extra.update(stats_metadata)
    if body_model in PSEUDO_MODELS:
        extra.update(
            _complexity=float(
                getattr(decision, "complexity", 0.5) if decision else 0.5
            ),
            _route=getattr(decision, "route", "fast_direct") if decision else "direct",
            _tier=getattr(decision, "tier", None) if decision else None,
            _plan=getattr(decision, "plan", None) if decision else None,
        )

    # OMA Complexity Gating Intercept. Outcomes stay in completion metadata so
    # the recorder can journal normal/fail-soft requests off the routing path.
    plugins_cfg = getattr(cfg, "plugins", None)
    plugins_enabled = bool(getattr(plugins_cfg, "enabled", False)) if plugins_cfg else False
    oma_enabled = bool(getattr(plugins_cfg, "oma_enabled", True)) if plugins_cfg else False
    oma_outcomes = ["not_eligible"]
    oma_reason = "direct_model"
    oma_result = None

    if request_depth >= 1:
        oma_reason = "request_depth"
    elif is_oma_sidecar:
        oma_reason = "oma_sidecar_header"
    elif body_model not in PSEUDO_MODELS:
        oma_reason = "direct_model"
    elif not plugins_enabled:
        oma_reason = "plugins_disabled"
    elif not oma_enabled:
        oma_reason = "oma_disabled"
    else:
        plan = getattr(decision, "plan", None) if decision else None
        task_type = str(getattr(plan, "task_type", "")).lower() if plan else ""
        c_score = getattr(plan, "complexity_score", None) if plan else None
        try:
            comp_val = (
                float(c_score) / 10.0
                if c_score is not None
                else float(getattr(decision, "complexity", 0.0))
            )
            decision_complexity = float(getattr(decision, "complexity", 0.0))
        except (TypeError, ValueError):
            comp_val = decision_complexity = 0.0

        is_high_complexity = (
            comp_val >= 0.75
            or decision_complexity >= 0.75
            or task_type in ("full_workflow", "refactor")
        )

        if not is_high_complexity:
            oma_reason = "complexity_below_threshold"
        else:
            user_prompt = ""
            if messages:
                for m in reversed(messages):
                    if isinstance(m, dict) and m.get("role") in ("user", "human"):
                        c = m.get("content")
                        if isinstance(c, str):
                            user_prompt = c
                        elif isinstance(c, list):
                            parts = [
                                p.get("text", "")
                                for p in c
                                if (isinstance(p, dict) and p.get("type") == "text") or isinstance(p, str)
                            ]
                            user_prompt = " ".join(parts)
                        break
            if not user_prompt and messages:
                first_m = messages[-1]
                user_prompt = str(first_m.get("content", "")) if isinstance(first_m, dict) else str(first_m)

            try:
                from autoconduck.plugin import runtime

                res = await runtime.start_task(
                    session_id=session_id or "default",
                    goal=user_prompt,
                    cfg=cfg,
                )
                runner_started = bool(res.get("runner_started")) if isinstance(res, dict) else False
                if runner_started:
                    oma_outcomes = ["started"]
                if runner_started and isinstance(res, dict) and res.get("status") == "ok":
                    oma_outcomes.append("completed")
                    oma_reason = "completed"
                    oma_result = res
                elif isinstance(res, dict) and res.get("status") == "disabled":
                    oma_outcomes = ["not_eligible"]
                    oma_reason = "execution_disabled"
                else:
                    if not runner_started:
                        oma_outcomes = []
                    oma_outcomes.append("failed_soft")
                    oma_reason = "runner_error"
                    logging.getLogger("autoconduck").warning(
                        "OMA sidecar runner returned error (fail-soft degrade): %s",
                        res.get("report") if isinstance(res, dict) else None,
                    )
            except Exception as exc:
                oma_outcomes = ["failed_soft"]
                oma_reason = "runner_exception"
                logging.getLogger("autoconduck").warning(
                    "OMA execution failed (fail-soft degrade): %s", exc
                )

    stats_metadata["_stats_selection"]["oma"] = {
        "outcomes": oma_outcomes,
        "reason": oma_reason,
    }
    if oma_result is not None:
        extra["_oma_result"] = oma_result
        extra["_oma_outcomes"] = oma_outcomes

    return target, extra
