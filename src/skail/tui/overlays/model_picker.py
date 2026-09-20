"""Model picker: configured models only; future attempts only."""

from __future__ import annotations

from typing import Any

try:
    from textual.screen import Screen
except Exception:  # pragma: no cover
    Screen = object  # type: ignore[assignment,misc]

from skail.tui.overlays.shell import OVERLAY_CSS, ovl_foot, ovl_head, ovl_rule_strong

MODEL_FOOT = (
    "Ticked models [x] are eligible for automatic routing. "
    "Future attempts only; the active attempt keeps its assigned model."
)


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
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.models: list[str] = list(models or [])
        self.current = current
        self.enabled: set[str] = set(self.models) if enabled is None else set(enabled)
        self.index = 0
        for i, name in enumerate(self.models):
            if name == current:
                self.index = i
                break

    def rows(self) -> list[str]:
        if not self.models:
            return ["[dim]No configured models[/dim]"]
        return model_rows(self.models, self.current, self.enabled, self.index)

    def move(self, delta: int) -> None:
        if self.models:
            self.index = (self.index + delta) % len(self.models)

    def toggle_tick(self) -> None:
        """Toggle tick for the currently highlighted model."""
        if self.models:
            target = self.models[self.index % len(self.models)]
            if target in self.enabled:
                self.enabled.remove(target)
            else:
                self.enabled.add(target)

    def toggle_all(self) -> None:
        """Toggle all models between enabled and disabled."""
        if self.models:
            if self.enabled == set(self.models):
                self.enabled.clear()
            else:
                self.enabled = set(self.models)

    def commit(self) -> str | None:
        """Select for future attempts; never mutates the active attempt."""
        if not self.models:
            return None
        name = self.models[self.index % len(self.models)]
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

    def _refresh_rows(self) -> None:
        try:
            row_widgets = list(self.query(".model-row"))
            new_rows = self.rows()
            for widget, text in zip(row_widgets, new_rows):
                if hasattr(widget, "update"):
                    widget.update(text)
        except Exception:
            pass

    def compose(self) -> Any:
        try:
            from textual.widgets import Static

            yield ovl_head(
                "MODEL SELECTION",
                hint="space: tick \u00b7 a: all \u00b7 enter: select \u00b7 esc closes",
            )

            yield ovl_rule_strong()
            for i, row in enumerate(self.rows()):
                yield Static(row, classes="model-row", id=f"model-row-{i}")
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
            self._refresh_rows()
            try:
                event.stop()
            except Exception:
                pass
        elif key == "space":
            self.toggle_tick()
            self._refresh_rows()
            try:
                event.stop()
            except Exception:
                pass
        elif key == "a":
            self.toggle_all()
            self._refresh_rows()
            try:
                event.stop()
            except Exception:
                pass


__all__ = ["MODEL_FOOT", "ModelPickerOverlay", "model_rows"]
