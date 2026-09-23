"""Twin sail logo constants for the Skail TUI.

The full six-row mark is monochrome text only and is never animated.
The main masthead uses the compact fallback-safe text mark.
"""

from __future__ import annotations

TWIN_SAIL_LOGO: list[str] = [
    "      /\\|\\",
    "     /  | \\",
    "    /___|__\\",
    "   /____|___\\",
    "   \\________/",
    "    S K A I L",
]

COMPACT_MARK = "/\\| S K A I L"

LOGO_TEXT = "\n".join(TWIN_SAIL_LOGO)


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
    "TWIN_SAIL_LOGO",
    "compact_mark",
    "help_header",
    "render_logo_text",
]
