"""Keyboard-only model picker with a bounded, non-scrollable viewport."""

from __future__ import annotations

from typing import Any

try:
    from textual.binding import Binding
    from textual.screen import Screen
except Exception:  # pragma: no cover
    Screen = object  # type: ignore[assignment,misc]

from skail.tui.overlays.shell import OVERLAY_CSS, ovl_foot, ovl_head, ovl_rule_strong

MODEL_FOOT = (
    "Ticked models [x] are enabled for future routing. "
    "Automatic routing still requires trusted capability evidence. "
    "Future attempts only; the active attempt keeps its assigned model."
)
DEFAULT_VIEWPORT_ROWS = 8


def _app_for(host: object) -> Any:
    test_app = getattr(host, "_test_app", None)
    if test_app is not None:
        return test_app
    try:
        return getattr(host, "app", None)
    except Exception:
        return None


def model_rows(
    models: list[str],
    current: str,
    enabled: set[str] | None = None,
    index: int = 0,
) -> list[str]:
    rows: list[str] = []
    en = set(models) if enabled is None else enabled
    for i, name in enumerate(models):
        cursor = "\u25cf" if i == index else " "
        check = "[x]" if name in en else "[ ]"
        lead_tag = " (lead)" if name == current else ""
        rows.append(f"{cursor} {check} {name}{lead_tag}")
    return rows


