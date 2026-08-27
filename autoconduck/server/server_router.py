"""Routing dispatcher integration, active tool turn detection, and upstream model resolution."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import autoconduck.config as config_module

_session_replan_state: dict[str, dict[str, Any]] = {}


def _get_session_key(messages: list[Any], request: Any = None) -> str:
    """Generate a consistent session key from request headers or conversation root."""
    if request is not None and hasattr(request, "headers"):
        sess_id = request.headers.get("x-session-id") or request.headers.get("x-thread-id")
        if sess_id:
            return str(sess_id)
    if isinstance(messages, list) and messages:
        first = messages[0]
        if isinstance(first, dict):
            c = str(first.get("content", ""))[:120]
            return f"sess_{hash(c)}"
    return "default_session"


async def _run_async_slm_heartbeat(
    session_key: str,
    messages: list[Any],
    current_plan: Any,
    guard_res: Any,
    cfg: Any,
) -> None:
    """Run async background SLM heartbeat evaluation for mid-execution DAG promotion."""
    state = _session_replan_state.setdefault(session_key, {})
    if state.get("evaluating"):
        return
    state["evaluating"] = True
    try:
        from autoconduck.routing.slm_planner import SLMPlanner

        session_stats = {
            "read_count": getattr(guard_res, "read_count", 0),
            "edit_count": getattr(guard_res, "edit_count", 0),
            "replan_reason": getattr(guard_res, "replan_reason", ""),
        }
        planner = SLMPlanner()
        verdict = await planner.evaluate_session_trajectory_async(
            messages,
            current_plan=current_plan,
            session_stats=session_stats,
            config=cfg,
        )
        if verdict.should_escalate:
            state["replan_pending"] = True
            state["escalation_plan"] = verdict.suggested_plan
            logging.getLogger("autoconduck").info(
                "Mid-execution SLM heartbeat scheduled replan for session %s: %s",
                session_key,
                verdict.reason,
            )
    except Exception as exc:
        logging.getLogger("autoconduck").debug("Error in async SLM heartbeat: %s", exc)
    finally:
        state["evaluating"] = False


def is_active_tool_session(messages: list[Any]) -> bool:
    """Return True if the conversation is an active agentic tool loop.

    In an active tool loop, the client agent (Pi, Claude Code, OpenCode, etc.)
    is managing its own tool execution loop. AutoConduck relays requests
    directly to the selected model rather than hijacking the turn with the
    multi-agent LangGraph orchestrator.
    """
    try:
        from autoconduck.server.turn_guard import TurnGuard

        res = TurnGuard().classify_turn(messages)
        if res.is_stagnant:
            return False
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
) -> tuple[str | None, dict[str, Any]]:
    """Determine routing path, model selection, and orchestration execution."""
    started = time.perf_counter()
    cfg = config_module.get_config()
    messages = normalize_messages_for_llm(messages)
    target, path = body_model, "direct"
    request_depth = 0
    if request is not None and hasattr(request, "headers"):
        try:
            request_depth = int(request.headers.get("x-autoconduck-depth", "0"))
        except (ValueError, TypeError):
            request_depth = 0
        if client_type is None:
            client_type = request.headers.get("x-agent-id", None)
        if client_type is None:
            ua = request.headers.get("user-agent", "").lower()
            if "pi" in ua or "pi-coding-agent" in ua:
                client_type = "pi"
            elif "opencode" in ua:
                client_type = "opencode"
            elif "claude" in ua:
                client_type = "claude"
    is_nested = request_depth >= 1
    decision = None

    session_key = _get_session_key(messages, request)
    state = _session_replan_state.setdefault(session_key, {})

    client_replan_hint = False
    if request is not None and hasattr(request, "headers"):
        hint = str(request.headers.get("x-autoconduck-escalate", "")).lower()
        if hint in ("true", "1", "replan", "yes"):
            client_replan_hint = True

    replan_pending = bool(state.get("replan_pending") or client_replan_hint)
    escalation_plan = state.get("escalation_plan")

    if replan_pending:
        state["replan_pending"] = False
        state["escalation_plan"] = None
        state["last_replan_turn"] = len(messages)

    if body_model in PSEUDO_MODELS:
        try:
            from autoconduck.routing.dispatcher import route

            history = decisions[-5:] if decisions else []
            decision = route(
                messages,
                history,
                pseudo_model=body_model,
                config=cfg,
                replan_pending=replan_pending,
                escalation_plan=escalation_plan,
            )
            path = getattr(decision, "path", "FAST").upper()
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
        task_complexity = float(getattr(decision, "complexity", 0.5))
        if path == "SLOW" and is_nested:
            path = "FAST"
            route_name = "fast_direct"
            model = model or None
            logging.getLogger("autoconduck").info(
                "Nested orchestrator call (depth=%d) downgraded to FAST",
                request_depth,
            )
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
                node="slm" if path == "SLOW" else "direct",
                step_detail=f"Dispatched -> {model or body_model} ({route_name})",
                start_time=time.time(),
                subtasks_total=subtasks_count,
                subtasks_completed=0,
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
                }
            )
        logging.getLogger("autoconduck").info(
            "route=%s tier=%s model=%s ms=%.1f",
            route_name,
            tier,
            model or body_model,
            (time.perf_counter() - started) * 1000,
        )

        # Check if background SLM heartbeat should evaluate session trajectory
        replan_enabled = getattr(getattr(cfg, "selection", None), "mid_execution_replan_enabled", True)
        if replan_enabled and not replan_pending:
            try:
                from autoconduck.server.turn_guard import TurnGuard
                guard_res = TurnGuard().classify_turn(messages)
                min_turns = int(getattr(getattr(cfg, "selection", None), "replan_min_turns_since_slm", 12))
                turns_since = len(messages) - int(state.get("last_replan_turn", 0))

                if (guard_res.replan_suggested or client_replan_hint) and turns_since >= min_turns and not state.get("evaluating"):
                    asyncio.create_task(
                        _run_async_slm_heartbeat(session_key, messages, plan, guard_res, cfg)
                    )
            except Exception:
                pass

        in_tool_loop = is_active_tool_session(messages) and not replan_pending
        if in_tool_loop and path == "SLOW":
            logging.getLogger("autoconduck").debug(
                "Active tool loop detected — delegating completion directly to selected model %s",
                model or body_model,
            )
        plan_context = None
        if (
            path == "SLOW"
            and not in_tool_loop
            and not (request is not None and await request.is_disconnected())
        ):
            try:
                from autoconduck.orchestrator import run

                result = await run(
                    messages,
                    [],
                    pseudo_model=body_model,
                    task_value=task_complexity,
                    request=request,
                    on_progress=on_progress,
                    client_type=client_type,
                    user_agent=request.headers.get("user-agent", "") if request is not None and hasattr(request, "headers") else "",
                    is_nested=is_nested,
                    plan=plan,
                    tools=tools or [],
                )
                if result is not None:
                    tool_calls = getattr(result, "tool_calls", None) or (
                        result.get("tool_calls") if isinstance(result, dict) else None
                    )
                    content = (
                        str(result)
                        if not isinstance(result, dict)
                        else result.get("content", str(result))
                    )
                    if tool_calls:
                        ans: dict[str, Any] = {"content": content, "tool_calls": tool_calls}
                        return None, {
                            "__answer__": ans,
                            "_path": path,
                            "_pseudo": body_model,
                            "_route": route_name,
                            "_tier": tier,
                            "_plan": plan,
                            "_complexity": task_complexity,
                        }
                    else:
                        plan_context = content
            except Exception as exc:
                logging.getLogger("autoconduck").warning(
                    "Orchestrator execution failed: %s", exc
                )
        if not model:
            try:
                from autoconduck.config import resolve_orchestrator_model
                from autoconduck.routing.pricing import pool_ids, select_closest

                selected = select_closest(
                    pool_ids(cfg), 0.15, cfg, pseudo_model=body_model
                )
                model = selected or resolve_orchestrator_model(cfg)
                if not selected:
                    logging.getLogger("autoconduck").warning(
                        "Model pool is empty - no models configured; falling back to %s",
                        model,
                    )
            except Exception:
                from autoconduck.config import resolve_orchestrator_model

                model = resolve_orchestrator_model(cfg)
        if not model:
            logging.getLogger("autoconduck").warning(
                "No model available for request"
            )
        target = model
    extra = litellm_params_for(target, cfg)
    extra.update(
        _path=path if body_model in PSEUDO_MODELS else "direct",
        _pseudo=body_model,
    )
    if body_model in PSEUDO_MODELS:
        extra.update(
            _complexity=float(
                getattr(decision, "complexity", 0.5) if decision else 0.5
            ),
            _route=getattr(decision, "route", "fast_direct") if decision else "direct",
            _tier=getattr(decision, "tier", None) if decision else None,
            _plan=getattr(decision, "plan", None) if decision else None,
        )
        if plan_context:
            extra["_plan_context"] = plan_context
    return target, extra
