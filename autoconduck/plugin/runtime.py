"""Internal executor proof path — deterministic orchestration wrapper."""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from autoconduck.plugin.executor_loop import LoopState

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
    Internal proof path: ledger task_start → run salvaged executor_loop with
    read-only tools → deterministic stagnation detection (Turn-Guard thresholds)
    → escalation + bias + terminal_result → deterministic templated report.

    NO SLM call in v1.

    Returns {"task_id", "report", "rounds", "stagnation_triggered", "outcome", "model", "files_touched", "tools_used"}
    """
    try:
        from autoconduck.plugin.ledger import get_ledger
        from autoconduck.plugin.bias import get_bias_store
        from autoconduck.plugin.synthesis import render_report
        from autoconduck.config.manager import get_config
        from autoconduck.config.paths import run_dir as _run_dir  # noqa: F401
        from autoconduck.plugin.executor_loop import run_executor_tool_loop
    except Exception as exc:
        return {"status": "error", "error": str(exc), "report": f"# Error\n\n{exc}"}

    if cfg is None:
        try:
            from autoconduck.config.manager import get_config as _gc

            cfg = _gc()
        except Exception:
            cfg = None

    session_id = str(session_id or "default")
    task_id = _new_task_id()
    goal_s = _sanitize_goal(goal)
    checks = list(checks or [])
    t0 = time.monotonic()

    if workspace_root is None:
        try:
            from autoconduck.config.paths import run_dir as _rd

            workspace_root = _rd()
        except Exception:
            workspace_root = Path(".")
    workspace_root = Path(workspace_root)
    try:
        workspace_root.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    if allowed_scope is None:
        allowed_scope = []

    if model is None:
        try:
            from autoconduck.config import resolve_orchestrator_model

            model = resolve_orchestrator_model(cfg)
        except Exception as exc:
            logger.warning("resolve_orchestrator_model failed, falling back to gpt-4o: %s", exc)
            model = "gpt-4o"

    sel = getattr(cfg, "selection", None) if cfg is not None else None
    mr = int(getattr(sel, "executor_max_tool_rounds", 10) if sel is not None else 10)
    tb = float(getattr(sel, "executor_tool_time_budget_s", 180.0) if sel is not None else 180.0)
    if max_rounds is not None:
        mr = int(max_rounds)
    if time_budget_s is not None:
        tb = float(time_budget_s)

    bump_cfg = 0.15
    ttl_cfg = 10
    try:
        plugins = getattr(cfg, "plugins", None)
        if plugins is not None:
            bump_cfg = float(getattr(plugins, "escalation_floor_bump", 0.15))
            ttl_cfg = int(getattr(plugins, "escalation_ttl_turns", 10))
    except Exception:
        pass

    ledger = get_ledger()
    try:
        ledger.enqueue(session_id, task_id, "task_start", {"goal": goal_s[:500], "checks": checks[:10] if checks else []})
    except Exception as exc:
        logger.warning("runtime ledger task_start failed: %s", exc)

    rounds = 0
    tools_used: list[str] = []
    files_touched: list[str] = []
    errors: list[str] = []
    outcome = "completed"
    result_text = ""
    stagnation_triggered = False

    system_prompt = (
        "You are a deterministic executor. Complete the user's goal using the available tools. "
        "Keep tool calls precise and minimal. Do not invent file contents."
    )
    user_prompt = goal_s
    if checks:
        user_prompt += "\n\nAcceptance checks:\n" + "\n".join(f"- {c}" for c in checks[:20])

    sigs: list[str] = []
    err_streak = [0]
    max_err = [0]
    rounds_holder = [0]

    def _tool_observer(name: str, args: dict, result: Any) -> None:
        try:
            tools_used.append(str(name))
        except Exception:
            pass
        try:
            p = args.get("path") or args.get("file") or args.get("pattern")
            if isinstance(p, str) and p not in ("", "."):
                files_touched.append(str(p).split("/")[-1].split("\\")[-1])
        except Exception:
            pass
        try:
            if isinstance(result, str) and result.startswith("ERROR:"):
                errors.append(f"{name}: {result[:500]}")
                err_streak[0] += 1
                if err_streak[0] > max_err[0]:
                    max_err[0] = err_streak[0]
            else:
                err_streak[0] = 0
        except Exception:
            pass
        try:
            sig = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
            sigs.append(sig)
        except Exception:
            pass
        rounds_holder[0] += 1

    try:
        result_text = await run_executor_tool_loop(
            client,
            model,
            system_prompt,
            user_prompt,
            allowed_scope=list(allowed_scope),
            workspace_root=workspace_root,
            cfg=cfg,
            max_rounds=mr,
            time_budget_s=tb,
            tool_observer=_tool_observer,
        )
    except Exception as exc:
        result_text = f"ERROR: {exc}"
        errors.append(str(exc)[:1000])
        outcome = "error"
        try:
            ledger.enqueue(session_id, task_id, "error", {"error": str(exc)[:2000]})
        except Exception:
            pass

    if outcome == "completed" and isinstance(result_text, str) and result_text.startswith("ERROR:"):
        outcome = "error"

    try:
        if len(sigs) >= 3 and len(set(sigs[-3:])) == 1:
            stagnation_triggered = True
        if not stagnation_triggered and max_err[0] >= 2:
            stagnation_triggered = True
    except Exception as exc:
        logger.warning("stagnation detection failed: %s", exc)

    if not stagnation_triggered:
        try:
            from autoconduck.server.turn_guard import TurnGuard

            pseudo: list[dict[str, Any]] = [{"role": "user", "content": goal_s}]
            for idx, sig in enumerate(sigs):
                try:
                    name, payload = sig.split(":", 1)
                    args = json.loads(payload)
                except Exception:
                    name, args = sig.split(":", 1)[0] if ":" in sig else sig, {}
                cid = f"c{idx}"
                pseudo.append(
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
                        ],
                    }
                )
                is_err = any(e.startswith(f"{name}:") for e in errors)
                pseudo.append(
                    {
                        "role": "tool",
                        "tool_call_id": cid,
                        "name": name,
                        "content": "ERROR: simulated" if (is_err and idx >= len(sigs) - err_streak[0]) else "ok",
                    }
                )
            tg = TurnGuard().classify_turn(pseudo)
            if tg.is_stagnant:
                stagnation_triggered = True
        except Exception:
            pass

    if stagnation_triggered:
        try:
            get_bias_store().apply_escalation(session_id, bump_cfg, ttl_cfg)
            ledger.enqueue(session_id, task_id, "escalation", {"reason": "stagnation_detected", "bump": bump_cfg, "ttl": ttl_cfg})
        except Exception as exc:
            logger.warning("stagnation escalation failed: %s", exc)

    rounds = rounds_holder[0] if rounds_holder[0] else max(1, len(sigs))

    elapsed = time.monotonic() - t0
    try:
        ledger.enqueue(
            session_id,
            task_id,
            "terminal_result",
            {"outcome": outcome, "rounds": rounds, "elapsed_s": round(elapsed, 3), "stagnation": stagnation_triggered},
        )
    except Exception as exc:
        logger.warning("terminal_result ledger failed: %s", exc)

    tools_dedup = sorted(set(tools_used)) if tools_used else []
    files_dedup = sorted(set(files_touched)) if files_touched else []

    llm_enabled = False
    try:
        plugins = getattr(cfg, "plugins", None)
        if plugins is not None:
            llm_enabled = bool(getattr(plugins, "llm_synthesis_enabled", False))
    except Exception:
        pass

    try:
        from autoconduck.plugin.synthesis import render_report as _rr

        report = _rr(
            session_id=session_id,
            task_id=task_id,
            goal=goal_s[:2000],
            outcome=outcome,
            rounds=rounds,
            tools_used=tools_dedup,
            files_touched=files_dedup,
            errors=errors[:10],
            extra_notes=(result_text[:4000] if isinstance(result_text, str) else None),
            llm_synthesis_enabled=llm_enabled,
        )
    except Exception as exc:
        report = f"# Task Report — {task_id}\n\nOutcome: {outcome}\n\n{result_text[:2000]}\n\n[report error: {exc}]"

    return {
        "task_id": task_id,
        "session_id": session_id,
        "report": report,
        "rounds": rounds,
        "stagnation_triggered": stagnation_triggered,
        "outcome": outcome,
        "model": model,
        "files_touched": files_dedup,
        "tools_used": tools_dedup,
        "elapsed_s": round(elapsed, 3),
        "result_text": result_text if isinstance(result_text, str) else str(result_text)[:4000],
    }
