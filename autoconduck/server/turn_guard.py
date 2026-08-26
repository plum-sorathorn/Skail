"""Turn Guard: Synchronous 0ms tool loop classifier & stagnation escalation.

Classifies incoming request turns in <2ms:
- Routes active in-flight tool loops directly to the active model tier (DIRECT_ACTIVE_TIER).
- Escalates to the SLM Planner upon stagnation (3+ identical calls or 2+ consecutive errors) (ESCALATE_SLM).
- Routes clean user turns to the SLM Planner (SLM_PLAN).
- Supports both OpenAI (tool_calls, role=tool) and Anthropic (tool_use, tool_result) formats.
"""
from __future__ import annotations

import json
import logging
from enum import Enum
from typing import Any
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class TurnAction(str, Enum):
    DIRECT_ACTIVE_TIER = "direct_active_tier"
    SLM_PLAN = "slm_plan"
    ESCALATE_SLM = "escalate_slm"


class TurnClassificationResult(BaseModel):
    is_tool_loop: bool
    is_stagnant: bool
    stagnation_reason: str | None = None
    target_action: TurnAction
    tool_call_streak: int = 0
    error_streak: int = 0
    last_tool_name: str | None = None


def _is_tool_error_content(content: Any, is_error_flag: bool | None = None) -> bool:
    """Check if tool execution output signifies an error."""
    if is_error_flag is True:
        return True
    if is_error_flag is False:
        return False
    if content is None:
        return False
    if isinstance(content, dict):
        if content.get("is_error") is True or content.get("isError") is True:
            return True
        if content.get("is_error") is False or content.get("isError") is False:
            return False
        status = str(content.get("status", "")).lower()
        if status in ("error", "failed", "failure"):
            return True
        if status in ("ok", "success", "succeeded"):
            return False
        exit_code = content.get("exit_code") if "exit_code" in content else content.get("exitCode")
        if exit_code is not None and isinstance(exit_code, (int, float)) and exit_code != 0:
            return True
        if content.get("error"):
            return True
        return False
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_result":
                if item.get("is_error") is True:
                    return True
                if item.get("is_error") is False:
                    continue
            if _is_tool_error_content(item):
                return True
        return False
    if not isinstance(content, str):
        return False

    text = content.strip()
    if not text:
        return False

    # Check if the text is JSON-serialized dict
    if (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, (dict, list)):
                return _is_tool_error_content(parsed)
        except Exception:
            pass

    lower = text.lower()
    first_line = lower.split("\n", 1)[0].strip()

    # Direct tool/shell error prefixes on the first line or trimmed output
    error_prefixes = (
        "error:",
        "error :",
        "fatal:",
        "fatal :",
        "failed:",
        "failure:",
        "[error]",
        "[fatal]",
        "[failed]",
        "traceback (most recent call last):",
        "command not found",
        "command failed",
        "failed with exit code",
        "process exited with code",
        "failed tests",
        "failed (",
        "permission denied",
        "no such file or directory",
        "cannot find the path specified",
        "is not recognized as an internal or external command",
        "modulenotfounderror:",
        "syntaxerror:",
        "filenotfounderror:",
        "permissionerror:",
        "runtimeerror:",
        "typeerror:",
        "valueerror:",
        "nameerror:",
        "importerror:",
        "attributeerror:",
        "indexerror:",
        "keyerror:",
        "zerodivisionerror:",
        "connectionerror:",
        "timeouterror:",
    )
    if any(first_line.startswith(p) for p in error_prefixes):
        return True

    lines = [l.strip() for l in lower.splitlines() if l.strip()]

    # Unhandled Python traceback anywhere in terminal output
    if "traceback (most recent call last):" in lower:
        if any(l.startswith("traceback (most recent call last):") for l in lines):
            return True

    # Standalone error lines in test / tool runners (e.g. pytest FAILED summary lines)
    for l in lines:
        if (
            l.startswith("failed ")
            or l.startswith("failed:")
            or l.startswith("failed tests")
            or l.startswith("error: ")
            or l.startswith("fatal: ")
        ):
            return True

    return False


