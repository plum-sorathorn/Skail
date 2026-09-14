"""Plugin & harness hook onboarding screen."""
from __future__ import annotations

import logging
from typing import Any

from skail.config import get_config, save_config

try:
    from textual.app import ComposeResult
    from textual.containers import Vertical
    from textual.screen import Screen
    from textual.widgets import Static
    _TEXTUAL = True
except ImportError:
    _TEXTUAL = False
    class Screen: pass
    ComposeResult = object

logger = logging.getLogger(__name__)


if _TEXTUAL:
    class PluginSetupScreen(Screen):
        """Onboarding screen for enabling plugin runtime and harness hook integration."""

        OPTIONS = [
            {
                "id": "full",
                "title": "Enable Plugin Runtime — Full Integration (Recommended)",
                "desc": "HTTP hooks, subagent tracking, codebase search (local RAG via MCP), stagnation recovery, and escalation bias.",
                "plugins_enabled": True,
                "claude_enabled": True,
                "subagent_enabled": True,
                "rag_enabled": True,
            },
            {
                "id": "runtime_only",
                "title": "Enable Plugin Runtime — Stagnation & Escalation Only (No Hooks, No RAG)",
                "desc": "Deterministic stagnation detection and ledger persistence without modifying harness hooks or enabling RAG tool.",
                "plugins_enabled": True,
                "claude_enabled": False,
                "subagent_enabled": False,
                "rag_enabled": False,
            },
            {
                "id": "disabled",
                "title": "Disable Plugin (Pure Router Mode)",
                "desc": "Zero overhead, zero background tailing, pure stateless model routing across turns.",
                "plugins_enabled": False,
                "claude_enabled": False,
                "subagent_enabled": False,
                "rag_enabled": False,
            },
        ]

        def __init__(self, controller=None, agents=None):
            super().__init__()
            self.controller = controller
            self.agents = set(agents or ())

            cfg = get_config()
            plugins = getattr(cfg, "plugins", None)
            is_enabled = bool(getattr(plugins, "enabled", False))
            claude_enabled = bool(getattr(plugins, "claude_enabled", False))
            subagent_enabled = bool(getattr(plugins, "subagent_enabled", False))
            rag_enabled = bool(getattr(plugins, "rag_enabled", False))

            if is_enabled and (claude_enabled or subagent_enabled or rag_enabled):
                self.cursor = 0
            elif is_enabled and not claude_enabled and not subagent_enabled and not rag_enabled:
                self.cursor = 1
            elif plugins is not None and not is_enabled:
                self.cursor = 2
            else:
                self.cursor = 0

            self.selected_idx = self.cursor

        def compose(self):
            yield Vertical(
                Static("┌─ Skail · Plugin & Harness Integration ─┐"),
                Static(
                    "Skail includes an optional deterministic plugin plane for automated stagnation\n"
                    "recovery, multi-tier capability escalation, and durable telemetry ledger.\n"
                    "Choose how plugins should be configured for your coding harnesses:"
                ),
                Static(self._render_rows(), id="options", markup=True),
                Static(self._render_desc(), id="description", markup=True),
                Static("[↑/↓] move · [space/enter] select · [→] confirm & continue · [←] back · [ctrl+c] quit"),
            )

        def _render_rows(self) -> str:
            lines = []
            for i, opt in enumerate(self.OPTIONS):
                prefix = ">" if i == self.cursor else " "
                radio = "(•)" if i == self.selected_idx else "( )"
                title = opt["title"]
                if i == self.cursor:
                    lines.append(f"[bold cyan]{prefix} {radio} {title}[/bold cyan]")
                else:
                    lines.append(f"  {radio} {title}")
            return "\n".join(lines)

        def _render_desc(self) -> str:
            curr = self.OPTIONS[self.cursor]
            return f"[dim]ℹ {curr['desc']}[/dim]"

        def _update_view(self):
            try:
                self.query_one("#options").update(self._render_rows())
                self.query_one("#description").update(self._render_desc())
            except Exception:
                pass

        def on_key(self, e):
            if e.key == "down":
                self.cursor = (self.cursor + 1) % len(self.OPTIONS)
                self.selected_idx = self.cursor
                self._update_view()
            elif e.key == "up":
                self.cursor = (self.cursor - 1 + len(self.OPTIONS)) % len(self.OPTIONS)
                self.selected_idx = self.cursor
                self._update_view()
            elif e.key == "space":
                self.selected_idx = self.cursor
                self._update_view()
            elif e.key in ("enter", "right"):
                self.selected_idx = self.cursor
                self._confirm_and_continue()
            elif e.key == "left":
                if self.controller:
                    self.controller.pop_screen()

        def _confirm_and_continue(self):
            opt = self.OPTIONS[self.selected_idx]
            cfg = get_config()
            if getattr(cfg, "plugins", None) is None:
                from skail.config.models import PluginConfig
                cfg.plugins = PluginConfig()
            cfg.plugins.enabled = opt["plugins_enabled"]
            cfg.plugins.claude_enabled = opt["claude_enabled"]
            cfg.plugins.subagent_enabled = opt["subagent_enabled"]
            cfg.plugins.rag_enabled = opt["rag_enabled"]
            if opt["plugins_enabled"]:
                cfg.plugins.omp_enabled = bool("omp" in self.agents if self.agents else True)
                cfg.plugins.pi_enabled = bool("pi" in self.agents if self.agents else False)
                cfg.plugins.opencode_enabled = bool("opencode" in self.agents if self.agents else False)
            else:
                cfg.plugins.omp_enabled = False
                cfg.plugins.pi_enabled = False
                cfg.plugins.opencode_enabled = False
            save_config(cfg)

            from .screens_extra import LauncherIntegrationScreen
            from .helpers import configure_selected_agents

            if self.agents & LauncherIntegrationScreen.ELIGIBLE:
                if self.controller:
                    self.controller.push_screen(
                        LauncherIntegrationScreen(self.controller, self.agents)
                    )
            else:
                configure_selected_agents(self.agents)
                from .screens_slm import SLMSetupScreen
                if self.controller:
                    self.controller.push_screen(SLMSetupScreen(self.controller))
else:
    class PluginSetupScreen(Screen):
        def __init__(self, *a, **k):
            from . import _require_textual
            _require_textual()
