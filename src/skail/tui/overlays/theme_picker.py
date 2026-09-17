"""Theme picker: Dark/Light/System with live preview and Esc-restore."""

from __future__ import annotations

from typing import Any

try:
    from textual.screen import Screen
except Exception:  # pragma: no cover
    Screen = object  # type: ignore[assignment,misc]

from skail.tui.theme import ThemeName, resolve_system_theme


def _app_for(host: object) -> Any:
    test_app = getattr(host, "_test_app", None)
    if test_app is not None:
        return test_app
    try:
        return getattr(host, "app", None)
    except Exception:
        return None


THEME_OPTIONS: tuple[str, ...] = ("Dark", "Light", "System")
SYSTEM_FALLBACK_NOTE = "System preference unavailable; using Dark."


def theme_rows(current: str) -> list[str]:
    """Return option rows with ● marking the current theme."""
    rows: list[str] = []
    for option in THEME_OPTIONS:
        marker = "\u25cf" if option.lower() == current.strip().lower() else " "
        rows.append(f"{marker} {option}")
    return rows


def resolve_system_note(detected: str | None) -> tuple[str, str]:
    """Resolve system theme; note when falling back to Dark."""
    tokens, detail = resolve_system_theme(detected)
    _ = tokens
    if detected is None or detected.strip().lower() not in ("dark", "light"):
        return "Dark", SYSTEM_FALLBACK_NOTE
    return ("Light" if (detected or "").strip().lower() == "light" else "Dark", detail)


class ThemePickerOverlay(Screen):  # type: ignore[type-arg]
    """List Dark/Light/System; preview on move, commit on Enter."""

    def __init__(self, current: str = "dark", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.current = current
        self.previous = current
        self.index = 0
        for i, option in enumerate(THEME_OPTIONS):
            if option.lower() == current.strip().lower():
                self.index = i
                break

    def rows(self) -> list[str]:
        opts = [o.lower() for o in THEME_OPTIONS]
        cur = THEME_OPTIONS[self.index].lower() if self.index < len(opts) else self.current
        _ = opts
        out: list[str] = []
        for option in THEME_OPTIONS:
            marker = "\u25cf" if option.lower() == cur else " "
            out.append(f"{marker} {option}")
        return out

    def move(self, delta: int) -> str:
        """Move selection and live-preview via ``apply_theme_preview``."""
        self.index = (self.index + delta) % len(THEME_OPTIONS)
        name = THEME_OPTIONS[self.index].lower()
        try:
            app = _app_for(self)
            if app is not None and hasattr(app, "apply_theme_preview"):
                app.apply_theme_preview(name)
        except Exception:
            pass
        return name

    def commit(self) -> str:
        name = THEME_OPTIONS[self.index].lower()
        try:
            app = _app_for(self)
            if app is not None and hasattr(app, "apply_theme_preview"):
                app.apply_theme_preview(name)
        except Exception:
            pass
        self.current = name
        self.previous = name
        try:
            app = _app_for(self)
            if app is not None and hasattr(app, "close_overlay"):
                app.close_overlay("theme_picker")
        except Exception:
            pass
        return name

    def cancel(self) -> str:
        """Esc restores the previous theme."""
        previous: ThemeName = self.previous.lower()  # type: ignore[assignment]
        try:
            app = _app_for(self)
            if app is not None and hasattr(app, "apply_theme_preview"):
                app.apply_theme_preview(previous)
            if app is not None and hasattr(app, "close_overlay"):
                app.close_overlay("theme_picker")
        except Exception:
            pass
        return str(previous)

    def compose(self) -> Any:
        try:
            from textual.widgets import Static

            yield Static("THEME")
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


__all__ = [
    "SYSTEM_FALLBACK_NOTE",
    "THEME_OPTIONS",
    "ThemePickerOverlay",
    "resolve_system_note",
    "theme_rows",
]
