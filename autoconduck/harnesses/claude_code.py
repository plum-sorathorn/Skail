from __future__ import annotations

import copy
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ..config import Config, backups_dir
from ..launcher import _claude_env
from .base import BaseAdapter


class ClaudeCodeAdapter(BaseAdapter):
    binary_name = "claude"
    id = "claude_code"
    display_name = "Claude Code"


    def detect(self) -> bool:
        if shutil.which("claude") is not None:
            return True
        return any(p.exists() for p in self.config_paths())

    def config_paths(self) -> list[Path]:
        home = Path.home()
        return [
            home / ".config" / "claude" / "settings.json",
            home / ".claude.json",
            home / ".claude" / "settings.json",
        ]

    # Hooks managed by the plugin shim (Phase B). HTTP hooks per event, observe-only.
    HOOK_EVENTS = ("PreToolUse", "PostToolUse", "Stop", "SubagentStart", "SubagentStop")
    HOOK_COMMAND_TMPL = "autoconduck hook claude {event}"

    def _hooks_enabled(self, config: Config) -> bool:
        try:
            plugins = getattr(config, "plugins", None)
            if plugins is None:
                return False
            return bool(getattr(plugins, "enabled", False) and getattr(plugins, "claude_enabled", False))
        except Exception:
            return False

    def _rag_enabled(self, config: Config) -> bool:
        try:
            plugins = getattr(config, "plugins", None)
            if plugins is None:
                return False
            return bool(
                getattr(plugins, "enabled", False)
                and getattr(plugins, "claude_enabled", False)
                and getattr(plugins, "rag_enabled", False)
            )
        except Exception:
            return False

    def _build_hooks_block(self, port: int = 11434) -> dict:
        hooks: dict[str, list[dict]] = {}
        for ev in self.HOOK_EVENTS:
            label = "AutoConduck Subagent Tracker" if "Subagent" in ev else "AutoConduck Monitor"
            hooks[ev] = [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "http",
                            "url": f"http://127.0.0.1:{port}/plugin/events",
                            "timeoutMs": 10,
                            "_name": label,
                        }
                    ],
                }
            ]
        return hooks

    def _build_mcp_block(self, port: int = 11434) -> dict:
        return {"autoconduck": {"url": f"http://127.0.0.1:{port}/mcp", "type": "http"}}

    def _is_autoconduck_hook_entry(self, entry: dict) -> bool:
        try:
            inner = entry.get("hooks") if isinstance(entry, dict) else None
            if not isinstance(inner, list):
                return False
            for h in inner:
                if isinstance(h, dict):
                    cmd = str(h.get("command", ""))
                    url = str(h.get("url", ""))
                    name = str(h.get("_name", ""))
                    if "autoconduck hook claude" in cmd or "/plugin/events" in url or name.startswith("AutoConduck"):
                        return True
            return False
        except Exception:
            return False

    def _merge_hooks(self, existing: dict | None, port: int = 11434) -> dict:
        """Merge autoconduck hook entries into existing hooks dict, idempotent."""
        base: dict[str, list] = {}
        if isinstance(existing, dict):
            # copy user hooks, but strip old autoconduck entries to avoid duplicates
            for k, v in existing.items():
                if not isinstance(v, list):
                    base[k] = v  # type: ignore[assignment]
                    continue
                kept = [e for e in v if not self._is_autoconduck_hook_entry(e)]
                if kept:
                    base[k] = kept
        managed = self._build_hooks_block(port=port)
        for ev, entries in managed.items():
            lst = base.get(ev)
            if not isinstance(lst, list):
                lst = []
                base[ev] = lst
            # append managed entries if not already present
            for me in entries:
                if me not in lst:
                    lst.append(me)
        return base

    def _strip_autoconduck_hooks(self, existing: dict | None) -> dict | None:
        if not isinstance(existing, dict):
            return existing
        out: dict[str, list] = {}
        for k, v in existing.items():
            if not isinstance(v, list):
                out[k] = v  # type: ignore[assignment]
                continue
            kept = [e for e in v if not self._is_autoconduck_hook_entry(e)]
            if kept:
                out[k] = kept
        return out if out else None

    def patch(self, config: Config, port: int | None = None) -> None:
        effective_port = int(
            port if port is not None else getattr(config, "port", 11434)
        )
        path = Path.home() / ".claude" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        first_takeover = not isinstance(data.get("autoconduck"), dict)
        if path.exists() and first_takeover:
            backup = backups_dir("claude_code")
            backup.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
            (backup / f"{stamp}.bak").write_text(
                path.read_text(encoding="utf-8"), encoding="utf-8"
            )
        env = data.get("env") if isinstance(data.get("env"), dict) else {}
        values = _claude_env(
            effective_port, getattr(config, "pseudo_model", "autoconduck")
        )
        marker = (
            data.get("autoconduck") if isinstance(data.get("autoconduck"), dict) else {}
        )
        previous = marker.get("previous_env", {})
        if not isinstance(previous, dict):
            previous = {}
        # Only snapshot pre-existing user env values on first-time takeover;
        # on later idempotent patches, previous_env must stay untouched so
        # revert() restores true original values instead of managed ones.
        if first_takeover:
            for key in values:
                if key not in previous and key in env:
                    previous[key] = env[key]
        for key, value in values.items():
            env[key] = value
        data["env"] = env
        model_overrides = (
            data.get("modelOverrides")
            if isinstance(data.get("modelOverrides"), dict)
            else {}
        )
        # modelOverrides in Claude Code maps model picker entries to provider model IDs (strings).
        # Filter out any legacy non-string objects so Claude Code does not fail schema validation.
        cleaned_overrides = {
            k: v for k, v in model_overrides.items() if isinstance(v, str)
        }
        for pseudo_name in (
            "autoconduck",
            "autoconduck-budget",
            "autoconduck-expensive",
        ):
            cleaned_overrides[pseudo_name] = pseudo_name
        data["modelOverrides"] = cleaned_overrides
        claude_settings = getattr(config, "claude_code", None)
        allowed_tools = list(getattr(claude_settings, "allowed_tools", []))
        permissions = data.get("permissions")
        previous_permissions = (
            copy.deepcopy(marker["previous_permissions"])
            if "previous_permissions" in marker
            else copy.deepcopy(permissions)
        )
        if not isinstance(permissions, dict):
            permissions = {}
        existing_allow = permissions.get("allow")
        if not isinstance(existing_allow, list):
            existing_allow = []
        permissions["allow"] = list(dict.fromkeys(existing_allow + allowed_tools))
        default_mode = getattr(claude_settings, "default_mode", None)
        if default_mode is not None and "defaultMode" not in permissions:
            permissions["defaultMode"] = default_mode
        if getattr(claude_settings, "enable_all_project_mcp_servers", False):
            permissions["enableAllProjectMcpServers"] = True
        data["permissions"] = permissions
        contributed = marker.get("contributed_permissions", allowed_tools)
        if not isinstance(contributed, list):
            contributed = allowed_tools
        # Previous hooks snapshot (only on first takeover)
        previous_hooks = marker.get("previous_hooks")
        if first_takeover and "previous_hooks" not in marker:
            # snapshot whatever was there before we touch it
            raw_hooks = data.get("hooks")
            if isinstance(raw_hooks, dict):
                previous_hooks = copy.deepcopy(raw_hooks)
            elif raw_hooks is not None:
                previous_hooks = copy.deepcopy(raw_hooks)
            else:
                previous_hooks = None
        # Decide hooks block based on plugin flags
        hooks_enabled = self._hooks_enabled(config)
        existing_hooks = data.get("hooks")
        if hooks_enabled:
            merged = self._merge_hooks(
                existing_hooks if isinstance(existing_hooks, dict) else None,
                port=effective_port,
            )
            data["hooks"] = merged
            contributed_hooks = list(self.HOOK_EVENTS)
        else:
            # flags off → ensure no autoconduck hooks remain (byte-identical to pre-plugin when never enabled)
            stripped = self._strip_autoconduck_hooks(existing_hooks if isinstance(existing_hooks, dict) else None)
            if stripped is None:
                data.pop("hooks", None)
            else:
                # if stripping left only empty dict, remove key to stay byte-identical to no-hooks state
                if not stripped:
                    data.pop("hooks", None)
                else:
                    data["hooks"] = stripped
            # keep marker but mark as not contributed
            contributed_hooks = marker.get("contributed_hooks_events", [])
            if not isinstance(contributed_hooks, list):
                contributed_hooks = []

        # RAG / MCP server registration (gated by plugins.enabled AND claude_enabled AND rag_enabled)
        rag_enabled = self._rag_enabled(config)
        existing_mcp = data.get("mcpServers")
        if rag_enabled:
            if not isinstance(existing_mcp, dict):
                existing_mcp = {}
            existing_mcp["autoconduck"] = {
                "url": f"http://127.0.0.1:{effective_port}/mcp",
                "type": "http",
            }
            data["mcpServers"] = existing_mcp
        else:
            if isinstance(existing_mcp, dict):
                existing_mcp.pop("autoconduck", None)
                if not existing_mcp:
                    data.pop("mcpServers", None)
                else:
                    data["mcpServers"] = existing_mcp

        data["autoconduck"] = {
            "managed_env_keys": list(values),
            "previous_env": previous,
            "previous_permissions": previous_permissions,
            "contributed_permissions": list(dict.fromkeys(contributed + allowed_tools)),
            "previous_hooks": previous_hooks,
            "contributed_hooks_events": contributed_hooks if hooks_enabled else [],
            "hooks_enabled": bool(hooks_enabled),
            "ingestion_path": "http",
        }
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def revert(self) -> None:
        """Remove managed environment values while preserving user settings."""
        for p in self.config_paths():
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                marker = data.get("autoconduck")
                env = data.get("env") if isinstance(data.get("env"), dict) else {}
                if isinstance(marker, dict):
                    previous = marker.get("previous_env", {})
                    managed_keys = marker.get("managed_env_keys", [])
                    keys = list(managed_keys) if isinstance(managed_keys, list) else []
                    keys.extend(
                        (
                            "ANTHROPIC_BASE_URL",
                            "ANTHROPIC_AUTH_TOKEN",
                            "ANTHROPIC_MODEL",
                            "ANTHROPIC_DEFAULT_OPUS_MODEL",
                            "ANTHROPIC_DEFAULT_SONNET_MODEL",
                            "ANTHROPIC_DEFAULT_HAIKU_MODEL",
                            "ANTHROPIC_CUSTOM_MODEL_OPTION",
                            "ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION",
                            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
                            "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS",
                            "CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT",
                            "CLAUDE_CODE_MAX_CONTEXT_TOKENS",
                        )
                    )
                    for key in dict.fromkeys(keys):
                        if key in previous:
                            env[key] = previous[key]
                        else:
                            env.pop(key, None)
                    if env:
                        data["env"] = env
                    else:
                        data.pop("env", None)
                    if (
                        "previous_permissions" in marker
                        and marker["previous_permissions"] is not None
                    ):
                        data["permissions"] = marker["previous_permissions"]
                    elif "previous_permissions" in marker:
                        permissions = data.get("permissions")
                        if isinstance(permissions, dict):
                            allow = permissions.get("allow")
                            contributed = marker.get("contributed_permissions", [])
                            if isinstance(allow, list) and isinstance(
                                contributed, list
                            ):
                                permissions["allow"] = [
                                    item for item in allow if item not in contributed
                                ]
                                if not permissions["allow"]:
                                    permissions.pop("allow", None)
                                if not permissions:
                                    data.pop("permissions", None)
                    # Restore hooks from previous_hooks snapshot if present, else strip managed hook entries
                    prev_hooks = marker.get("previous_hooks")
                    if "previous_hooks" in marker:
                        if prev_hooks is None:
                            data.pop("hooks", None)
                        elif isinstance(prev_hooks, dict):
                            if prev_hooks:
                                data["hooks"] = prev_hooks
                            else:
                                data.pop("hooks", None)
                        else:
                            # non-dict snapshot: strip managed entries defensively
                            stripped = self._strip_autoconduck_hooks(data.get("hooks") if isinstance(data.get("hooks"), dict) else None)
                            if stripped is None:
                                data.pop("hooks", None)
                            elif not stripped:
                                data.pop("hooks", None)
                            else:
                                data["hooks"] = stripped
                    else:
                        stripped = self._strip_autoconduck_hooks(data.get("hooks") if isinstance(data.get("hooks"), dict) else None)
                        if stripped is None:
                            data.pop("hooks", None)
                        elif not stripped:
                            data.pop("hooks", None)
                        else:
                            data["hooks"] = stripped
                else:
                    # No marker — still defensively strip any managed hooks
                    stripped = self._strip_autoconduck_hooks(data.get("hooks") if isinstance(data.get("hooks"), dict) else None)
                    if stripped is None:
                        data.pop("hooks", None)
                    elif isinstance(stripped, dict) and not stripped:
                        data.pop("hooks", None)
                    elif isinstance(stripped, dict):
                        data["hooks"] = stripped
                data.pop("autoconduck", None)
                mcp_servers = data.get("mcpServers")
                if isinstance(mcp_servers, dict):
                    mcp_servers.pop("autoconduck", None)
                    if not mcp_servers:
                        data.pop("mcpServers", None)
                    else:
                        data["mcpServers"] = mcp_servers
                model_overrides = data.get("modelOverrides")
                if isinstance(model_overrides, dict):
                    for pseudo_name in (
                        "autoconduck",
                        "autoconduck-budget",
                        "autoconduck-expensive",
                    ):
                        model_overrides.pop(pseudo_name, None)
                    if not model_overrides:
                        data.pop("modelOverrides", None)
                p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
