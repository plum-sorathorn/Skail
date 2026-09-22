"""Hook CLI handler — observe-only, fails inert.

Invoked as `skail hook claude <EventName>` from Claude Code hooks.
Design contract:
- No config load, no network, no daemon call — single file append only.
- ALWAYS exit 0, even on any internal error (PreToolUse nonzero would block tool execution).
- Reads stdin JSON if present and parseable; tolerates EOF / malformed / absent.
- Appends ONE json line {ts, harness, event, tool_name?, session_id?} to plugin_spool.jsonl with O_APPEND.

Honest scope note: interpreter startup (~30-80ms on typical machines) is outside
the <10ms handler budget. The handler itself (file open + single write) is
<10ms on warm FS; the per-invocation OS spawn cost is unavoidable for a
Python CLI hook but is bounded to one syscall-append and never blocks on
planning, ledger writes, or LLM calls.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path


def _spool_path() -> Path:
    try:
        from skail.config.paths import run_dir

        return run_dir() / "plugin_spool.jsonl"
    except Exception:
        # fallback: ~/.skail/run/plugin_spool.jsonl
        return Path.home() / ".skail" / "run" / "plugin_spool.jsonl"


def _utc_now_iso() -> str:
    try:
        return datetime.datetime.now(datetime.timezone.utc).isoformat()
    except Exception:
        return datetime.datetime.utcnow().isoformat() + "Z"


def cmd_hook(args) -> int:  # type: ignore[no-untyped-def]
    """Handle `skail hook <harness> <event>`.

    Always returns 0. Never raises.
    """
    try:
        # tolerate unknown/missing args — still exit 0
        harness = str(getattr(args, "harness", None) or getattr(args, "agent", None) or "claude")
        # normalize harness (claude alias)
        if harness in ("claude_code", "claude-code"):
            harness = "claude"
        event = str(getattr(args, "event", None) or getattr(args, "hook_event", None) or "unknown")
        # positional fallback: if harness was actually event due to missing arg
        # args layout is hook <harness> <event>; if only one positional, treat as event
        if harness and not event:
            event = harness
            harness = "claude"
        if not harness:
            harness = "claude"
        if not event or event == "None":
            event = "unknown"

        tool_name = None
        session_id = None

        # Read stdin JSON if present and parseable (Claude Code passes hook JSON on stdin)
        try:
            # don't block indefinitely — read whatever is available
            # stdin may be tty with no data (EOF immediately)
            data = None
            try:
                # Claude Code closes stdin after writing hook JSON, so this
                # blocking read is bounded in practice (EOF arrives promptly
                # when the harness has no payload; no indefinite hang).
                raw = sys.stdin.read()
            except Exception:
                raw = ""
            if raw:
                raw = raw.strip()
                if raw:
                    try:
                        parsed = json.loads(raw)
                    except Exception:
                        # try to find first JSON object in stream (some harnesses prefix)
                        parsed = None
                        # malformed → tolerate
                    if isinstance(parsed, dict):
                        # Claude Code tool fields: tool_name, tool_input, session_id
                        # Be tolerant of varied shapes
                        for key in ("tool_name", "tool", "toolName"):
                            v = parsed.get(key)
                            if isinstance(v, str) and v:
                                tool_name = v
                                break
                        for key in ("session_id", "sessionId", "sessionID"):
                            v = parsed.get(key)
                            if isinstance(v, str) and v:
                                session_id = v
                                break
                        # also check nested tool_input / tool_use
                        if tool_name is None:
                            inp = parsed.get("tool_input") or parsed.get("toolInput") or parsed.get("tool_use")
                            if isinstance(inp, dict):
                                for k in ("name", "tool_name"):
                                    vv = inp.get(k)
                                    if isinstance(vv, str) and vv:
                                        tool_name = vv
                                        break
        except Exception:
            # stdin parse must never affect exit code
            pass

        # Build record
        record: dict[str, object] = {
            "ts": _utc_now_iso(),
            "harness": harness,
            "event": event,
        }
        if tool_name:
            record["tool_name"] = tool_name
        if session_id:
            record["session_id"] = session_id

        # Single append — O_APPEND, one write
        try:
            spool = _spool_path()
            spool.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(record, separators=(",", ":"), default=str)
            # Use os.open with O_APPEND for atomic append where possible, fallback to normal open
            try:
                fd = os.open(str(spool), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
                try:
                    os.write(fd, (line + "\n").encode("utf-8"))
                finally:
                    try:
                        os.close(fd)
                    except Exception:
                        pass
            except Exception:
                # fallback: Python open with append
                with spool.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception:
            # spool write failure is silent no-op per spec
            pass

        return 0
    except Exception:
        # Top-level fails inert: always exit 0 and never surface error
        return 0


def register_hook_parser(subparsers) -> None:  # type: ignore[no-untyped-def]
    """Register `skail hook` subcommand on given subparsers. Never raises."""
    try:
        hook_parser = subparsers.add_parser("hook", help="Harness hook spool (observe-only, fails inert)")
        hook_parser.add_argument("harness", nargs="?", default="claude", help="Harness id (e.g. claude)")
        hook_parser.add_argument("event", nargs="?", default="unknown", help="Hook event name (e.g. PostToolUse)")
        hook_parser.set_defaults(handler=cmd_hook)
    except Exception:
        pass
