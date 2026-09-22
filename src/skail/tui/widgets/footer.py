"""ATELIER footer: keybinding hints row for SkailApp.

Design: design/tui-redesigns/atelier (redesign-1, row 50). The app derives
(key, label) pairs from its own BINDINGS and passes them in; the widget never
hard-codes keys. Markup uses bare theme token tags (rich 15 rejects ``$`` in
markup); the ``.kbd`` chip rule in TCSS records the chip styling (no border
or radius).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Static

WIDE_HINT_COUNT = 8
NARROW_HINT_COUNT = 4

_MORE_INDICATOR = "⋯"
_ALL_SHORTCUTS = "? all shortcuts"
_ALL_SHORTCUTS_NARROW = "? all"


def format_footer_hints(
    pairs: Sequence[tuple[str, str]], *, narrow: bool = False
) -> tuple[str, str]:
    """Return (hints markup, shortcuts hint) for one ATELIER footer row.

    Wide shows up to 8 ``<kbd> key </kbd> label`` hints joined by `` · ``,
    narrow only 4; both end with a more indicator (``⋯``) plus the shortcuts
    hint, shortened when narrow.
    """
    limit = NARROW_HINT_COUNT if narrow else WIDE_HINT_COUNT
    parts = [
        f"[surfaceRaised][text] {key} [/][/] {label}" for key, label in pairs[:limit]
    ]
    parts.append(_MORE_INDICATOR)
    hints = f"[textMuted]{' · '.join(parts)}[/]"
    shortcuts = _ALL_SHORTCUTS_NARROW if narrow else _ALL_SHORTCUTS
    return hints, f"[textMuted]{shortcuts}[/]"


class AtelierFooter(Horizontal):
    """ATELIER footer: one row of keybinding hints, more indicator, shortcuts."""

    DEFAULT_CSS = """
    AtelierFooter {
        width: 100%;
        height: 1;
        background: $surface;
        color: $textMuted;
        padding: 0 1;
    }
    #app-footer .kbd {
        background: $surfaceRaised;
        color: $text;
    }
    #app-footer-hints {
        width: 1fr;
        height: 1;
    }
    #app-footer-shortcuts {
        width: auto;
        height: 1;
    }
    """

    narrow: reactive[bool] = reactive(False)

    def __init__(
        self, pairs: Sequence[tuple[str, str]] | None = None, **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self._pairs: list[tuple[str, str]] = list(pairs) if pairs is not None else []

    def compose(self) -> ComposeResult:
        hints, shortcuts = format_footer_hints(self._pairs, narrow=self.narrow)
        yield Static(hints, id="app-footer-hints")
        yield Static(shortcuts, id="app-footer-shortcuts")

    def set_bindings(self, pairs: Sequence[tuple[str, str]]) -> None:
        """Replace the (key, label) pairs; the app derives them, never this widget."""
        self._pairs = list(pairs)
        self._refresh_hints()

    def watch_narrow(self, narrow: bool) -> None:
        """Re-render hints and the shortened shortcuts hint when the app goes narrow."""
        _ = narrow
        self._refresh_hints()

    def _refresh_hints(self) -> None:
        if not self.is_mounted:
            return
        hints, shortcuts = format_footer_hints(self._pairs, narrow=self.narrow)
        try:
            self.query_one("#app-footer-hints", Static).update(hints)
            self.query_one("#app-footer-shortcuts", Static).update(shortcuts)
        except Exception:
            return
