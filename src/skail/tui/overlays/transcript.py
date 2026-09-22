"""Full-area transcript overlay reusing ChatTranscript."""

from __future__ import annotations

from typing import Any

try:
    from textual.screen import Screen
except Exception:  # pragma: no cover - stub fallback for headless tests
    Screen = object  # type: ignore[assignment,misc]

from skail.tui.overlays.shell import OVERLAY_CSS, ovl_foot, ovl_head, ovl_rule_strong
from skail.tui.projection import TranscriptItem
from skail.tui.widgets.chat import (
    ChatTranscript,
    export_transcript_text,
    filter_transcript,
)

NATIVE_SCROLLBACK_UNAVAILABLE = (
    "Native scrollback is unavailable in this terminal; "
    "opened the system pager instead."
)
RETURN_PROMPT = "Press Enter to return to Skail."
TRANSCRIPT_FOOT = (
    "Read-only \u00b7 ctrl+shift+o pages when native scrollback is unavailable."
)


def _app_for(host: object) -> Any:
    """Return the bound app, preferring the injected test double."""
    test_app = getattr(host, "_test_app", None)
    if test_app is not None:
        return test_app
    try:
        return getattr(host, "app", None)
    except Exception:
        return None
def transcript_search(items: list[TranscriptItem], query: str) -> list[TranscriptItem]:
    """Search hook: case-insensitive filter over title+content."""
    return filter_transcript(items, query)


def transcript_plain_text(items: list[TranscriptItem]) -> str:
    """Plain-text export via ``export_transcript_text``."""
    return export_transcript_text(items)


class TranscriptOverlay(Screen):  # type: ignore[type-arg]
    """Full-area transcript; Esc/Ctrl+O closes, Ctrl+Shift+O pagers."""

    DEFAULT_CSS = OVERLAY_CSS

    def __init__(
        self,
        items: list[TranscriptItem] | None = None,
        scroll_y: int = 0,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.overlay_items: list[TranscriptItem] = list(items or [])
        self.saved_scroll_y = int(scroll_y)
        self.query_text = ""
        self.filtered: list[TranscriptItem] = list(self.overlay_items)
        self.match_index = 0

    def set_query(self, query: str) -> list[TranscriptItem]:
        self.query_text = query
        self.filtered = transcript_search(self.overlay_items, query)
        self.match_index = 0
        return self.filtered

    def next_match(self) -> TranscriptItem | None:
        if not self.filtered:
            return None
        self.match_index = (self.match_index + 1) % len(self.filtered)
        return self.filtered[self.match_index]

    def prev_match(self) -> TranscriptItem | None:
        if not self.filtered:
            return None
        self.match_index = (self.match_index - 1) % len(self.filtered)
        return self.filtered[self.match_index]

    def export_text(self) -> str:
        return transcript_plain_text(self.overlay_items)

    def pager_payload(self) -> tuple[str, str, str]:
        """Return (plain_text, fallback_message, prompt) for suspend/pager."""
        return (self.export_text(), NATIVE_SCROLLBACK_UNAVAILABLE, RETURN_PROMPT)

    def close(self) -> int:
        """Close hook returning the scroll position to restore."""
        try:
            app = _app_for(self)
            if app is not None and hasattr(app, "close_overlay"):
                app.close_overlay("transcript")
        except Exception:
            pass
        return self.saved_scroll_y

    def compose(self) -> Any:
        try:
            transcript = ChatTranscript(id="transcript-full")
            transcript.update_items(self.overlay_items)
            try:
                transcript.scroll_y = self.saved_scroll_y
            except Exception:
                pass
            yield ovl_head("TRANSCRIPT", hint="esc closes \u00b7 ctrl+shift+o pager")
            yield ovl_rule_strong()
            yield transcript
            yield ovl_foot(TRANSCRIPT_FOOT)
        except Exception:
            return
            yield  # pragma: no cover - make this a generator

    async def on_key(self, event: Any) -> None:
        key = getattr(event, "key", "")
        if key in ("escape", "ctrl+o"):
            self.close()
            try:
                event.stop()
            except Exception:
                pass
        elif key == "ctrl+shift+o":
            try:
                app = _app_for(self)
                if app is not None and hasattr(app, "open_system_pager"):
                    app.open_system_pager(self.export_text())
            except Exception:
                pass
            try:
                event.stop()
            except Exception:
                pass
        elif key == "/":
            pass
        elif key in ("n", "N"):
            pass


__all__ = [
    "NATIVE_SCROLLBACK_UNAVAILABLE",
    "RETURN_PROMPT",
    "TRANSCRIPT_FOOT",
    "TranscriptOverlay",
    "transcript_plain_text",
    "transcript_search",
]
