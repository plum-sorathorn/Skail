"""Compact live routing dashboard / main navigation hub."""

from __future__ import annotations

from typing import Any

from autoconduck.tui.dashboard_screens import (
    DrillDownScreen,
    LaunchAgentScreen,
    UpdateCatalogScreen,
    UpdateScreen,
)
from autoconduck.tui.dashboard_widgets import (
    DASHBOARD_WINDOWS,
    _cell_len,
    build_dashboard_snapshot,
    decision_path,
    decision_explanation,
    _format_box_lines,
    move_cursor,
    record_value,
    render_log_rows,
)
from autoconduck.tui.keymap import FOOTER_HINT

try:
    from textual.containers import Vertical
    from textual.screen import Screen
    from textual.widgets import DataTable, Static
    _TEXTUAL = True
except ImportError:
    _TEXTUAL = False

    class Screen:  # type: ignore
        pass

    def _require():
        raise RuntimeError("Textual is required to use the AutoConduck TUI")


if _TEXTUAL:
    class MainMenuScreen(Screen):
        """Main navigation hub."""

        DUCK_FRAMES = [
            '  __(o<   [bold cyan]AutoConduck[/bold cyan]',
            '  __(.<   [bold cyan]AutoConduck[/bold cyan]',
            '  __(^<   [bold cyan]AutoConduck[/bold cyan]',
        ]

        MENU_ITEMS = [
            ("d", "Live Routing Stats", "Real-time routing decisions & cost tracker"),
            ("m", "Model Catalog", "Providers, presets, and API key vault"),
            ("c", "Configure Integrations", "Re-configure models and coding agents"),
            ("u", "Check for Updates", "Check latest version & upgrade AutoConduck"),
            ("s", "Settings", "Launch behaviour, thresholds, log level"),
            ("a", "Launch Agent", "Start a configured coding agent"),
        ]

        def __init__(self):
            super().__init__()
            self.cursor = 0
            self.duck_frame = 0
            self.totals = {
                "calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost": 0.0,
            }

        def compose(self):
            yield Vertical(
                Static(self._header(), id="header", markup=True),
                Static(self._stats_line(), id="stats", markup=True),
                Static(self._menu(), id="menu", markup=True),
                Static(
                    "[up/down] navigate  [enter] open  [key] shortcut  [ctrl+c] quit",
                    id="footer",
                    markup=False,
                ),
            )

        def on_mount(self):
            self._update_stats()
            self.set_interval(1.5, self._tick)

        def _tick(self):
            self.duck_frame = (self.duck_frame + 1) % len(self.DUCK_FRAMES)
            self._update_stats()
            try:
                self.query_one("#header", Static).update(self._header())
                self.query_one("#stats", Static).update(self._stats_line())
            except Exception:
                pass

        def _update_stats(self):
            try:
                from autoconduck import stats

                records = stats.load_records(limit=50)
                if records:
                    agg = stats.aggregate(records)
                    self.totals = agg.get("totals", self.totals)
            except Exception:
                pass

        def _header(self):
            duck = self.DUCK_FRAMES[self.duck_frame]
            return f"{duck} [green]RUNNING[/green]\n  \\___)"

        def _stats_line(self):
            t = self.totals
            return (
                f"Calls: [bold]{t['calls']}[/bold]  "
                f"Tokens: [bold]{t['total_tokens']:,}[/bold]  "
                f"Spend: [bold green]${t['cost']:.4f}[/bold green] USD"
            )

        def _menu(self):
            lines = ["", "  Navigate to:", ""]
            for i, (key, title, desc) in enumerate(self.MENU_ITEMS):
                mark = ">> " if i == self.cursor else "   "
                if i == self.cursor:
                    row = f"{mark}\\[{key}] [bold cyan]{title}[/bold cyan]  [dim]{desc}[/dim]"
                else:
                    row = f"{mark}\\[{key}] [bold]{title}[/bold]  [dim]{desc}[/dim]"
                lines.append(row)
            return "\n".join(lines)

        def _navigate(self, idx: int):
            _, title, _ = self.MENU_ITEMS[idx]
            app = self.app
            if idx == 0:
                app.push_screen(DashboardScreen())
            elif idx == 1:
                from .onboarding.screens_models import ModelCatalogScreen
                app.push_screen(ModelCatalogScreen(app))
            elif idx == 2:
                from .onboarding import ModelSourceScreen
                app.push_screen(ModelSourceScreen(app))
            elif idx == 3:
                app.push_screen(UpdateScreen(app))
            elif idx == 4:
                from .settings import SettingsScreen

                app.push_screen(SettingsScreen(app))
            elif idx == 5:
                app.push_screen(LaunchAgentScreen(app))

        def on_key(self, event):
            if event.key == "down":
                self.cursor = move_cursor(self.cursor, 1, len(self.MENU_ITEMS))
                self.query_one("#menu").update(self._menu())
            elif event.key == "up":
                self.cursor = move_cursor(self.cursor, -1, len(self.MENU_ITEMS))
                self.query_one("#menu").update(self._menu())
            elif event.key == "enter":
                self._navigate(self.cursor)
            else:
                for i, (key, _, _) in enumerate(self.MENU_ITEMS):
                    if event.key == key:
                        self.cursor = i
                        self.query_one("#menu").update(self._menu())
                        self._navigate(i)
                        break

    class DashboardScreen(Screen):
        """Live routing decisions log — accessible from the main menu."""

        BINDINGS = [
            ("d", "drill", "drill selected decision"),
            ("p", "pause", "pause"),
            ("enter", "drill", "open decision"),
            ("bracketleft", "previous_window", "previous window"),
            ("bracketright", "next_window", "next window"),
            ("r", "refresh", "refresh persisted stats"),
        ]
        DUCK_FRAMES = [
            '  __(o<   [bold cyan]AutoConduck[/bold cyan] . [green]proxy active[/green]',
            '  __(.<   [bold cyan]AutoConduck[/bold cyan] . [green]proxy active[/green]',
            '  __(^<   [bold cyan]AutoConduck[/bold cyan] . [green]proxy active[/green]',
        ]

        def __init__(self, session_id: str | None = None):
            super().__init__()
            self.session_id = session_id
            self.selected_window = "1h"
            self.records: list[dict[str, Any]] = []
            self.cursor = 0
            self.paused = False
            self.duck_frame = 0
            self.totals = {
                "calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost": 0.0,
            }
            self.models_breakdown: dict[str, dict[str, Any]] = {}
            self.paths: dict[str, int] = {}
            self.pseudos: dict[str, int] = {}
            self.metrics: dict[str, Any] = {}
            self.snapshot = build_dashboard_snapshot(
                [],
                session_id=self.session_id,
                window=self.selected_window,
                plugins_enabled=None,
            )

        def compose(self):
            yield Vertical(
                Static(self._mascot_header(), id="header", markup=True),
                Static(self._graph_view(), id="graph", markup=True),
                Static(self._telemetry_cards(), id="telemetry", markup=True),
                Static(self._stats_summary(), id="stats", markup=True),
                DataTable(id="decisions", cursor_type="row"),
                Static(
                    "[up/down] move  [enter/d] details  [/] window  [r] refresh  [p] pause  [esc/left] back  [ctrl+c] quit",
                    id="footer",
                    markup=False,
                ),
            )

        def on_mount(self):
            try:
                table = self.query_one("#decisions", DataTable)
                table.add_columns("Timestamp", "Path", "Model Selected", "In/Out Tokens", "Cost", "Latency (ms)", "Decision Evidence")
            except Exception:
                pass
            self._update_stats()
            self.set_interval(0.8, self._tick)

        def _tick(self):
            self.duck_frame = (self.duck_frame + 1) % len(self.DUCK_FRAMES)
            if not self.paused:
                self._update_stats()
            self._render_dashboard()

        def _render_dashboard(self):
            try:
                self.query_one("#header", Static).update(self._mascot_header())
                self.query_one("#graph", Static).update(self._graph_view())
                self.query_one("#telemetry", Static).update(self._telemetry_cards())
                self.query_one("#stats", Static).update(self._stats_summary())
                self._refresh_table()
            except Exception:
                pass

        def _update_stats(self):
            try:
                from autoconduck import stats
                from autoconduck.config import get_config

                records = stats.load_records()
                cfg = get_config()
                plugins = getattr(cfg, "plugins", None)
                self.snapshot = build_dashboard_snapshot(
                    records,
                    session_id=self.session_id,
                    window=self.selected_window,
                    plugins_enabled=getattr(plugins, "enabled", None),
                )
                session = self.snapshot["session"]
                self.records = session["decisions"]
                self.totals = session["usage"] or {
                    "calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cost": 0.0,
                }
                self.models_breakdown = session["models"]
                self.paths = session["paths"]
                self.pseudos = session["pseudos"]
                self.metrics = self.totals
            except Exception:
                self.snapshot = build_dashboard_snapshot(
                    [],
                    session_id=self.session_id,
                    window=self.selected_window,
                    plugins_enabled=None,
                )
                self.records = []
                self.metrics = {}

        def _refresh_table(self):
            try:
                table = self.query_one("#decisions", DataTable)
                table.clear(columns=False)
                for record in self.records:
                    stamp = str(record_value(record, "time", "timestamp", "ts"))[:19]
                    path = decision_path(record)
                    model = str(record_value(record, "upstream_model", "model", "model_used"))[:24]
                    prompt = int(record.get("prompt_tokens", 0) or 0)
                    completion = int(record.get("completion_tokens", 0) or 0)
                    latency = record_value(record, "latency_ms", "turn_latency_ms")
                    try:
                        raw_cost = float(record.get("cost", 0) or 0)
                    except (TypeError, ValueError):
                        raw_cost = 0.0
                    cost = f"${raw_cost:.4f}" if raw_cost > 0 else "Unknown"
                    table.add_row(
                        stamp,
                        path,
                        model,
                        f"{prompt:,}/{completion:,}",
                        cost,
                        str(latency),
                        decision_explanation(record)[:80],
                    )
            except Exception:
                pass

        def _telemetry_cards(self) -> str:
            session = self.snapshot["session"]
            usage = session["usage"]
            evidence = session["evidence"]
            window = self.snapshot["window"]
            window_evidence = self.snapshot["window_evidence"]
            plugin_status = self.snapshot["plugin_status"]

            lines = [
                f"Plugin runtime: [bold]{plugin_status}[/bold]  |  Window (all sessions): [bold]{self.selected_window}[/bold]",
                f"Window completions: [bold]{window['totals']['calls']}[/bold]  |  Cost: {self._cost_label(window['totals'], window_evidence)}",
            ]
            if usage is None:
                lines.extend([
                    "Current session: [bold yellow]Unknown session[/bold yellow]",
                    "Session totals, model mix, and decisions are withheld until a correlated session ID is available.",
                ])
            elif not evidence["has_completions"]:
                lines.extend([
                    f"Current session: [bold]{session['status']}[/bold]",
                    "No persisted completions for this session.",
                ])
            else:
                savings = (
                    f"${usage['estimated_savings_usd']:.4f} ({usage['savings_percentage']:.1f}%)"
                    if evidence["cost_known"]
                    else "Unknown (pricing not evidenced)"
                )
                latency = (
                    f"{usage['avg_latency_ms']:.1f} ms"
                    if evidence["latency_reported"]
                    else "Unknown (not recorded)"
                )
                cache = (
                    f"read {usage['cache_read_tokens']:,} / write {usage['cache_write_tokens']:,}"
                    if evidence["cache_reported"]
                    else "Unknown (not reported)"
                )
                floor = (
                    f"{float(evidence['floor']):.2f}"
                    if evidence["floor"] is not None
                    else "Unknown (not recorded)"
                )
                bias = (
                    f"{float(evidence['bias']):.2f}"
                    if evidence["bias"] is not None
                    else "Unknown (not recorded)"
                )
                oma = self._oma_label(session["oma"])
                projection = (
                    f"${usage['monthly_projected_cost']:.4f}/month"
                    if evidence["cost_known"] and usage["monthly_projected_cost"] > 0
                    else "Unknown (insufficient priced history)"
                )
                lines.extend([
                    f"Current session: [bold]{session['status']}[/bold]  |  Spend: {self._cost_label(usage, evidence)}  |  Savings: {savings}",
                    f"Requests: [bold]{usage['calls']}[/bold]  |  Tokens: [bold]{usage['total_tokens']:,}[/bold]  |  Avg latency: {latency}",
                    f"Cache: {cache}  |  Floor: {floor}  |  Bias: {bias}",
                    f"OMA: {oma}  |  Monthly projection: {projection}",
                ])
            return "\n".join(_format_box_lines("Persisted Session Telemetry", lines, width=104))

        @staticmethod
        def _cost_label(usage: dict[str, Any], evidence: dict[str, Any]) -> str:
            return (
                f"[bold green]${float(usage.get('cost', 0) or 0):.4f}[/bold green]"
                if evidence["cost_known"]
                else "[yellow]Unknown[/yellow]"
            )

        @staticmethod
        def _oma_label(oma: dict[str, Any]) -> str:
            outcomes = oma.get("outcomes", {}) if isinstance(oma, dict) else {}
            return ", ".join(f"{name}={count}" for name, count in sorted(outcomes.items())) or "No outcomes observed"

        def _graph_view(self) -> str:
            try:
                from autoconduck import stats

                active = stats.get_active_routing()
            except Exception:
                active = {"active": False, "path": "FAST", "node": "idle"}

            is_active = active.get("active", False)
            path = active.get("path", "FAST")
            node = active.get("node", "idle")
            detail = active.get("step_detail", "Ready")
            model = active.get("selected_model", "autoconduck")
            val = active.get("task_value", 0.0)
            if is_active:
                lines = [
                    f"Selected model: [bold green]{model}[/bold green]  |  Path: [bold]{path}[/bold]",
                    f"Recorded complexity: [bold]{val:.2f}[/bold]",
                    f"Status: [bold green]{detail}[/bold green]",
                    "This is live router state, not a per-session aggregate.",
                ]
                return "\n".join(
                    _format_box_lines(
                        "[bold green]Live Router Dispatch[/bold green]",
                        lines,
                        width=104,
                    )
                )
            else:
                from autoconduck import __version__
                lines = [
                    f"Engine: [bold]AutoConduck v{__version__}[/bold]",
                    "No active dispatch is persisted.",
                    "Usage below is derived from the durable stats journal.",
                ]
                return "\n".join(
                    _format_box_lines(
                        "[bold dim]Router State[/bold dim]",
                        lines,
                        width=104,
                    )
                )

        def _mascot_header(self):
            status_label = "PAUSED" if self.paused else "RUNNING"
            status_color = "yellow" if self.paused else "green"
            duck = self.DUCK_FRAMES[self.duck_frame]
            return f"{duck} [{status_color}][{status_label}][/{status_color}]\n   \\___)"

        def _stats_summary(self):
            all_time = self.snapshot["all_time"]
            window = self.snapshot["window"]
            session = self.snapshot["session"]
            all_totals = all_time["totals"]
            lines = [
                f"All time (all sessions): {all_totals['calls']} completions  |  {all_totals['total_tokens']:,} tokens",
                f"Selected window (all sessions, {self.selected_window}): {window['totals']['calls']} completions  |  {window['totals']['total_tokens']:,} tokens",
            ]
            if not all_totals["calls"]:
                lines.append("No persisted completions yet.")
            else:
                lines.extend(["-" * 100, "All-time model mix (all sessions):"])
                for model, row in list(all_time["models"].items())[:5]:
                    lines.append(f"{model[:34]:<34} | calls={row['calls']:<5} | tokens={row['total_tokens']:,}")
                path_text = ", ".join(f"{name}={count}" for name, count in sorted(all_time["paths"].items()))
                if path_text:
                    lines.append(f"All-time paths: {path_text}")

            if session["usage"] is None:
                lines.extend([
                    "-" * 100,
                    "Current session: [bold yellow]Unknown session[/bold yellow] — no global decision list is substituted.",
                ])
            elif not session["usage"]["calls"]:
                lines.extend(["-" * 100, f"Current session: {session['status']} — no persisted completions."])
            else:
                session_paths = ", ".join(f"{name}={count}" for name, count in sorted(session["paths"].items()))
                lines.extend([
                    "-" * 100,
                    f"Current session: [bold]{session['status']}[/bold]  |  calls={session['usage']['calls']}  |  tokens={session['usage']['total_tokens']:,}",
                    f"Session paths: {session_paths or 'No paths recorded'}",
                ])
            return "\n".join(_format_box_lines("Verified Usage Aggregates", lines, width=104))

        def on_key(self, event):
            if event.key == "down":
                self.cursor = move_cursor(self.cursor, 1, len(self.records))
                self._refresh_table()
            elif event.key == "up":
                self.cursor = move_cursor(self.cursor, -1, len(self.records))
                self._refresh_table()
            elif event.key in ("left", "escape", "b"):
                self.app.pop_screen()

        def action_pause(self):
            self.paused = not self.paused
            self.query_one("#header").update(self._mascot_header())

        def action_refresh(self):
            self._update_stats()
            self._render_dashboard()

        def action_next_window(self):
            index = DASHBOARD_WINDOWS.index(self.selected_window)
            self.selected_window = DASHBOARD_WINDOWS[(index + 1) % len(DASHBOARD_WINDOWS)]
            self.action_refresh()

        def action_previous_window(self):
            index = DASHBOARD_WINDOWS.index(self.selected_window)
            self.selected_window = DASHBOARD_WINDOWS[(index - 1) % len(DASHBOARD_WINDOWS)]
            self.action_refresh()

        def action_drill(self):
            record = self.records[self.cursor] if self.records else {}
            self.app.push_screen(DrillDownScreen(record))

        def on_data_table_row_selected(self, event):
            try:
                self.cursor = event.cursor_row
                self.action_drill()
            except Exception:
                pass

else:
    class MainMenuScreen(Screen):  # type: ignore
        def __init__(self, *args, **kwargs):
            _require()

    class DashboardScreen(Screen):  # type: ignore
        def __init__(self, *args, **kwargs):
            _require()


__all__ = [
    "MainMenuScreen",
    "DashboardScreen",
    "DrillDownScreen",
    "LaunchAgentScreen",
    "UpdateScreen",
    "UpdateCatalogScreen",
    "move_cursor",
    "render_log_rows",
    "_format_box_lines",
]
