"""Adapter for Oh My Pi (OMP)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..config import Config, backups_dir
from .base import BaseAdapter


class OmpAdapter(BaseAdapter):
    """Register AutoConduck in OMP's YAML model registry."""

    binary_name: str | None = "omp"
    id = "omp"
    display_name = "Oh My Pi"
    provider_name = "autoconduck"
    PSEUDO_MODELS = (
        "fast",
        "balanced",
        "frontier",
    )


    def detect(self) -> bool:
        return self.detect_binary() or self.detect_config()

    def detect_binary(self) -> bool:
        binary_name = self.binary_name
        return binary_name is not None and shutil.which(binary_name) is not None

    def detect_config(self) -> bool:
        return any(path.is_file() for path in self.config_paths())

    def config_paths(self) -> list[Path]:
        home = Path.home()
        return [
            home / ".omp" / "agent" / "models.yml",
            home / ".omp" / "agent" / "models.yaml",
            Path.cwd() / ".omp" / "config.yml",
        ]

    def settings_paths(self) -> list[Path]:
        home = Path.home() / ".omp" / "agent"
        return [home / "config.yml", home / "config.yaml"]

    def _extension_path(self) -> Path:
        return Path.home() / ".omp" / "agent" / "extensions" / "autoconduck.ts"

    def _render_extension(
        self,
        port: int,
        hooks_enabled: bool = False,
        subagent_enabled: bool = False,
        rag_enabled: bool = False,
        spool_path: str | None = None,
    ) -> str:
        hooks_flag = "true" if hooks_enabled else "false"
        subagent_flag = "true" if subagent_enabled else "false"
        rag_flag = "true" if rag_enabled else "false"

        if spool_path is None:
            try:
                from autoconduck.config.paths import run_dir

                spool_path = str(run_dir() / "plugin_spool.jsonl")
            except Exception:
                spool_path = str(Path.home() / ".autoconduck" / "run" / "plugin_spool.jsonl")

        from autoconduck import __version__
        spool_json = json.dumps(str(spool_path))
        extension_version_json = json.dumps(__version__)
        provider_json = json.dumps(self.provider_name)
        pseudo_models_json = json.dumps(list(self.PSEUDO_MODELS))

        return (
            f"// AutoConduck Monitor & Router — managed by autoconduck v{__version__}\n"
            "// Provides: provider routing, subagent tracking (agent_start/agent_end), codebase search\n"
            "// Reinstall: autoconduck install omp\n"
            "// Remove:    autoconduck uninstall omp\n"
            "// Check loaded: run /extensions in OMP terminal\n"
            'import * as fs from "fs";\n'
            'import * as path from "path";\n'
            'import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";\n'
            "\n"
            f"const SPOOL_JSON_PATH = {spool_json};\n"
            f"const AUTOCONDUCK_EXTENSION_VERSION = {extension_version_json};\n"
            f"const AUTOCONDUCK_PROVIDER = {provider_json};\n"
            f"const AUTOCONDUCK_MODEL_IDS = new Set({pseudo_models_json});\n"
            "\n"
            "function _appendSpool(data: Record<string, unknown>): void {\n"
            "  try {\n"
            "    const spool = SPOOL_JSON_PATH;\n"
            "    fs.mkdirSync(path.dirname(spool), { recursive: true });\n"
            "    fs.appendFileSync(spool, JSON.stringify({ ts: new Date().toISOString(), ...data }) + '\\n');\n"
            "  } catch {}\n"
            "}\n"
            "\n"
            "async function _postOrSpool(data: Record<string, unknown>): Promise<void> {\n"
            "  try {\n"
            f"    const res = await fetch(`http://127.0.0.1:{port}/plugin/events`, {{\n"
            "      method: 'POST',\n"
            "      headers: { 'content-type': 'application/json' },\n"
            "      body: JSON.stringify({ ts: new Date().toISOString(), ...data }),\n"
            "      signal: AbortSignal.timeout(500),\n"
            "    });\n"
            "    if (!res.ok) {\n"
            "      _appendSpool(data);\n"
            "    }\n"
            "  } catch {\n"
            "    _appendSpool(data);\n"
            "  }\n"
            "}\n"
            "\n"
            "async function _postEscalate(sessionId: string, reason: string): Promise<void> {\n"
            "  if (!sessionId) return;\n"
            "  try {\n"
            f"    const res = await fetch(`http://127.0.0.1:{port}/plugin/escalate`, {{\n"
            "      method: 'POST',\n"
            "      headers: { 'content-type': 'application/json' },\n"
            "      body: JSON.stringify({ session_id: sessionId, reason: reason }),\n"
            "      signal: AbortSignal.timeout(500),\n"
            "    });\n"
            "    if (!res.ok) {\n"
            "      _appendSpool({ event: 'escalate', session_id: sessionId, reason: reason });\n"
            "    }\n"
            "  } catch {\n"
            "    _appendSpool({ event: 'escalate', session_id: sessionId, reason: reason });\n"
            "  }\n"
            "}\n"
            "\n"
            "export default function (pi: ExtensionAPI) {\n"
            f"  const AUTOCONDUCK_HOOKS_ENABLED = {hooks_flag};\n"
            f"  const AUTOCONDUCK_SUBAGENT_ENABLED = {subagent_flag};\n"
            f"  const AUTOCONDUCK_RAG_ENABLED = {rag_flag};\n"
            "\n"
            "  let lastToolName = '';\n"
            "  let sameToolStreak = 0;\n"
            "  let consecutiveErrors = 0;\n"
            "  let sessionHeartbeatSent = false;\n"
            "\n"
            "  pi.on('before_provider_request', (event: any, ctx: any) => {\n"
            "    try {\n"
            "      const payload = event?.payload;\n"
            "      if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return;\n"
            "      const currentModel = ctx?.model;\n"
            "      const model = payload.model;\n"
            "      if (\n"
            "        currentModel?.provider !== AUTOCONDUCK_PROVIDER ||\n"
            "        !AUTOCONDUCK_MODEL_IDS.has(currentModel.id) ||\n"
            "        typeof model !== 'string' ||\n"
            "        !AUTOCONDUCK_MODEL_IDS.has(model)\n"
            "      ) return;\n"
            "      const sessionId = ctx?.sessionManager?.getSessionId?.();\n"
            "      if (typeof sessionId !== 'string' || !sessionId.trim()) return;\n"
            "      return { ...payload, autoconduck_session_id: sessionId.trim() };\n"
            "    } catch {\n"
            "      return;\n"
            "    }\n"
            "  });\n"
            "\n"
            "  function trackToolStagnation(sessionId: string, toolName: string, isError: boolean): void {\n"
            "    if (isError) {\n"
            "      consecutiveErrors++;\n"
            "    } else {\n"
            "      consecutiveErrors = 0;\n"
            "    }\n"
            "    if (toolName && toolName === lastToolName) {\n"
            "      sameToolStreak++;\n"
            "    } else {\n"
            "      sameToolStreak = 1;\n"
            "      lastToolName = toolName;\n"
            "    }\n"
            "    if (consecutiveErrors >= 2) {\n"
            "      _postEscalate(sessionId, 'consecutive_errors');\n"
            "    } else if (sameToolStreak >= 3) {\n"
            "      _postEscalate(sessionId, 'repeated_calls');\n"
            "    }\n"
            "  }\n"
            "\n"
            "  if (AUTOCONDUCK_SUBAGENT_ENABLED) {\n"
            "    pi.on('agent_start', (event: any) => {\n"
            "      if (event?.agentKind === 'sub' && event?.parentSessionId) {\n"
            "        _postOrSpool({ event: 'SubagentStart', session_id: event.parentSessionId, subagent_id: event.sessionId || event.id || '' });\n"
            "      }\n"
            "    });\n"
            "    pi.on('agent_end', (event: any) => {\n"
            "      if (event?.agentKind === 'sub' && event?.parentSessionId) {\n"
            "        _postOrSpool({ event: 'SubagentStop', session_id: event.parentSessionId, subagent_id: event.sessionId || event.id || '', outcome: event.outcome ?? event.status ?? 'unknown' });\n"
            "      }\n"
            "    });\n"
            "  }\n"
            "\n"
            "  if (AUTOCONDUCK_HOOKS_ENABLED) {\n"
            "    pi.on('session_start', (event: any) => {\n"
            "      const sid = event?.sessionId || event?.id || '';\n"
            "      if (sid && !sessionHeartbeatSent) {\n"
            "        sessionHeartbeatSent = true;\n"
            "        _postOrSpool({\n"
            "          event: 'session_start',\n"
            "          session_id: sid,\n"
            "          data: {\n"
            "            source: 'omp_extension',\n"
            "            extension: 'autoconduck',\n"
            "            extension_version: AUTOCONDUCK_EXTENSION_VERSION,\n"
            "          },\n"
            "        });\n"
            "      }\n"
            "    });\n"
            "    pi.on('tool_call', (event: any) => {\n"
            "      _postOrSpool({\n"
            "        event: 'tool_call',\n"
            "        session_id: event?.sessionId || '',\n"
            "        tool_name: event?.toolName || event?.name || '',\n"
            "      });\n"
            "    });\n"
            "    pi.on('tool_result', (event: any) => {\n"
            "      const sid = event?.sessionId || '';\n"
            "      const toolName = event?.toolName || event?.name || '';\n"
            "      const isErr = Boolean(event?.isError || event?.error);\n"
            "      _postOrSpool({\n"
            "        event: 'tool_result',\n"
            "        session_id: sid,\n"
            "        tool_name: toolName,\n"
            "        is_error: isErr,\n"
            "      });\n"
            "      if (sid) {\n"
            "        trackToolStagnation(sid, toolName, isErr);\n"
            "      }\n"
            "    });\n"
            "  }\n"
            "\n"
            "  if (AUTOCONDUCK_RAG_ENABLED) {\n"
            "    const z = (pi as any).zod;\n"
            "    pi.registerTool({\n"
            "      name: 'autoconduck_search',\n"
            "      label: 'AutoConduck Search',\n"
            "      description: 'Search the AutoConduck indexed knowledge base for codebase symbols.',\n"
            "      parameters: z ? z.object({\n"
            "        query: z.string().describe('Search query for codebase symbols or concepts'),\n"
            "        limit: z.number().optional().describe('Maximum number of results (default 5)'),\n"
            "      }) : undefined,\n"
            "      async execute(_toolCallId: string, params: { query: string; limit?: number }) {\n"
            "        try {\n"
            f"          const res = await fetch(`http://127.0.0.1:{port}/mcp/tools/call`, {{\n"
            "            method: 'POST',\n"
            "            headers: { 'content-type': 'application/json' },\n"
            "            body: JSON.stringify({ tool: 'autoconduck_search', args: params }),\n"
            "            signal: AbortSignal.timeout(3000),\n"
            "          });\n"
            "          if (res.ok) {\n"
            "            const data = await res.json();\n"
            "            const textContent = typeof data === 'string' ? data : JSON.stringify(data, null, 2);\n"
            "            return {\n"
            "              content: [{ type: 'text', text: textContent }],\n"
            "              details: data,\n"
            "            };\n"
            "          }\n"
            "          return {\n"
            "            content: [{ type: 'text', text: 'Error: autoconduck unavailable' }],\n"
            "            details: { error: 'autoconduck unavailable' },\n"
            "            isError: true,\n"
            "          };\n"
            "        } catch {\n"
            "          return {\n"
            "            content: [{ type: 'text', text: 'Error: autoconduck unavailable' }],\n"
            "            details: { error: 'autoconduck unavailable' },\n"
            "            isError: true,\n"
            "          };\n"
            "        }\n"
            "      },\n"
            "    });\n"
            "  }\n"
            "}\n"
        )

    def patch(self, config: Config, port: int | None = None) -> None:
        import yaml

        try:
            effective_port = int(
                port if port is not None else getattr(config, "port", 11434)
            )
        except (TypeError, ValueError):
            effective_port = 11434
        target = next(
            (path for path in self.config_paths() if path.exists()),
            self.config_paths()[0],
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        existing = {}
        if target.exists():
            self.backup(target)
            try:
                loaded = yaml.safe_load(target.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError):
                loaded = {}
            if isinstance(loaded, dict):
                existing = loaded

        providers = existing.setdefault("providers", {})
        if not isinstance(providers, dict):
            providers = {}
            existing["providers"] = providers
        providers[self.provider_name] = {
            "baseUrl": f"http://127.0.0.1:{effective_port}/v1",
            "api": "openai-completions",
            "apiKey": "autoconduck-local",
            "auth": "none",
            "headers": {
                "x-agent-id": "omp",
            },
            "models": [
                {
                    "id": model,
                    "name": f"AutoConduck {model.replace('-', ' ').title()}",
                    "contextWindow": 1000000,
                    "maxTokens": 16384,
                }
                for model in self.PSEUDO_MODELS
            ],
        }
        target.write_text(yaml.safe_dump(existing, sort_keys=False), encoding="utf-8")

        configured_pseudo_model = getattr(config, "pseudo_model", None)
        pseudo_model = str(
            configured_pseudo_model
            if configured_pseudo_model in self.PSEUDO_MODELS
            else "balanced"
        )
        settings_target = next(
            (path for path in self.settings_paths() if path.exists()),
            self.settings_paths()[0],
        )
        settings_target.parent.mkdir(parents=True, exist_ok=True)
        settings = {}
        if settings_target.exists():
            self.backup(settings_target)
            try:
                loaded = yaml.safe_load(settings_target.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError):
                loaded = {}
            if isinstance(loaded, dict):
                settings = loaded
        model_roles = settings.setdefault("modelRoles", {})
        if not isinstance(model_roles, dict):
            model_roles = {}
            settings["modelRoles"] = model_roles
        model_roles["default"] = f"autoconduck/{pseudo_model}"
        settings_target.write_text(
            yaml.safe_dump(settings, sort_keys=False), encoding="utf-8"
        )

        plugins = getattr(config, "plugins", None)
        hooks_enabled = bool(getattr(plugins, "enabled", False) and getattr(plugins, "omp_enabled", False)) if plugins is not None else False
        subagent_enabled = bool(getattr(plugins, "enabled", False) and (getattr(plugins, "omp_enabled", False) or getattr(plugins, "subagent_enabled", False))) if plugins is not None else False
        rag_enabled = bool(getattr(plugins, "enabled", False) and getattr(plugins, "omp_enabled", False) and getattr(plugins, "rag_enabled", False)) if plugins is not None else False
        try:
            from autoconduck.config.paths import run_dir

            spool_path = str(run_dir() / "plugin_spool.jsonl")
        except Exception:
            spool_path = str(Path.home() / ".autoconduck" / "run" / "plugin_spool.jsonl")

        ext_path = self._extension_path()
        ext_path.parent.mkdir(parents=True, exist_ok=True)
        ext_path.write_text(
            self._render_extension(
                effective_port,
                hooks_enabled=hooks_enabled,
                subagent_enabled=subagent_enabled,
                rag_enabled=rag_enabled,
                spool_path=spool_path,
            ),
            encoding="utf-8",
        )

    def revert(self) -> None:
        """Restore the latest backup for OMP, or remove only our provider."""
        ext_path = self._extension_path()
        if ext_path.exists():
            try:
                ext_path.unlink()
            except OSError:
                pass

        bak_dir = backups_dir(self.id)
        restored_sources: set[Path] = set()
        if bak_dir.exists():
            for backup in sorted(bak_dir.glob("*.bak"), reverse=True):
                meta = backup.with_suffix(".meta")
                try:
                    source = Path(meta.read_text(encoding="utf-8").strip())
                except (OSError, ValueError):
                    continue
                if (
                    source.name
                    in {"models.yml", "models.yaml", "config.yml", "config.yaml"}
                    and source not in restored_sources
                ):
                    try:
                        source.parent.mkdir(parents=True, exist_ok=True)
                        source.write_bytes(backup.read_bytes())
                        restored_sources.add(source)
                    except OSError:
                        continue

        import yaml

        for path in [*self.config_paths(), *self.settings_paths()]:
            if path in restored_sources:
                continue
            if not path.exists():
                continue
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError):
                continue
            if not isinstance(data, dict):
                continue
            providers = data.get("providers")
            if isinstance(providers, dict):
                providers.pop(self.provider_name, None)
                if not providers:
                    data.pop("providers", None)
            if path in self.settings_paths():
                model_roles = data.get("modelRoles")
                if isinstance(model_roles, dict) and str(
                    model_roles.get("default", "")
                ).startswith("autoconduck/"):
                    model_roles.pop("default", None)
                    if not model_roles:
                        data.pop("modelRoles", None)
            path.write_text(
                yaml.safe_dump(data, sort_keys=False) if data else "", encoding="utf-8"
            )

    def install_features(self) -> list[str]:
        return []

    def install_plugin_visibility(self, config: Config) -> None:
        """Write any harness-visible plugin/extension markers. Fail-soft: log warnings, do not raise."""
        import logging
        logger = logging.getLogger(__name__)
        try:
            ext_path = self._extension_path()
            if not ext_path.exists():
                self.patch(config)
        except Exception as e:
            logger.warning(f"Failed to install plugin visibility for OMP: {e}")

