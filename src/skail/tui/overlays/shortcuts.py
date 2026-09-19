"""Shortcuts overlay: grouped bindings with type-to-filter.

The composed view is the ATELIER 36/1/36 two-column kbd/desc grid fed from the
same grouped registry. Rendering ALL ``ACTION_REGISTRY`` groups is a documented
superset of the mock's shortcut rows.
"""

from __future__ import annotations

from typing import Any

try:
    from textual.screen import Screen
except Exception:  # pragma: no cover
    Screen = object  # type: ignore[assignment,misc]

from skail.tui.overlays.shell import OVERLAY_CSS, ovl_foot, ovl_head, ovl_rule_strong
from skail.tui.widgets.plan import section_head

GROUP_ORDER = (
    "Run",
    "Composer",
    "Navigation",
    "Agents",
    "Approvals",
    "Session",
    "Display",
)

GRID_LEFT_GROUPS: tuple[str, ...] = GROUP_ORDER[:3]
GRID_RIGHT_GROUPS: tuple[str, ...] = GROUP_ORDER[3:]

SHORTCUTS_FOOT = (
    "focus ring = $focusRing token \u00b7 status is never colour-only (glyph + word)"
)


def _app_for(host: object) -> Any:
    test_app = getattr(host, "_test_app", None)
    if test_app is not None:
        return test_app
    try:
        return getattr(host, "app", None)
    except Exception:
        return None


def group_shortcuts(
    registry: dict[str, dict[str, str]],
) -> dict[str, list[tuple[str, str, str]]]:
    """Group ACTION_REGISTRY entries: {group: [(action, binding, desc)]}."""
    grouped: dict[str, list[tuple[str, str, str]]] = {g: [] for g in GROUP_ORDER}
    for action in sorted(registry):
        entry = registry[action]
        group = str(entry.get("group", "Session"))
        binding = str(entry.get("binding", ""))
        desc = str(entry.get("description", ""))
        if group not in grouped:
            grouped[group] = []
        grouped[group].append((action, binding, desc))
    return grouped


def filter_shortcuts(
    grouped: dict[str, list[tuple[str, str, str]]], query: str
) -> dict[str, list[tuple[str, str, str]]]:
    """Type-to-filter over action/binding/description."""
    needle = query.strip().lower()
    if not needle:
        return grouped
    out: dict[str, list[tuple[str, str, str]]] = {}
    for group, rows in grouped.items():
        kept = [
            r
            for r in rows
            if needle in r[0].lower() or needle in r[1].lower() or needle in r[2].lower()
        ]
        if kept:
            out[group] = kept
    return out


def render_shortcut_lines(
    registry: dict[str, dict[str, str]], query: str = ""
) -> list[str]:
    lines: list[str] = ["SHORTCUTS"]
    grouped = filter_shortcuts(group_shortcuts(registry), query)
    for group in GROUP_ORDER:
        rows = grouped.get(group, [])
        if not rows:
            continue
        lines.append(f"== {group} ==")
        for action, binding, desc in rows:
            lines.append(f"{binding}  {desc} ({action})")
    for group, rows in grouped.items():
        if group in GROUP_ORDER:
            continue
        lines.append(f"== {group} ==")
        for action, binding, desc in rows:
            lines.append(f"{binding}  {desc} ({action})")
    return lines


def shortcut_grid_columns(
    registry: dict[str, dict[str, str]], query: str = ""
) -> tuple[list[str], list[str]]:
    """Markup rows for the 36/1/36 two-column kbd/desc grid: (left, right).

    Left column: Run/Composer/Navigation; right: Agents/Approvals/Session/Display
    plus any extra registry groups. Rows are ``[on $surfaceRaised] binding [/]  desc``
    under letterspaced hairline group heads; the focused filter applies as usual.
    """
    grouped = filter_shortcuts(group_shortcuts(registry), query)

    def column(groups: tuple[str, ...]) -> list[str]:
        lines: list[str] = []
        for group in groups:
            rows = grouped.get(group, [])
            if not rows:
                continue
            lines.append(section_head(group.upper()))
            for _action, binding, desc in rows:
                lines.append(f"[on $surfaceRaised] {binding} [/]  {desc}")
        return lines

    extra = [group for group in grouped if group not in GROUP_ORDER]
    return column(GRID_LEFT_GROUPS), column((*GRID_RIGHT_GROUPS, *extra))


class ShortcutsOverlay(Screen):  # type: ignore[type-arg]
    """Shortcuts pane; Esc closes; never injects a transcript event."""

    DEFAULT_CSS = OVERLAY_CSS

    def __init__(self, registry: dict[str, dict[str, str]] | None = None, **kw: Any) -> None:
        super().__init__(**kw)
        self.registry = dict(registry or {})
        self.filter_query = ""

    def set_filter(self, query: str) -> list[str]:
        self.filter_query = query
        return render_shortcut_lines(self.registry, query)

    def lines(self) -> list[str]:
        return render_shortcut_lines(self.registry, self.filter_query)

    def close(self) -> None:
        try:
            app = _app_for(self)
            if app is not None and hasattr(app, "close_overlay"):
                app.close_overlay("shortcuts")
        except Exception:
            pass

    def compose(self) -> Any:
        try:
            from textual.containers import Horizontal, Vertical
            from textual.widgets import Input, Static

            left, right = shortcut_grid_columns(self.registry, self.filter_query)
            yield ovl_head("SHORTCUTS", hint="esc closes")
            yield ovl_rule_strong()
            yield Input(placeholder="Filter shortcuts", id="shortcuts-filter")
            with Horizontal(classes="ovl-grid"):
                with Vertical(classes="ovl-col"):
                    for line in left:
                        yield Static(line)
                yield Static("", id="hairline", classes="hairline")
                with Vertical(classes="ovl-col"):
                    for line in right:
                        yield Static(line)
            yield ovl_foot(SHORTCUTS_FOOT)
        except Exception:
            return
            yield  # pragma: no cover

    async def on_key(self, event: Any) -> None:
        if getattr(event, "key", "") == "escape":
            self.close()
            try:
                event.stop()
            except Exception:
                pass


__all__ = [
    "SHORTCUTS_FOOT",
    "ShortcutsOverlay",
    "filter_shortcuts",
    "group_shortcuts",
    "render_shortcut_lines",
    "shortcut_grid_columns",
]
