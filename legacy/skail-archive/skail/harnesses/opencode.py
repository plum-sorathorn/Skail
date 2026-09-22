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
        return Path.home() / ".config" / "opencode" / "plugins" / "skail.js"

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

        from skail import __version__

        return (
            f"// Skail OpenCode Plugin — managed by skail v{__version__}\n"
            "// Provides: tool interception, subagent tracking, codebase search\n"
            "// Reinstall: skail install opencode\n"
            "// Remove:    skail uninstall opencode\n"
            "\n"
            f"const SKAIL_PORT = {port};\n"
            f"const SKAIL_HOOKS_ENABLED = {hooks_flag};\n"
            f"const SKAIL_SUBAGENT_ENABLED = {subagent_flag};\n"
            f"const SKAIL_RAG_ENABLED = {rag_flag};\n"
            "\n"
            "async function _sendEvent(eventData) {\n"
            "  try {\n"
            "    const res = await fetch(`http://127.0.0.1:${SKAIL_PORT}/plugin/events`, {\n"
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
            "export const SkailPlugin = async ({ client }) => {\n"
            "  return {\n"
            '    "tool.execute.before": async (input, output) => {\n'
            "      if (!SKAIL_HOOKS_ENABLED) return;\n"
            "      await _sendEvent({\n"
            '        kind: "tool_call",\n'
            '        tool_name: input?.tool,\n'
            "        data: input,\n"
            "      });\n"
            "    },\n"
            '    "tool.execute.after": async (input, output) => {\n'
            "      if (!SKAIL_HOOKS_ENABLED) return;\n"
            "      await _sendEvent({\n"
            '        kind: "tool_result",\n'
            '        tool_name: input?.tool,\n'
            "        data: output,\n"
            "      });\n"
            "    },\n"
            '    "event": async ({ event }) => {\n'
            "      if (!SKAIL_SUBAGENT_ENABLED) return;\n"
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
            "    ...(SKAIL_RAG_ENABLED ? {\n"
            '      "tool.skail_search": async (args) => {\n'
            "        try {\n"
            f"          const res = await fetch(`http://127.0.0.1:${{SKAIL_PORT}}/mcp/tools/call`, {{\n"
            '            method: "POST",\n'
            '            headers: { "Content-Type": "application/json" },\n'
            '            body: JSON.stringify({ tool: "skail_search", args }),\n'
            "            signal: AbortSignal.timeout(3000),\n"
            "          });\n"
            '          return res.ok ? await res.json() : { error: "skail unavailable" };\n'
            "        } catch {\n"
            '          return { error: "skail unavailable" };\n'
            "        }\n"
            "      },\n"
            "    } : {}),\n"
            "  };\n"
            "};\n"
            "\n"
            "export default SkailPlugin;\n"
        )

    def patch(self, config: Config, port: int | None = None) -> None:
        effective_port = int(port if port is not None else getattr(config, "port", 11434))
        endpoint = f"http://127.0.0.1:{effective_port}/v1"
        pseudo_model = getattr(config, "pseudo_model", "skail") or "skail"

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
            marker = data.get("skail") if isinstance(data.get("skail"), dict) else {}
            if "model" in data and not marker:
                marker["previous_model"] = data["model"]

            # Flat providers dictionary
            providers = data.setdefault("providers", {})
            if isinstance(providers, dict):
                ac = providers.setdefault("skail", {})
                if isinstance(ac, dict):
                    ac["api_base"] = endpoint
                    ac["baseURL"] = endpoint
                    ac["apiKey"] = "skail-local"
                    ac["models"] = ["skail", "skail-budget", "skail-expensive"]

            # Structured provider dictionary
            provider = data.setdefault("provider", {})
            if isinstance(provider, dict):
                provider["skail"] = {
                    "type": "openai",
                    "name": "Skail",
                    "options": {
                        "baseURL": endpoint,
                        "apiKey": "skail-local",
                    },
                    "models": {
                        "skail": {
                            "name": "Skail",
                            "limit": {"context": 1000000, "output": 16384},
                        },
                        "skail-budget": {
                            "name": "Skail Budget",
                            "limit": {"context": 1000000, "output": 16384},
                        },
                        "skail-expensive": {
                            "name": "Skail Expensive",
                            "limit": {"context": 1000000, "output": 16384},
                        },
                    },
                }

            # Register MCP in opencode.json
            if rag_enabled:
                mcp = data.setdefault("mcp", {})
                if isinstance(mcp, dict):
                    mcp["skail"] = {
                        "type": "http",
                        "url": f"http://127.0.0.1:{effective_port}/mcp",
                    }
            else:
                if isinstance(data.get("mcp"), dict):
                    data["mcp"].pop("skail", None)
                    if not data["mcp"]:
                        data.pop("mcp", None)

            # Register plugin in opencode.json
            plugin_entries = data.get("plugin")
            if not isinstance(plugin_entries, list):
                plugin_entries = []
                data["plugin"] = plugin_entries
            entry_str = "~/.config/opencode/plugins/skail.js"
            if entry_str not in plugin_entries and not any("skail.js" in str(x) for x in plugin_entries):
                plugin_entries.append(entry_str)

            # Managed active model
            data["model"] = f"skail/{pseudo_model}"
            marker["managed"] = True
            marker["managed_model"] = f"skail/{pseudo_model}"
            data["skail"] = marker

        target = next((p for p in self.config_paths() if p.exists()), self.config_paths()[0])
        self._patch_json(target, updater)

    def revert(self) -> None:
        """Restore previous configuration or cleanly remove Skail entries."""
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
                marker = data.pop("skail", None)
                if isinstance(data.get("providers"), dict):
                    data["providers"].pop("skail", None)
                    if not data["providers"]:
                        data.pop("providers", None)
                if isinstance(data.get("provider"), dict):
                    data["provider"].pop("skail", None)
                    if not data["provider"]:
                        data.pop("provider", None)
                if isinstance(data.get("mcp"), dict):
                    data["mcp"].pop("skail", None)
                    if not data["mcp"]:
                        data.pop("mcp", None)
                if isinstance(data.get("plugin"), list):
                    data["plugin"] = [
                        e for e in data["plugin"]
                        if not ("skail.js" in str(e) or e == str(self._plugin_path()) or e == "~/.config/opencode/plugins/skail.js")
                    ]
                    if not data["plugin"]:
                        data.pop("plugin", None)
                if isinstance(marker, dict) and "previous_model" in marker:
                    data["model"] = marker["previous_model"]
                elif str(data.get("model", "")).startswith("skail"):
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


