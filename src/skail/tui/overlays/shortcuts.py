"""Shortcuts overlay: grouped bindings with type-to-filter."""

from __future__ import annotations

from typing import Any

try:
    from textual.screen import Screen
except Exception:  # pragma: no cover
    Screen = object  # type: ignore[assignment,misc]

GROUP_ORDER = (
    "Run",
    "Composer",
    "Navigation",
    "Agents",
    "Approvals",
    "Session",
    "Display",
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


class ShortcutsOverlay(Screen):  # type: ignore[type-arg]
    """Shortcuts pane; Esc closes; never injects a transcript event."""

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
            from textual.widgets import Input, Static

            yield Input(placeholder="Filter shortcuts", id="shortcuts-filter")
            for line in self.lines():
                yield Static(line)
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
    "ShortcutsOverlay",
    "filter_shortcuts",
    "group_shortcuts",
    "render_shortcut_lines",
]