def _extract_root_target(args_str: str | None, content: Any = None) -> str | None:
    """Extract primary path/target identifier from tool arguments or error text."""
    path_val = None
    if args_str:
        raw_str = args_str.strip()
        if (raw_str.startswith("{") and raw_str.endswith("}")) or (raw_str.startswith("[") and raw_str.endswith("]")):
            try:
                parsed = json.loads(raw_str)
                if isinstance(parsed, dict):
                    for k in ("path", "file_path", "filepath", "file", "target", "filename", "dir", "directory", "uri"):
                        v = parsed.get(k)
                        if isinstance(v, str) and v.strip():
                            path_val = v.strip()
                            break
                    if not path_val and "command" in parsed:
                        cmd = str(parsed.get("command", "")).strip()
                        words = cmd.split()
                        for w in words:
                            if "/" in w or "\\" in w:
                                path_val = w.strip("\"'")
                                break
            except Exception:
                pass
        if not path_val:
            import re
            match = re.search(r'["\']?(?:path|file|target|dir)["\']?\s*[:=]\s*["\']([^"\']+)["\']', raw_str)
            if match:
                path_val = match.group(1)
            elif "/" in raw_str or "\\" in raw_str:
                tokens = raw_str.replace(",", " ").replace(":", " ").split()
                for t in tokens:
                    cleaned = t.strip("\"'{}[]()")
                    if "/" in cleaned or "\\" in cleaned:
                        path_val = cleaned
                        break

    if not path_val and isinstance(content, str):
        import re
        match = re.search(
            r'(?:no such file or directory|cannot find|failed to open|not found|cannot read)[:\s]+[`\'"]?([a-zA-Z0-9_.-]+(?:[/\\][a-zA-Z0-9_.-]+)*)',
            content,
            re.IGNORECASE,
        )
        if match:
            path_val = match.group(1)

    if path_val:
        normalized = path_val.replace("\\", "/").strip("/")
        parts = normalized.split("/")
        if parts and parts[0]:
            return parts[0].lower()
    return None


