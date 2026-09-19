"""Multiline composer with queue, history, stash, and ghost slash palette.

Draft source: docs/skail/TUI_REVAMP_DRAFT.md section 5.3.
Phase 2: multiline 3-8 rows, exact placeholder/validating copy, char count,
mode corner, Enter/Shift+Enter/Ctrl+Enter/Tab/Esc, FIFO queue-above view,
history with edit-recall, Ctrl+S stash receipt, deterministic fuzzy palette.
Slash parsing/dispatch stays in ``skail.tui.commands``; this module only
matches and completes. No hardcoded hex values; styling uses theme tokens.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Static, TextArea

COMPOSER_PLACEHOLDER = "Message Skail\u2026"
COMPOSER_VALIDATING_TEXT = "Validating provider\u2026"
STASH_RECEIPT = "Draft stashed. Press Up on an empty composer to restore it."
MAX_PALETTE_ROWS = 6
MIN_COMPOSER_ROWS = 3
MAX_COMPOSER_ROWS = 8


@dataclass
class PaletteMatch:
    """One deterministic fuzzy palette match."""

    command: str
    description: str = ""
    rank: int = 0


@dataclass
class ComposerState:
    """Minimal widget state machine for Enter/send decisions."""

    draft: str = ""
    palette_open: bool = False
    palette_selection: int = 0
    validating: bool = False
    active_run: bool = False


def _normalize_query(query: str) -> str:
    text = query.strip().lower()
    if text.startswith("/"):
        text = text[1:]
    return text.split()[0] if text else ""


def _is_subsequence(needle: str, haystack: str) -> bool:
    if not needle:
        return True
    pos = 0
    for char in haystack:
        if char == needle[pos]:
            pos += 1
            if pos == len(needle):
                return True
    return False


def fuzzy_match_commands(
    query: str,
    candidates: list[str] | list[PaletteMatch] | tuple[str, ...],
    descriptions: dict[str, str] | None = None,
    keywords: dict[str, list[str]] | None = None,
) -> list[PaletteMatch]:
    """Deterministic fuzzy match: prefix > subsequence > desc/kw > alpha.

    Accepts plain command names (``/help`` style without the slash) or
    ``PaletteMatch`` entries. Tiebreak is alphabetical, then registry order,
    so repeated calls with the same input always agree.
    """
    needle = _normalize_query(query)
    registry: list[PaletteMatch] = []
    for index, entry in enumerate(candidates):
        if isinstance(entry, PaletteMatch):
            registry.append(entry)
        else:
            name = str(entry).lstrip("/").lower()
            desc = (descriptions or {}).get(name, "")
            registry.append(PaletteMatch(command=name, description=desc, rank=index))
    if not needle:
        ordered = sorted(registry, key=lambda m: (m.command, m.rank))
        return ordered
    scored: list[tuple[int, str, int, PaletteMatch]] = []
    for index, match in enumerate(registry):
        name = match.command.lower()
        desc = (match.description or "").lower()
        keys = " ".join((keywords or {}).get(match.command, [])).lower()
        if name.startswith(needle):
            rank = 0
        elif _is_subsequence(needle, name):
            rank = 1
        elif needle in desc or (keys and needle in keys):
            rank = 2
        elif _is_subsequence(needle, desc) or (keys and _is_subsequence(needle, keys)):
            rank = 2
        else:
            continue
        scored.append((rank, name, index, match))
    scored.sort(key=lambda row: (row[0], row[1], row[2]))
    return [row[3] for row in scored]


def overflow_label(total: int, shown: int) -> str:
    """Footer overflow label such as ``+3 more`` or empty when fitting."""
    remaining = total - shown
    if remaining <= 0:
        return ""
    return f"+{remaining} more"


def mode_token(mode: str) -> str:
    """Theme token for a routing mode (``text`` when unrecognized)."""
    return {
        "quality": "modeQuality",
        "economy": "modeEconomy",
        "manual": "modeManual",
    }.get(mode.strip().lower(), "text")


def should_send_on_enter(state: ComposerState) -> bool:
    """Enter sends only when the slash palette is closed."""
    if state.palette_open:
        return False
    return True


def complete_ghost(draft: str, completion: str) -> tuple[str, bool]:
    """Tab completion: complete without submitting (submitted=False)."""
    name = completion.lstrip("/").split()[0]
    return (f"/{name}", False)


def take_back_newest(queue: list[str]) -> tuple[list[str], str | None]:
    """FIFO take-back: remove and restore the newest queued prompt."""
    if not queue:
        return ([], None)
    return (list(queue[:-1]), queue[-1])


def recall_older(history: list[str], current: str | None) -> str | None:
    """Up recall: newest-first; oldest sticks when already at the bottom."""
    if not history:
        return current
    if current is None:
        return history[-1]
    try:
        index = history.index(current)
    except ValueError:
        return history[-1]
    if index <= 0:
        return history[0]
    return history[index - 1]


def recall_newer(
    history: list[str], current: str | None, draft: str = ""
) -> str | None:
    """Down recall: move toward newer history, then restore in-progress draft."""
    if not history or current is None:
        return draft
    try:
        index = history.index(current)
    except ValueError:
        return draft
    if index >= len(history) - 1:
        return draft
    return history[index + 1]


@dataclass
class ComposerHistory:
    """Submitted-prompt history with edit-recall (recall never mutates)."""

    entries: list[str] = field(default_factory=list)
    cursor: str | None = None
    saved_draft: str = ""
    stashed: str | None = None

    def submit(self, text: str) -> None:
        cleaned = text.strip()
        if cleaned:
            self.entries.append(cleaned)
        self.cursor = None
        self.saved_draft = ""

    def move_older(self, draft: str) -> str:
        if self.cursor is None and draft:
            self.saved_draft = draft
        result = recall_older(self.entries, self.cursor)
        if result is not None:
            self.cursor = result
            return result
        return draft

    def move_newer(self, draft: str) -> str:
        if self.cursor is None:
            return draft
        result = recall_newer(self.entries, self.cursor, self.saved_draft)
        self.cursor = None if result == self.saved_draft else self.cursor
        if result == self.saved_draft:
            self.cursor = None
        return result or ""

    def stash(self, draft: str) -> str:
        self.stashed = draft
        return STASH_RECEIPT


class PromptComposer(Widget):
    """Multiline input card with queue-above view and slash palette."""

    can_focus = True

    DEFAULT_CSS = """
    PromptComposer {
        width: 100%;
        height: auto;
        padding: 0 1;
        background: $surface;
        border-top: solid $borderStrong;
        border-bottom: solid $borderStrong;
    }
    PromptComposer:focus-within {
        border-top: solid $focusRing;
        border-bottom: solid $focusRing;
    }
    #composer-queue {
        width: 100%;
        height: auto;
        background: $surface;
        color: $approval;
        padding: 0 1;
    }
    #composer-outer {
        width: 100%;
        height: auto;
    }
    #composer-actions {
        width: 100%;
        height: auto;
    }
    #composer-card {
        width: 100%;
        height: auto;
        border: none;
        background: $surface;
        padding: 0;
    }
    .composer-input-row {
        width: 100%;
        height: auto;
    }
    .composer-prompt {
        width: 2;
        color: $accent;
    }
    #composer-input {
        width: 1fr;
        height: auto;
        min-height: 3;
        max-height: 8;
        background: $surface;
        color: $text;
    }
    #composer-status {
        width: 1fr;
        height: 1;
        color: $textFaint;
    }
    #composer-mode {
        color: $modeQuality;
        text-style: bold;
        background: $surfaceRaised;
        padding: 0 1;
    }
    #composer-palette {
        width: 100%;
        height: auto;
        max-height: 6;
        background: $surface;
        border-top: solid $border;
        color: $text;
    }
    #composer-send {
        width: auto;
        min-width: 10;
        margin-left: 1;
        border: solid $accent;
        color: $accent;
        background: $accentSoft;
    }
    """

    class PromptSubmitted(Message):
        """Dispatched when the user submits a prompt or command."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class PromptQueued(Message):
        """Dispatched when Ctrl+Enter queues while a run is active."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class DraftStashed(Message):
        """Dispatched on Ctrl+S with the exact stash receipt."""

        def __init__(self, receipt: str = STASH_RECEIPT) -> None:
            super().__init__()
            self.receipt = receipt

    def __init__(
        self,
        mode: str = "QUALITY",
        queue: list[str] | None = None,
        registry: list[str] | None = None,
        descriptions: dict[str, str] | None = None,
        keywords: dict[str, list[str]] | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.composer_mode = mode
        self.queue_items: list[str] = list(queue or [])
        self.history = ComposerHistory()
        self.registry = list(registry or ["help", "agents", "plan", "route"])
        self.descriptions: dict[str, str] = dict(descriptions or {})
        self.keywords: dict[str, list[str]] = dict(keywords or {})
        self._palette_open = False
        self._matches: list[PaletteMatch] = []
        self._palette_index = 0
        self._stashed: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="composer-outer"):
            yield Static("", id="composer-queue")
            with Vertical(id="composer-card"):
                with Horizontal(classes="composer-input-row"):
                    yield Static("\u203a", classes="composer-prompt")
                    yield TextArea(
                        "",
                        id="composer-input",
                        show_line_numbers=False,
                    )
                yield Static("", id="composer-palette")
                with Horizontal(id="composer-actions"):
                    yield Static("", id="composer-status")
                    yield Static(
                        f"MODE [{mode_token(self.composer_mode)}]"
                        f"{self.composer_mode}[/]",
                        id="composer-mode",
                    )
                    yield Button("SEND \u23ce", id="composer-send")

    def on_mount(self) -> None:
        self._refresh_queue()
        self._refresh_status()

    @property
    def draft_text(self) -> str:
        try:
            area = self.query_one("#composer-input", TextArea)
            return area.text
        except Exception:
            return ""

    def set_queue(self, queue: list[str]) -> None:
        """Replace the projection-derived FIFO queue view."""
        self.queue_items = list(queue)
        self._refresh_queue()

    def _refresh_queue(self) -> None:
        try:
            label = self.query_one("#composer-queue", Static)
        except Exception:
            return
        if not self.queue_items:
            label.update("")
            label.display = False
            return
        label.display = True
        lines = [
            f"QUEUED {len(self.queue_items)} \u00b7 ^ take back"
            " \u00b7 newest runs after this one"
        ]
        for number, item in enumerate(self.queue_items, start=1):
            lines.append(f"{number}  {item}")
        label.update("\n".join(lines))

    def _refresh_status(self) -> None:
        try:
            status = self.query_one("#composer-status", Static)
            status.update(
                f"{len(self.draft_text)} chars \u00b7 / commands \u00b7 ? shortcuts"
            )
        except Exception:
            pass

    def _refresh_palette(self) -> None:
        try:
            palette = self.query_one("#composer-palette", Static)
        except Exception:
            return
        if not self._palette_open or not self._matches:
            palette.update("")
            palette.display = False
            return
        palette.display = True
        rows = self._matches[:MAX_PALETTE_ROWS]
        lines = ["Commands"]
        for number, match in enumerate(rows):
            marker = ">" if number == self._palette_index else " "
            detail = f"  {match.description}" if match.description else ""
            lines.append(f"{marker} /{match.command}{detail}")
        extra = overflow_label(len(self._matches), len(rows))
        if extra:
            lines.append(f"  {extra}")
        palette.update("\n".join(lines))

    def _update_palette_for_draft(self, draft: str) -> None:
        if draft.startswith("/") and "\n" not in draft:
            entries = [
                PaletteMatch(
                    command=name,
                    description=self.descriptions.get(name, ""),
                )
                for name in self.registry
            ]
            self._matches = fuzzy_match_commands(
                draft, entries, self.descriptions, self.keywords
            )
            self._palette_open = bool(self._matches)
            self._palette_index = 0
        else:
            self._matches = []
            self._palette_open = False
        self._refresh_palette()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        _ = event
        self._update_palette_for_draft(self.draft_text)
        self._refresh_status()

    def _submit_text(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        self.history.submit(cleaned)
        try:
            area = self.query_one("#composer-input", TextArea)
            area.text = ""
        except Exception:
            pass
        self._matches = []
        self._palette_open = False
        self._refresh_palette()
        self._refresh_status()
        self.post_message(self.PromptSubmitted(cleaned))

    def _queue_text(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        self.queue_items.append(cleaned)
        try:
            area = self.query_one("#composer-input", TextArea)
            area.text = ""
        except Exception:
            pass
        self._refresh_queue()
        self._refresh_status()
        self.post_message(self.PromptQueued(cleaned))

    async def on_key(self, event: events.Key) -> None:
        try:
            area = self.query_one("#composer-input", TextArea)
            focused = self.app.focused is area
        except Exception:
            focused = False
        if not focused:
            return
        draft = self.draft_text
        if event.key == "escape" and self._palette_open:
            self._palette_open = False
            self._matches = []
            self._refresh_palette()
            event.stop()
            return
        if event.key == "tab" and self._palette_open and self._matches:
            match = self._matches[self._palette_index % len(self._matches)]
            completed, _ = complete_ghost(draft, match.command)
            try:
                area.text = completed
            except Exception:
                pass
            self._refresh_status()
            event.stop()
            return
        if event.key == "ctrl+enter":
            if self.queue_items:
                self._queue_text(draft)
            else:
                self._submit_text(draft)
            event.stop()
            return
        if event.key == "shift+enter":
            return
        if event.key == "enter":
            state = ComposerState(draft=draft, palette_open=self._palette_open)
            if not should_send_on_enter(state):
                match = self._matches[self._palette_index % len(self._matches)]
                if " " in draft.strip() or match.command in ("help",):
                    completed, _ = complete_ghost(draft, match.command)
                    try:
                        area.text = completed
                    except Exception:
                        pass
                    self._refresh_status()
                event.stop()
                return
            if self.queue_items:
                self._queue_text(draft)
            else:
                self._submit_text(draft)
            event.stop()
            return
        if event.key == "up" and not draft.strip():
            if self.queue_items:
                _, restored = take_back_newest(self.queue_items)
                self.queue_items = take_back_newest(self.queue_items)[0]
                self._refresh_queue()
                if restored is not None:
                    try:
                        area.text = restored
                    except Exception:
                        pass
                    self._refresh_status()
            else:
                recalled = self.history.move_older(draft)
                try:
                    area.text = recalled
                except Exception:
                    pass
                self._refresh_status()
            event.stop()
            return
        if event.key == "down" and self.history.cursor is not None:
            recalled = self.history.move_newer(draft)
            try:
                area.text = recalled
            except Exception:
                pass
            self._refresh_status()
            event.stop()
            return
        if event.key == "ctrl+s":
            receipt = self.history.stash(draft)
            self._stashed = draft
            try:
                area.text = ""
            except Exception:
                pass
            self._refresh_status()
            self.post_message(self.DraftStashed(receipt))
            event.stop()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "composer-send":
            state = ComposerState(
                draft=self.draft_text, palette_open=self._palette_open
            )
            if should_send_on_enter(state):
                self._submit_text(self.draft_text)


__all__ = [
    "COMPOSER_PLACEHOLDER",
    "COMPOSER_VALIDATING_TEXT",
    "MAX_COMPOSER_ROWS",
    "MAX_PALETTE_ROWS",
    "MIN_COMPOSER_ROWS",
    "STASH_RECEIPT",
    "ComposerHistory",
    "ComposerState",
    "PaletteMatch",
    "PromptComposer",
    "complete_ghost",
    "fuzzy_match_commands",
    "mode_token",
    "overflow_label",
    "recall_newer",
    "recall_older",
    "should_send_on_enter",
    "take_back_newest",
]
