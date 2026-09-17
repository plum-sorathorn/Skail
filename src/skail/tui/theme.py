"""Semantic theme tokens for the Skail TUI (single source of truth).

Draft source: docs/skail/TUI_REVAMP_DRAFT.md sections 3.1-3.2.
Every widget must consume these tokens; no raw hex value may appear in
widget CSS, Rich markup, or rendering logic outside this module.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, fields
from typing import Literal

from rich.style import Style

ThemeName = Literal["dark", "light", "system"]

HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

#: Canonical token names exactly as listed in draft section 3.2.
REQUIRED_TOKENS: tuple[str, ...] = (
    "background",
    "surface",
    "surfaceRaised",
    "surfaceInset",
    "border",
    "borderStrong",
    "text",
    "textMuted",
    "textFaint",
    "accent",
    "accentSoft",
    "modeQuality",
    "modeEconomy",
    "modeManual",
    "delegation",
    "budgetFill",
    "budgetWarning",
    "budgetCritical",
    "budgetEmpty",
    "diffAdded",
    "diffAddedSurface",
    "diffRemoved",
    "diffRemovedSurface",
    "dimmed",
    "error",
    "errorSurface",
    "approval",
    "approvalSurface",
    "agentOne",
    "agentTwo",
    "agentThree",
    "shimmerBase",
    "shimmerPeak",
    "focusRing",
    "selection",
    "link",
)

#: Budget meter thresholds from draft sections 5.1/5.8.
BUDGET_WARNING_THRESHOLD = 0.75
BUDGET_CRITICAL_THRESHOLD = 0.90

#: Child slot (1-based, stable for the session lifetime) to token name.
AGENT_SLOT_TOKENS: dict[int, str] = {
    1: "agentOne",
    2: "agentTwo",
    3: "agentThree",
}


@dataclass(frozen=True)
class ThemeTokens:
    """Immutable semantic color tokens for one theme variant."""

    background: str
    surface: str
    surface_raised: str
    surface_inset: str
    border: str
    border_strong: str
    text: str
    text_muted: str
    text_faint: str
    accent: str
    accent_soft: str
    mode_quality: str
    mode_economy: str
    mode_manual: str
    delegation: str
    budget_fill: str
    budget_warning: str
    budget_critical: str
    budget_empty: str
    diff_added: str
    diff_added_surface: str
    diff_removed: str
    diff_removed_surface: str
    dimmed: str
    error: str
    error_surface: str
    approval: str
    approval_surface: str
    agent_one: str
    agent_two: str
    agent_three: str
    shimmer_base: str
    shimmer_peak: str
    focus_ring: str
    selection: str
    link: str


def _snake(name: str) -> str:
    out: list[str] = []
    for char in name:
        if char.isupper():
            out.append("_")
            out.append(char.lower())
        else:
            out.append(char)
    return "".join(out)


DARK_THEME = ThemeTokens(
    background="#0B0D10",
    surface="#11151A",
    surface_raised="#171C22",
    surface_inset="#0E1216",
    border="#2A313A",
    border_strong="#3A4552",
    text="#E8EDF2",
    text_muted="#8E99A6",
    text_faint="#59636F",
    accent="#5CC8FF",
    accent_soft="#173748",
    mode_quality="#B69CFF",
    mode_economy="#58D6A7",
    mode_manual="#F2B866",
    delegation="#A88BFA",
    budget_fill="#5CC8FF",
    budget_warning="#F2B866",
    budget_critical="#FF6B7A",
    budget_empty="#303842",
    diff_added="#4FCB8D",
    diff_added_surface="#102A20",
    diff_removed="#FF7D88",
    diff_removed_surface="#32171C",
    dimmed="#66717D",
    error="#FF6B7A",
    error_surface="#34171D",
    approval="#F5C451",
    approval_surface="#302711",
    agent_one="#5CC8FF",
    agent_two="#B69CFF",
    agent_three="#58D6A7",
    shimmer_base="#56616D",
    shimmer_peak="#D5F3FF",
    focus_ring="#86D8FF",
    selection="#24495D",
    link="#79D1FF",
)

LIGHT_THEME = ThemeTokens(
    background="#F6F7F9",
    surface="#FFFFFF",
    surface_raised="#EEF1F4",
    surface_inset="#E8ECF0",
    border="#CBD2DA",
    border_strong="#98A3AF",
    text="#18202A",
    text_muted="#66717D",
    text_faint="#9099A3",
    accent="#006F9F",
    accent_soft="#D9F1FC",
    mode_quality="#6545B8",
    mode_economy="#087A55",
    mode_manual="#98600B",
    delegation="#6741C7",
    budget_fill="#007AAE",
    budget_warning="#98600B",
    budget_critical="#B42335",
    budget_empty="#D5DBE1",
    diff_added="#087A49",
    diff_added_surface="#DDF6E9",
    diff_removed="#B42335",
    diff_removed_surface="#FCE2E5",
    dimmed="#89929C",
    error="#B42335",
    error_surface="#FCE4E7",
    approval="#8A6200",
    approval_surface="#FFF2C4",
    agent_one="#006F9F",
    agent_two="#6545B8",
    agent_three="#087A55",
    shimmer_base="#98A3AF",
    shimmer_peak="#006F9F",
    focus_ring="#005D86",
    selection="#CBEAF8",
    link="#006F9F",
)


def theme_token_names() -> tuple[str, ...]:
    """Return the canonical draft token names."""
    return REQUIRED_TOKENS


def as_dict(theme: ThemeTokens) -> dict[str, str]:
    """Map canonical draft token names to hex values."""
    values = {field.name: getattr(theme, field.name) for field in fields(theme)}
    return {_camel(name): value for name, value in values.items()}


def _camel(snake: str) -> str:
    parts = snake.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


def validate_theme(theme: ThemeTokens) -> None:
    """Raise ValueError unless every token is a valid six-digit hex color."""
    mapping = as_dict(theme)
    missing = [name for name in REQUIRED_TOKENS if name not in mapping]
    if missing:
        raise ValueError(f"Theme is missing tokens: {', '.join(missing)}")
    invalid = [name for name, value in mapping.items() if not HEX_COLOR_RE.match(value)]
    if invalid:
        raise ValueError(f"Theme has invalid hex values: {', '.join(invalid)}")


def lookup(theme: ThemeTokens, token: str) -> str:
    """Return the hex value for a canonical token name, else raise KeyError."""
    try:
        value = getattr(theme, _snake(token))
    except AttributeError as exc:
        raise KeyError(f"Unknown theme token: {token}") from exc
    assert isinstance(value, str)
    return value


def get_theme(name: ThemeName) -> ThemeTokens:
    """Return the token set for a concrete theme name."""
    if name == "light":
        return LIGHT_THEME
    if name == "dark":
        return DARK_THEME
    raise KeyError("Use resolve_system_theme() for the 'system' theme name.")


def resolve_system_theme(detected: str | None = None) -> tuple[ThemeTokens, str]:
    """Resolve 'system' to dark/light; fall back to Dark and say so.

    Returns the token set plus a human-readable detail string for the UI.
    """
    normalized = (detected or "").strip().lower()
    if normalized == "light":
        return LIGHT_THEME, "System theme resolved to Light."
    if normalized == "dark":
        return DARK_THEME, "System theme resolved to Dark."
    return DARK_THEME, "System preference unavailable; resolved to Dark."


def detect_system_preference() -> str | None:
    """Best-effort terminal/OS theme preference, or None if undetectable."""
    for var in ("SKAIL_THEME", "COLORFTO", "OS_APPEARANCE"):
        value = os.environ.get(var, "").strip().lower()
        if value in ("dark", "light"):
            return value
    return None


def reduced_motion_enabled(explicit: bool | None = None) -> bool:
    """Resolve the reduced-motion preference (draft section 6.2)."""
    if explicit is not None:
        return explicit
    for var in ("SKAIL_REDUCED_MOTION", "REDUCED_MOTION", "NO_ANIMATION"):
        if os.environ.get(var, "").strip().lower() in ("1", "true", "yes"):
            return True
    return False


def to_css_variables(theme: ThemeTokens) -> dict[str, str]:
    """Map tokens to Textual CSS variable declarations."""
    return {f"--{name}": value for name, value in as_dict(theme).items()}


def to_textual_css(theme: ThemeTokens, scope: str = ":root") -> str:
    """Generate scoped Textual CSS variable block from tokens."""
    lines = [f"{scope} {{"]
    lines.extend(f"    --{name}: {value};" for name, value in as_dict(theme).items())
    lines.append("}")
    return "\n".join(lines)


def rich_style(theme: ThemeTokens, token: str) -> Style:
    """Build a Rich Style for a canonical token name."""
    return Style(color=lookup(theme, token))


def budget_token_for_ratio(ratio: float | None) -> str:
    """Return the budget meter token for a used ratio (draft section 5.1)."""
    if ratio is None:
        return "budgetEmpty"
    if ratio >= BUDGET_CRITICAL_THRESHOLD:
        return "budgetCritical"
    if ratio >= BUDGET_WARNING_THRESHOLD:
        return "budgetWarning"
    return "budgetFill"


def agent_slot_token(slot: int) -> str:
    """Return the stable agent color token for child slot 1-3."""
    try:
        return AGENT_SLOT_TOKENS[slot]
    except KeyError as exc:
        raise KeyError(f"Unknown agent slot: {slot}") from exc
