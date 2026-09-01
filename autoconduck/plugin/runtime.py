"""Plugin runtime — deterministic orchestration entrypoint."""

from __future__ import annotations

import asyncio
import json
import logging
import time
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
    Launches the OMA Node.js sidecar runner dynamically and logs events to PluginLedger.
    """
    if cfg is None:
        try:
            from autoconduck.config.manager import get_config as _gc

            cfg = _gc()
        except Exception:
            cfg = None

    plugins_cfg = getattr(cfg, "plugins", None) if cfg else None

    if not plugins_cfg or not getattr(plugins_cfg, "enabled", False):
        return {"status": "disabled", "error": "plugins.enabled must be true to use plugin runtime."}

    if not getattr(plugins_cfg, "execute_enabled", False):
        return {"status": "disabled", "error": "execute_enabled must be true to use internal executor."}

    if not getattr(plugins_cfg, "oma_enabled", True):
        return {"status": "disabled", "error": "oma_enabled must be true to launch OMA sidecar."}

    start_time = time.time()
    task_id = _new_task_id()
    sess_id = str(session_id or "default")

    if workspace_root:
        ws_root = str(Path(workspace_root).resolve())
    else:
        ws_root = str(Path.cwd().resolve())

    base_url = None
    if cfg is not None:
        host = getattr(cfg, "host", "127.0.0.1")
        port = getattr(cfg, "port", 11434)
        base_url = f"http://{host}:{port}/v1"
    if not base_url:
        base_url = "http://127.0.0.1:11434/v1"

    oma_mode = getattr(plugins_cfg, "oma_mode", "auto") if plugins_cfg else "auto"
    node_path = (getattr(plugins_cfg, "oma_node_path", None) if plugins_cfg else None) or "node"
    model_name = model or (getattr(cfg, "pseudo_model", "autoconduck") if cfg else "autoconduck")

    # 1. Enqueue task_start event to PluginLedger
    ledger: Any = None
    try:
        from autoconduck.plugin.ledger import get_ledger

        ledger = get_ledger()
        ledger.enqueue(
            session_id=sess_id,
            task_id=task_id,
            kind="task_start",
            data={
                "goal": _sanitize_goal(goal),
                "mode": oma_mode,
                "workspace_root": ws_root,
            },
        )
    except Exception as exc:
        logger.warning("Failed to enqueue task_start in ledger: %s", exc)
        ledger = None

    payload = {
        "goal": goal,
        "session_id": sess_id,
        "task_id": task_id,
        "mode": oma_mode,
        "workspace_root": ws_root,
        "base_url": base_url,
        "model": model_name,
    }

    res: dict[str, Any]
    try:
        runner_script = Path(__file__).parent / "oma_sidecar" / "runner.js"
        if not runner_script.exists():
            raise FileNotFoundError(f"OMA sidecar script not found at {runner_script}")

        payload_bytes = json.dumps(payload).encode("utf-8")

        proc = await asyncio.create_subprocess_exec(
            node_path,
            str(runner_script),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate(input=payload_bytes)

        if proc.returncode != 0 and not stdout_bytes:
            err_msg = stderr_bytes.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Node process exited with code {proc.returncode}: {err_msg}")

        stdout_str = stdout_bytes.decode("utf-8", errors="replace").strip()
        if not stdout_str:
            err_msg = stderr_bytes.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Empty output from OMA sidecar. Stderr: {err_msg}")

        data = json.loads(stdout_str)
        elapsed = round(time.time() - start_time, 3)

        res = {
            "task_id": data.get("task_id", task_id),
            "session_id": sess_id,
            "status": data.get("status", "ok"),
            "report": data.get("report", ""),
            "mode": data.get("mode", oma_mode),
            "tasks": data.get("tasks", []),
            "elapsed_s": elapsed,
        }
        if "totalTokenUsage" in data:
            res["totalTokenUsage"] = data["totalTokenUsage"]

    except Exception as exc:
        logger.warning("OMA sidecar execution failed (fail-soft): %s", exc)
        elapsed = round(time.time() - start_time, 3)
        res = {
            "task_id": task_id,
            "session_id": sess_id,
            "status": "error",
            "report": f"OMA sidecar launch failed: {str(exc)}",
            "mode": oma_mode,
            "tasks": [],
            "elapsed_s": elapsed,
        }

    # 2. Enqueue terminal_result event to PluginLedger
    try:
        if ledger is None:
            from autoconduck.plugin.ledger import get_ledger

            ledger = get_ledger()
        ledger.enqueue(
            session_id=sess_id,
            task_id=task_id,
            kind="terminal_result",
            data={
                "status": res.get("status"),
                "report": res.get("report"),
                "mode": res.get("mode"),
                "elapsed_s": res.get("elapsed_s"),
            },
        )
    except Exception as exc:
        logger.warning("Failed to enqueue terminal_result in ledger: %s", exc)

    return res