class ModelPickerOverlay(Screen):  # type: ignore[type-arg]
    """Keep the filter focused while typing, navigating, toggling, and selecting."""

    DEFAULT_CSS = OVERLAY_CSS
    BINDINGS = [
        Binding("ctrl+space", "toggle_selected", show=False, priority=True),
        Binding("ctrl+shift+a", "toggle_filtered", show=False, priority=True),
    ]

    def __init__(
        self,
        models: list[str] | None = None,
        current: str = "auto",
        enabled: set[str] | list[str] | None = None,
        details: dict[str, dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.models: list[str] = list(models or [])
        self.current = current
        self.enabled: set[str] = set(self.models) if enabled is None else set(enabled)
        self.details = dict(details or {})
        self.filter_text = ""
        self._rendered_models: list[str] = []
        self.window_start = 0
        self.index = 0
        self.viewport_rows = DEFAULT_VIEWPORT_ROWS
        for i, name in enumerate(self.models):
            if name == current:
                self.index = i
                break

    def rows(self) -> list[str]:
        if not self.models:
            return ["[dim]No configured models[/dim]"]
        visible = self.visible_models()
        return [
            f"{row}{self._detail_suffix(name)}"
            for row, name in zip(
                model_rows(visible, self.current, self.enabled, self.index), visible
            )
        ]

    def visible_models(self) -> list[str]:
        needle = self.filter_text.lower()
        if not needle:
            return list(self.models)
        return [
            name
            for name in self.models
            if needle in name.lower()
            or needle in self.details.get(name, {}).get("provider", "").lower()
        ]

    def _detail_suffix(self, name: str) -> str:
        detail = self.details.get(name, {})
        labels = [
            value
            for key in ("routing", "input", "output", "context", "capabilities")
            if (value := detail.get(key))
        ]
        return f"  ·  {' · '.join(labels)}" if labels else ""

    def move(self, delta: int) -> None:
        visible = self.visible_models()
        if visible:
            self.index = (self.index + delta) % len(visible)
            self._ensure_highlight_visible(len(visible))

    def _ensure_highlight_visible(self, visible_count: int) -> None:
        if self.index < self.window_start:
            self.window_start = self.index
        elif self.index >= self.window_start + self.viewport_rows:
            self.window_start = self.index - self.viewport_rows + 1
        self.window_start = min(
            max(0, self.window_start),
            max(0, visible_count - self.viewport_rows),
        )

    def toggle_tick(self) -> None:
        visible = self.visible_models()
        if visible:
            target = visible[self.index % len(visible)]
            if target in self.enabled:
                self.enabled.remove(target)
            else:
                self.enabled.add(target)

    def toggle_all(self) -> None:
        visible = self.visible_models()
        if visible:
            if set(visible).issubset(self.enabled):
                self.enabled.difference_update(visible)
            else:
                self.enabled.update(visible)

    def action_toggle_selected(self) -> None:
        self.toggle_tick()
        self._refresh_rows(force=True)

    def action_toggle_filtered(self) -> None:
        self.toggle_all()
        self._refresh_rows(force=True)

    def key_ctrl_space(self, event: Any) -> None:
        self.action_toggle_selected()
        event.stop()

    def key_ctrl_at(self, event: Any) -> None:
        self.action_toggle_selected()
        event.stop()

    def key_ctrl_shift_a(self, event: Any) -> None:
        self.action_toggle_filtered()
        event.stop()

    def commit(self) -> str | None:
        visible = self.visible_models()
        if not visible:
            return None
        name = visible[self.index % len(visible)]
        try:
            app = _app_for(self)
            if app is not None:
                if hasattr(app, "set_future_model"):
                    app.set_future_model(name)
                if hasattr(app, "set_enabled_models"):
                    app.set_enabled_models(list(self.enabled))
                if hasattr(app, "close_overlay"):
                    app.close_overlay("model_picker")
        except Exception:
            pass
        self.current = name
        return name

    def cancel(self) -> None:
        try:
            app = _app_for(self)
            if app is not None and hasattr(app, "close_overlay"):
                app.close_overlay("model_picker")
        except Exception:
            pass

    def _refresh_rows(self, *, force: bool = False) -> None:
        try:
            from rich.text import Text
            from textual.widgets import Static

            visible = self.visible_models()
            if not force and visible == self._rendered_models:
                return
            self._ensure_highlight_visible(len(visible))
            if not self.models:
                lines = self.rows()
            elif not visible:
                lines = ["[dim]No matching models[/dim]"]
            else:
                rows = self.rows()[
                    self.window_start : self.window_start + self.viewport_rows
                ]
                hidden_above = f"↑ {self.window_start} more" if self.window_start else ""
                hidden_count = max(0, len(visible) - self.window_start - len(rows))
                hidden_below = f"↓ {hidden_count} more" if hidden_count else ""
                lines = [line for line in (hidden_above, *rows, hidden_below) if line]
            self.query_one("#model-list", Static).update(Text("\n".join(lines)))
            self._rendered_models = visible
        except Exception:
            pass

    def compose(self) -> Any:
        try:
            from rich.text import Text
            from textual.widgets import Input, Static

            class FilterInput(Input):
                async def _on_key(self, event: Any) -> None:
                    key = getattr(event, "key", "")
                    screen = getattr(self, "screen", None)
                    if key in ("ctrl+space", "ctrl+@") and screen is not None:
                        screen.action_toggle_selected()
                        event.stop()
                        event.prevent_default()
                        return
                    if key in ("ctrl+a", "ctrl+shift+a", "ctrl+shift+at") and screen is not None:
                        screen.action_toggle_filtered()
                        event.stop()
                        event.prevent_default()
                        return
                    await super()._on_key(event)

            yield ovl_head(
                "MODEL SELECTION",
                hint="↑/↓ move · ctrl+space tick · ctrl+shift+a all · enter select · esc closes",
            )
            yield ovl_rule_strong()
            yield FilterInput(placeholder="Filter model or provider", id="model-search")
            yield Static(Text("\n".join(self.rows())), id="model-list", classes="model-row")
            yield ovl_foot(MODEL_FOOT)
        except Exception:
            return
            yield  # pragma: no cover

    async def on_key(self, event: Any) -> None:
        key = getattr(event, "key", "")
        if key == "escape":
            self.cancel()
        elif key == "enter":
            self.commit()
        elif key in ("up", "down"):
            self.move(-1 if key == "up" else 1)
            self._refresh_rows(force=True)
        elif key in ("ctrl+space", "ctrl+@"):
            self.toggle_tick()
            self._refresh_rows(force=True)
        elif key in ("ctrl+a", "ctrl+shift+a", "ctrl+shift+at"):
            self.toggle_all()
            self._refresh_rows(force=True)
        else:
            return
        try:
            event.stop()
        except Exception:
            pass

    def on_input_changed(self, event: Any) -> None:
        if getattr(event.input, "id", None) != "model-search":
            return
        self.filter_text = str(event.value)
        self.index = 0
        self.window_start = 0
        self._refresh_rows(force=True)

    def on_mount(self) -> None:
        self._rendered_models = self.visible_models()
        try:
            self.viewport_rows = max(1, self.size.height - 7)
            self.query_one("#model-search").focus()
            self._refresh_rows(force=True)
        except Exception:
            pass

    def on_resize(self, event: Any) -> None:
        self.viewport_rows = max(1, event.size.height - 7)
        self._refresh_rows(force=True)


__all__ = ["DEFAULT_VIEWPORT_ROWS", "MODEL_FOOT", "ModelPickerOverlay", "model_rows"]
