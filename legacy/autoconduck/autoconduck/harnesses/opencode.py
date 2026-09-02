from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import List

from .base import BaseAdapter
from ..config import Config, backups_dir


class OpenCodeAdapter(BaseAdapter):
    binary_name = "opencode"
    id = "opencode"
    display_name = "OpenCode"


    def detect(self) -> bool:
        if shutil.which(self.binary_name) is not None:
            return True
        return any(p.exists() for p in self.config_paths())

    def config_paths(self) -> List[Path]:
        home = Path.home()
        return [
            Path.cwd() / "opencode.json",
            Path.cwd() / "opencode.config.json",
            home / ".config" / "opencode" / "config.json",
            home / ".config" / "opencode" / "opencode.json",
            home / ".opencode.json",
            home / ".opencode" / "config.json",
        ]

    def _plugin_path(self) -> Path:
        return Path.home() / ".config" / "opencode" / "plugins" / "autoconduck.js"

    def _render_plugin_js(
        self,
        port: int,
        hooks_enabled: bool = False,
        subagent_enabled: bool = False,
        rag_enabled: bool = False,
    ) -> str:
        hooks_flag = "true" if hooks_enabled else "false"
        subagent_flag = "true" if subagent_enabled else "false"
        rag_flag = "true" if rag_enabled else "false"

        from autoconduck import __version__

        return (
            f"// AutoConduck OpenCode Plugin — managed by autoconduck v{__version__}\n"
            "// Provides: tool interception, subagent tracking, codebase search\n"
            "// Reinstall: autoconduck install opencode\n"
            "// Remove:    autoconduck uninstall opencode\n"
            "\n"
            f"const AUTOCONDUCK_PORT = {port};\n"
            f"const AUTOCONDUCK_HOOKS_ENABLED = {hooks_flag};\n"
            f"const AUTOCONDUCK_SUBAGENT_ENABLED = {subagent_flag};\n"
            f"const AUTOCONDUCK_RAG_ENABLED = {rag_flag};\n"
            "\n"
            "async function _sendEvent(eventData) {\n"
            "  try {\n"
            "    const res = await fetch(`http://127.0.0.1:${AUTOCONDUCK_PORT}/plugin/events`, {\n"
            '      method: "POST",\n'
            '      headers: { "Content-Type": "application/json" },\n'
            "      body: JSON.stringify(eventData),\n"
            "      signal: AbortSignal.timeout(20),\n"
            "    });\n"
            "    return res.ok;\n"
            "  } catch {\n"
            "    return false;\n"
            "  }\n"
            "}\n"
            "\n"
            "export const AutoConduckPlugin = async ({ client }) => {\n"
            "  return {\n"
            '    "tool.execute.before": async (input, output) => {\n'
            "      if (!AUTOCONDUCK_HOOKS_ENABLED) return;\n"
            "      await _sendEvent({\n"
            '        kind: "tool_call",\n'
            '        tool_name: input?.tool,\n'
            "        data: input,\n"
            "      });\n"
            "    },\n"
            '    "tool.execute.after": async (input, output) => {\n'
            "      if (!AUTOCONDUCK_HOOKS_ENABLED) return;\n"
            "      await _sendEvent({\n"
            '        kind: "tool_result",\n'
            '        tool_name: input?.tool,\n'
            "        data: output,\n"
            "      });\n"
            "    },\n"
            '    "event": async ({ event }) => {\n'
            "      if (!AUTOCONDUCK_SUBAGENT_ENABLED) return;\n"
            '      if (event?.type === "session.start" && event?.parentSessionId) {\n'
            "        await _sendEvent({\n"
            '          kind: "SubagentStart",\n'
            "          session_id: event.parentSessionId,\n"
            '          subagent_id: event.sessionId || event.id || "",\n'
            "        });\n"
            '      } else if (event?.type === "session.end" && event?.parentSessionId) {\n'
            "        await _sendEvent({\n"
            '          kind: "SubagentStop",\n'
            "          session_id: event.parentSessionId,\n"
            '          subagent_id: event.sessionId || event.id || "",\n'
            '          outcome: event.outcome || event.status || "unknown",\n'
            "        });\n"
            "      }\n"
            "    },\n"
            "    ...(AUTOCONDUCK_RAG_ENABLED ? {\n"
            '      "tool.autoconduck_search": async (args) => {\n'
            "        try {\n"
            f"          const res = await fetch(`http://127.0.0.1:${{AUTOCONDUCK_PORT}}/mcp/tools/call`, {{\n"
            '            method: "POST",\n'
            '            headers: { "Content-Type": "application/json" },\n'
            '            body: JSON.stringify({ tool: "autoconduck_search", args }),\n'
            "            signal: AbortSignal.timeout(3000),\n"
            "          });\n"
            '          return res.ok ? await res.json() : { error: "autoconduck unavailable" };\n'
            "        } catch {\n"
            '          return { error: "autoconduck unavailable" };\n'
            "        }\n"
            "      },\n"
            "    } : {}),\n"
            "  };\n"
            "};\n"
            "\n"
            "export default AutoConduckPlugin;\n"
        )

    def patch(self, config: Config, port: int | None = None) -> None:
        effective_port = int(port if port is not None else getattr(config, "port", 11434))
        endpoint = f"http://127.0.0.1:{effective_port}/v1"
        pseudo_model = getattr(config, "pseudo_model", "autoconduck") or "autoconduck"

        plugins = getattr(config, "plugins", None)
        hooks_enabled = bool(getattr(plugins, "enabled", False) and getattr(plugins, "opencode_enabled", False)) if plugins is not None else False
        subagent_enabled = bool(getattr(plugins, "enabled", False) and getattr(plugins, "subagent_enabled", False)) if plugins is not None else False
        rag_enabled = bool(getattr(plugins, "enabled", False) and getattr(plugins, "opencode_enabled", False) and getattr(plugins, "rag_enabled", False)) if plugins is not None else False

        plugin_file = self._plugin_path()
        plugin_file.parent.mkdir(parents=True, exist_ok=True)
        plugin_file.write_text(
            self._render_plugin_js(
                effective_port,
                hooks_enabled=hooks_enabled,
                subagent_enabled=subagent_enabled,
                rag_enabled=rag_enabled,
            ),
            encoding="utf-8",
        )

        def updater(data: dict) -> None:
            marker = data.get("autoconduck") if isinstance(data.get("autoconduck"), dict) else {}
            if "model" in data and not marker:
                marker["previous_model"] = data["model"]

            # Flat providers dictionary
            providers = data.setdefault("providers", {})
            if isinstance(providers, dict):
                ac = providers.setdefault("autoconduck", {})
                if isinstance(ac, dict):
                    ac["api_base"] = endpoint
                    ac["baseURL"] = endpoint
                    ac["apiKey"] = "autoconduck-local"
                    ac["models"] = ["autoconduck", "autoconduck-budget", "autoconduck-expensive"]

            # Structured provider dictionary
            provider = data.setdefault("provider", {})
            if isinstance(provider, dict):
                provider["autoconduck"] = {
                    "type": "openai",
                    "name": "AutoConduck",
                    "options": {
                        "baseURL": endpoint,
                        "apiKey": "autoconduck-local",
                    },
                    "models": {
                        "autoconduck": {
                            "name": "AutoConduck",
                            "limit": {"context": 1000000, "output": 16384},
                        },
                        "autoconduck-budget": {
                            "name": "AutoConduck Budget",
                            "limit": {"context": 1000000, "output": 16384},
                        },
                        "autoconduck-expensive": {
                            "name": "AutoConduck Expensive",
                            "limit": {"context": 1000000, "output": 16384},
                        },
                    },
                }

            # Register MCP in opencode.json
            if rag_enabled:
                mcp = data.setdefault("mcp", {})
                if isinstance(mcp, dict):
                    mcp["autoconduck"] = {
                        "type": "http",
                        "url": f"http://127.0.0.1:{effective_port}/mcp",
                    }
            else:
                if isinstance(data.get("mcp"), dict):
                    data["mcp"].pop("autoconduck", None)
                    if not data["mcp"]:
                        data.pop("mcp", None)

            # Register plugin in opencode.json
            plugin_entries = data.get("plugin")
            if not isinstance(plugin_entries, list):
                plugin_entries = []
                data["plugin"] = plugin_entries
            entry_str = "~/.config/opencode/plugins/autoconduck.js"
            if entry_str not in plugin_entries and not any("autoconduck.js" in str(x) for x in plugin_entries):
                plugin_entries.append(entry_str)

            # Managed active model
            data["model"] = f"autoconduck/{pseudo_model}"
            marker["managed"] = True
            marker["managed_model"] = f"autoconduck/{pseudo_model}"
            data["autoconduck"] = marker

        target = next((p for p in self.config_paths() if p.exists()), self.config_paths()[0])
        self._patch_json(target, updater)

    def revert(self) -> None:
        """Restore previous configuration or cleanly remove AutoConduck entries."""
        plugin_file = self._plugin_path()
        if plugin_file.exists():
            try:
                plugin_file.unlink()
            except OSError:
                pass

        dest_dir = backups_dir(self.id)
        if dest_dir.exists():
            for bak in sorted(dest_dir.glob("*.bak"), reverse=True):
                meta = bak.with_suffix(".meta")
                try:
                    src_str = meta.read_text(encoding="utf-8").strip() if meta.exists() else ""
                    if src_str:
                        src = Path(src_str)
                        src.parent.mkdir(parents=True, exist_ok=True)
                        src.write_bytes(bak.read_bytes())
                        return
                except Exception:
                    continue

        for p in self.config_paths():
            if not p.exists():
                continue
            try:
                raw = p.read_text(encoding="utf-8")
                data = json.loads(raw)
                if not isinstance(data, dict):
                    continue
                marker = data.pop("autoconduck", None)
                if isinstance(data.get("providers"), dict):
                    data["providers"].pop("autoconduck", None)
                    if not data["providers"]:
                        data.pop("providers", None)
                if isinstance(data.get("provider"), dict):
                    data["provider"].pop("autoconduck", None)
                    if not data["provider"]:
                        data.pop("provider", None)
                if isinstance(data.get("mcp"), dict):
                    data["mcp"].pop("autoconduck", None)
                    if not data["mcp"]:
                        data.pop("mcp", None)
                if isinstance(data.get("plugin"), list):
                    data["plugin"] = [
                        e for e in data["plugin"]
                        if not ("autoconduck.js" in str(e) or e == str(self._plugin_path()) or e == "~/.config/opencode/plugins/autoconduck.js")
                    ]
                    if not data["plugin"]:
                        data.pop("plugin", None)
                if isinstance(marker, dict) and "previous_model" in marker:
                    data["model"] = marker["previous_model"]
                elif str(data.get("model", "")).startswith("autoconduck"):
                    data.pop("model", None)
                p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            except Exception:
                continue

    def install_plugin_visibility(self, config: Config) -> None:
        """Write any harness-visible plugin/extension markers. Fail-soft: log warnings, do not raise."""
        import logging
        logger = logging.getLogger(__name__)
        try:
            plugin_path = self._plugin_path()
            if not plugin_path.exists():
                self.patch(config)
        except Exception as e:
            logger.warning(f"Failed to install plugin visibility for OpenCode: {e}")


