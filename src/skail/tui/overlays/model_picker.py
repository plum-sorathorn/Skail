"""Model picker: configured models only; future attempts only."""

from __future__ import annotations

from typing import Any, cast

try:
    from textual.containers import VerticalScroll
    from textual.screen import Screen
except Exception:  # pragma: no cover
    Screen = object  # type: ignore[assignment,misc]
    VerticalScroll = object  # type: ignore[assignment,misc]

from skail.tui.overlays.shell import OVERLAY_CSS, ovl_foot, ovl_head, ovl_rule_strong

MODEL_FOOT = (
    "Ticked models [x] are enabled for future routing. "
    "Automatic routing still requires trusted capability evidence. "
    "Future attempts only; the active attempt keeps its assigned model."
)
MAX_RENDERED_ROWS = 40


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
    """Enter selects for FUTURE attempts via ``set_future_model``."""

    DEFAULT_CSS = OVERLAY_CSS

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
        for i, name in enumerate(self.models):
            if name == current:
                self.index = i
                break

    def rows(self) -> list[str]:
        if not self.models:
            return ["[dim]No configured models[/dim]"]
        visible = self.visible_models()
        rows = model_rows(visible, self.current, self.enabled, self.index)
        return [f"{row}{self._detail_suffix(name)}" for row, name in zip(rows, visible)]

    def visible_models(self) -> list[str]:
        needle = self.filter_text.strip().lower()
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
            self.window_start = min(
                max(0, self.index - MAX_RENDERED_ROWS + 1),
                max(0, len(visible) - MAX_RENDERED_ROWS),
            )

    def toggle_tick(self) -> None:
        """Toggle tick for the currently highlighted model."""
        visible = self.visible_models()
        if visible:
            target = visible[self.index % len(visible)]
            if target in self.enabled:
                self.enabled.remove(target)
            else:
                self.enabled.add(target)

    def toggle_all(self) -> None:
        """Toggle all models between enabled and disabled."""
        visible = self.visible_models()
        if visible:
            if set(visible).issubset(self.enabled):
                self.enabled.difference_update(visible)
            else:
                self.enabled.update(visible)

    def commit(self) -> str | None:
        """Select for future attempts; never mutates the active attempt."""
        if not self.models:
            return None
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

            container = self.query_one("#model-list", VerticalScroll)
            visible = self.visible_models()
            if not force and visible == self._rendered_models:
                return
            new_rows = self.rows()[
                self.window_start : self.window_start + MAX_RENDERED_ROWS
            ]
            row_widgets = cast(list[Static], list(container.query(".model-row")))
            content = Text("\n".join(new_rows))
            if row_widgets:
                row_widgets[0].update(content)
            else:
                container.mount(Static(content, classes="model-row", id="model-row-0"))
            self._rendered_models = visible
        except Exception:
            pass

    def compose(self) -> Any:
        try:
            from rich.text import Text
            from textual.widgets import Input, Static

            yield ovl_head(
                "MODEL SELECTION",
                hint="space: tick \u00b7 a: all \u00b7 enter: select \u00b7 esc closes",
            )

            yield ovl_rule_strong()
            yield Input(placeholder="Filter model or provider", id="model-search")
            with VerticalScroll(id="model-list"):
                yield Static(
                    Text("\n".join(self.rows()[:MAX_RENDERED_ROWS])),
                    classes="model-row",
                    id="model-row-0",
                )
            yield ovl_foot(MODEL_FOOT)
        except Exception:
            return
            yield  # pragma: no cover

    async def on_key(self, event: Any) -> None:
        key = getattr(event, "key", "")
        if key == "escape":
            self.cancel()
            try:
                event.stop()
            except Exception:
                pass
        elif key == "enter":
            self.commit()
            try:
                event.stop()
            except Exception:
                pass
        elif key in ("up", "down", "k", "j"):
            self.move(-1 if key in ("up", "k") else 1)
            self._refresh_rows(force=True)
            try:
                event.stop()
            except Exception:
                pass
        elif key == "space":
            self.toggle_tick()
            self._refresh_rows(force=True)
            try:
                event.stop()
            except Exception:
                pass
        elif key == "a":
            self.toggle_all()
            self._refresh_rows(force=True)
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
        if len(self.filter_text) < 3:
            return
        self._refresh_rows()

    def on_mount(self) -> None:
        self._rendered_models = self.visible_models()


__all__ = ["MAX_RENDERED_ROWS", "MODEL_FOOT", "ModelPickerOverlay", "model_rows"]
