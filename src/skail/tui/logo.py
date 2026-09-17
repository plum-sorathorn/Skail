"""Windward logo constants for the Skail TUI (Phase 4).

The full 6-row mark is monochrome text only and is never animated.
Header uses the fallback-safe compact mark ``S│``.
"""

from __future__ import annotations

WINDWARD_LOGO: list[str] = [
    "   ■",
    "  ■■│",
    " ■■■│",
    "■■■■│",
    "  ▪ │",
    "━━━━━━━",
]

COMPACT_MARK = "S\u2502"

LOGO_TEXT = "\n".join(WINDWARD_LOGO)


def render_logo_text() -> str:
    """Return the full 6-row logo as plain text (no markup, no animation)."""
    return LOGO_TEXT


def help_header() -> str:
    """Monochrome logo header prepended to /help output."""
    return LOGO_TEXT + "\nSkail help"


def compact_mark() -> str:
    """Fallback-safe header mark."""
    return COMPACT_MARK


__all__ = [
    "COMPACT_MARK",
    "LOGO_TEXT",
    "WINDWARD_LOGO",
    "compact_mark",
    "help_header",
    "render_logo_text",
]
