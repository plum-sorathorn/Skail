"""Model picker: configured models only; future attempts only."""

from __future__ import annotations

from typing import Any

try:
    from textual.screen import Screen
except Exception:  # pragma: no cover
    Screen = object  # type: ignore[assignment,misc]


def _app_for(host: object) -> Any:
    test_app = getattr(host, "_test_app", None)
    if test_app is not None:
        return test_app
    try:
        return getattr(host, "app", None)
    except Exception:
        return None


def model_rows(models: list[str], current: str) -> list[str]:
    rows: list[str] = []
    for name in models:
        marker = "\u25cf" if name == current else " "
        rows.append(f"{marker} {name}")
    return rows


class ModelPickerOverlay(Screen):  # type: ignore[misc]
    """Enter selects for FUTURE attempts via ``set_future_model``."""

    def __init__(
        self,
        models: list[str] | None = None,
        current: str = "auto",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[call-arg]
        self.models: list[str] = list(models or [])
        self.current = current
        self.index = 0
        for i, name in enumerate(self.models):
            if name == current:
                self.index = i
                break

    def rows(self) -> list[str]:
        if not self.models:
            return ["[dim]No configured models[/dim]"]
        out: list[str] = []
        for i, name in enumerate(self.models):
            marker = "\u25cf" if i == self.index else " "
            out.append(f"{marker} {name}")
        return out

    def move(self, delta: int) -> None:
        if self.models:
            self.index = (self.index + delta) % len(self.models)

    def commit(self) -> str | None:
        """Select for future attempts; never mutates the active attempt."""
        if not self.models:
            return None
        name = self.models[self.index % len(self.models)]
        try:
            app = _app_for(self)
            if app is not None and hasattr(app, "set_future_model"):
                app.set_future_model(name)
        except Exception:
            pass
        self.current = name
        try:
            app = _app_for(self)
            if app is not None and hasattr(app, "close_overlay"):
                app.close_overlay("model_picker")
        except Exception:
            pass
        return name

    def cancel(self) -> None:
        try:
            app = _app_for(self)
            if app is not None and hasattr(app, "close_overlay"):
                app.close_overlay("model_picker")
        except Exception:
            pass

    def compose(self) -> Any:
        try:
            from textual.widgets import Static

            yield Static("MODEL (future attempts only)")
            for row in self.rows():
                yield Static(row)
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
        elif key in ("up", "down"):
            self.move(-1 if key == "up" else 1)
            try:
                event.stop()
            except Exception:
                pass


__all__ = ["ModelPickerOverlay", "model_rows"]