class TurnGuard:
    """Synchronous fast-path classifier for agentic tool loops and stagnation."""

    def classify_turn(self, messages: list[dict[str, Any]]) -> TurnClassificationResult:
        """Classify message history for tool loop bypass or SLM escalation."""
        if not messages or not isinstance(messages, list):
            return TurnClassificationResult(
                is_tool_loop=False,
                is_stagnant=False,
                target_action=TurnAction.SLM_PLAN,
                tool_call_streak=0,
                error_streak=0,
            )

        # Inspect the last message
        last_msg = messages[-1]
        if not isinstance(last_msg, dict):
            return TurnClassificationResult(
                is_tool_loop=False,
                is_stagnant=False,
                target_action=TurnAction.SLM_PLAN,
                tool_call_streak=0,
                error_streak=0,
            )

        # Check if last message is a tool response
        is_tool_resp = False
        last_tool_name: str | None = None
        last_tool_is_error = False

        role = last_msg.get("role")
        content = last_msg.get("content")

        if role in ("tool", "function"):
            is_tool_resp = True
            last_tool_name = last_msg.get("name")
            last_tool_is_error = _is_tool_error_content(content)
        elif role == "user" and isinstance(content, list):
            # Anthropic tool_result check
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    is_tool_resp = True
                    is_err = block.get("is_error")
                    last_tool_is_error = _is_tool_error_content(block.get("content"), is_error_flag=is_err)
                    break

        if not is_tool_resp:
            # Clean user prompt or system turn -> SLM Planner
            return TurnClassificationResult(
                is_tool_loop=False,
                is_stagnant=False,
                target_action=TurnAction.SLM_PLAN,
                tool_call_streak=0,
                error_streak=0,
                last_tool_name=None,
            )

        # If last_tool_name was not in the tool message, extract from previous assistant call
        all_calls: list[tuple[str, str]] = []  # list of (tool_name, args_str)
        call_id_to_args: dict[str, tuple[str, str]] = {}
        tool_results: list[bool] = []  # list of is_error booleans
        failed_targets: list[str] = []

        for idx, m in enumerate(messages):
            if not isinstance(m, dict):
                continue
            m_role = m.get("role")
            m_content = m.get("content")

            # OpenAI assistant tool calls
            tool_calls = m.get("tool_calls")
            if isinstance(tool_calls, list):
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        cid = tc.get("id")
                        fn = tc.get("function")
                        if isinstance(fn, dict):
                            fn_name = str(fn.get("name", ""))
                            fn_args = str(fn.get("arguments", ""))
                            all_calls.append((fn_name, fn_args))
                            last_tool_name = fn_name
                            if cid:
                                call_id_to_args[cid] = (fn_name, fn_args)

            # Anthropic assistant tool_use
            if m_role == "assistant" and isinstance(m_content, list):
                for b in m_content:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        cid = b.get("id")
                        fn_name = str(b.get("name", ""))
                        fn_args = json.dumps(b.get("input", {}), sort_keys=True)
                        all_calls.append((fn_name, fn_args))
                        last_tool_name = fn_name
                        if cid:
                            call_id_to_args[cid] = (fn_name, fn_args)

            # OpenAI tool response
            if m_role in ("tool", "function"):
                is_err = _is_tool_error_content(m.get("content"))
                tool_results.append(is_err)
                if not last_tool_name and m.get("name"):
                    last_tool_name = m.get("name")
                if is_err:
                    cid = m.get("tool_call_id")
                    args_str = call_id_to_args.get(cid, ("", ""))[1] if cid else (all_calls[-1][1] if all_calls else "")
                    tgt = _extract_root_target(args_str, m.get("content"))
                    if tgt:
                        failed_targets.append(tgt)

            # Anthropic user tool_result
            if m_role == "user" and isinstance(m_content, list):
                for b in m_content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        is_err = b.get("is_error")
                        err_flag = _is_tool_error_content(b.get("content"), is_error_flag=is_err)
                        tool_results.append(err_flag)
                        if err_flag:
                            cid = b.get("tool_use_id")
                            args_str = call_id_to_args.get(cid, ("", ""))[1] if cid else (all_calls[-1][1] if all_calls else "")
                            tgt = _extract_root_target(args_str, b.get("content"))
                            if tgt:
                                failed_targets.append(tgt)

        # Calculate error streak (consecutive errors at the end)
        error_streak = 0
        for is_err in reversed(tool_results):
            if is_err:
                error_streak += 1
            else:
                break

        # Calculate identical tool call streak
        tool_call_streak = 1
        if len(all_calls) >= 2:
            last_call = all_calls[-1]
            identical_count = 1
            for c in reversed(all_calls[:-1]):
                if c == last_call:
                    identical_count += 1
                else:
                    break
            tool_call_streak = identical_count

        # Check Stagnation conditions
        # 1. 3+ identical consecutive tool calls
        if tool_call_streak >= 3:
            return TurnClassificationResult(
                is_tool_loop=True,
                is_stagnant=True,
                stagnation_reason=f"3+ identical tool calls detected (loop on {last_tool_name})",
                target_action=TurnAction.ESCALATE_SLM,
                tool_call_streak=tool_call_streak,
                error_streak=error_streak,
                last_tool_name=last_tool_name,
            )

        # 2. 2+ consecutive errors
        if error_streak >= 2:
            return TurnClassificationResult(
                is_tool_loop=True,
                is_stagnant=True,
                stagnation_reason=f"2+ consecutive tool execution errors on {last_tool_name}",
                target_action=TurnAction.ESCALATE_SLM,
                tool_call_streak=tool_call_streak,
                error_streak=error_streak,
                last_tool_name=last_tool_name,
            )

        # 3. Recurring failure targeting the same invalid root entity / directory prefix
        if last_tool_is_error and failed_targets:
            target_counts: dict[str, int] = {}
            for t in failed_targets:
                target_counts[t] = target_counts.get(t, 0) + 1
            for target_name, count in target_counts.items():
                if count >= 3:
                    return TurnClassificationResult(
                        is_tool_loop=True,
                        is_stagnant=True,
                        stagnation_reason=f"3+ recurring failures targeting invalid root prefix '{target_name}'",
                        target_action=TurnAction.ESCALATE_SLM,
                        tool_call_streak=tool_call_streak,
                        error_streak=error_streak,
                        last_tool_name=last_tool_name,
                    )

        # 4. High error density in sliding window when last turn failed (>= 50% error rate in recent calls)
        if last_tool_is_error and len(tool_results) >= 4:
            recent_window = tool_results[-6:]
            if len(recent_window) >= 4:
                err_count = sum(1 for e in recent_window if e)
                if (err_count / len(recent_window)) >= 0.5:
                    return TurnClassificationResult(
                        is_tool_loop=True,
                        is_stagnant=True,
                        stagnation_reason=f"High error density in recent tool window ({err_count}/{len(recent_window)} failed)",
                        target_action=TurnAction.ESCALATE_SLM,
                        tool_call_streak=tool_call_streak,
                        error_streak=error_streak,
                        last_tool_name=last_tool_name,
                    )

        # Active healthy tool loop
        return TurnClassificationResult(
            is_tool_loop=True,
            is_stagnant=False,
            target_action=TurnAction.DIRECT_ACTIVE_TIER,
            tool_call_streak=tool_call_streak,
            error_streak=error_streak,
            last_tool_name=last_tool_name,
        )
