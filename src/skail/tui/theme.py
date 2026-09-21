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

ThemeName = Literal[
    "dark",
    "light",
    "system",
    "pistachio-night",
    "pistachio-paper",
    "mint-porcelain",
]

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
    background="#14110E",
    surface="#1B1714",
    surface_raised="#221D19",
    surface_inset="#100D0A",
    border="#322A24",
    border_strong="#4F4238",
    text="#EDE4D6",
    text_muted="#9A8C7B",
    text_faint="#6E6154",
    accent="#D98E4A",
    accent_soft="#2E2318",
    mode_quality="#B39DDB",
    mode_economy="#82C9A5",
    mode_manual="#D9A441",
    delegation="#B39DDB",
    budget_fill="#C9A227",
    budget_warning="#D98E4A",
    budget_critical="#E0645A",
    budget_empty="#2C2620",
    diff_added="#8FBF7A",
    diff_added_surface="#182114",
    diff_removed="#E0645A",
    diff_removed_surface="#2A1614",
    dimmed="#6E6154",
    error="#E0645A",
    error_surface="#2A1614",
    approval="#D9A441",
    approval_surface="#241E14",
    agent_one="#7FB3D5",
    agent_two="#B39DDB",
    agent_three="#82C9A5",
    shimmer_base="#6E6154",
    shimmer_peak="#F6E7D0",
    focus_ring="#E8B978",
    selection="#3A2F22",
    link="#8FC7E8",
)

LIGHT_THEME = ThemeTokens(
    background="#F4F0E7",
    surface="#FBF8F1",
    surface_raised="#EDE7DA",
    surface_inset="#E7E0D2",
    border="#D6CCBB",
    border_strong="#A99C87",
    text="#241E17",
    text_muted="#6E6154",
    text_faint="#948878",
    accent="#9E5518",
    accent_soft="#F0E0CB",
    mode_quality="#5E46A0",
    mode_economy="#2C7355",
    mode_manual="#8A6200",
    delegation="#5E46A0",
    budget_fill="#8A6A0C",
    budget_warning="#9E5518",
    budget_critical="#AE3227",
    budget_empty="#DCD4C5",
    diff_added="#2C7355",
    diff_added_surface="#DDF3E6",
    diff_removed="#AE3227",
    diff_removed_surface="#F6E2DE",
    dimmed="#948878",
    error="#AE3227",
    error_surface="#F6E2DE",
    approval="#8A6200",
    approval_surface="#FAEEC9",
    agent_one="#2F6E92",
    agent_two="#5E46A0",
    agent_three="#2C7355",
    shimmer_base="#A99C87",
    shimmer_peak="#241E17",
    focus_ring="#7A3F0E",
    selection="#E3D3BC",
    link="#2F6E92",
)

PISTACHIO_NIGHT_THEME = ThemeTokens(
    background="#101713", surface="#18221C", surface_raised="#203029", surface_inset="#0B110E",
    border="#385044", border_strong="#56735D", text="#E8F0E8", text_muted="#A8B8AA",
    text_faint="#77897B", accent="#9FD3A9", accent_soft="#294133", mode_quality="#B7A6D9",
    mode_economy="#9FD3A9", mode_manual="#E5C27F", delegation="#B7A6D9", budget_fill="#9FD3A9",
    budget_warning="#E5C27F", budget_critical="#F18A82", budget_empty="#2B3B31",
    diff_added="#A9D99E", diff_added_surface="#203A29", diff_removed="#F18A82",
    diff_removed_surface="#3C2425", dimmed="#77897B", error="#F18A82", error_surface="#3C2425",
    approval="#E5C27F", approval_surface="#3B321F", agent_one="#86B7D5", agent_two="#C0A4E8",
    agent_three="#9FD3A9", shimmer_base="#77897B", shimmer_peak="#F5FFF5", focus_ring="#BDE8C4",
    selection="#2D4A39", link="#A8D8E8",
)

PISTACHIO_PAPER_THEME = ThemeTokens(
    background="#F1F3E7", surface="#FAFBF4", surface_raised="#E4E9D8", surface_inset="#E9EEDF",
    border="#B9C5AF", border_strong="#82957A", text="#243128", text_muted="#667468",
    text_faint="#849286", accent="#648F5A", accent_soft="#DDE8C9", mode_quality="#65539A",
    mode_economy="#3E7655", mode_manual="#8A6200", delegation="#65539A", budget_fill="#648F5A",
    budget_warning="#8A6200", budget_critical="#A83D35", budget_empty="#D4DDC9",
    diff_added="#3E7655", diff_added_surface="#D8EBD8", diff_removed="#A83D35",
    diff_removed_surface="#F2D9D5", dimmed="#849286", error="#A83D35", error_surface="#F2D9D5",
    approval="#8A6200", approval_surface="#F6E9BF", agent_one="#2F6E92", agent_two="#65539A",
    agent_three="#3E7655", shimmer_base="#B9C5AF", shimmer_peak="#243128", focus_ring="#416D3A",
    selection="#D4E4CC", link="#2F6E92",
)

MINT_PORCELAIN_THEME = ThemeTokens(
    background="#E9F0EB", surface="#F7FAF7", surface_raised="#DCE8E1", surface_inset="#E1EBE5",
    border="#AFC7BA", border_strong="#789B89", text="#1F2E28", text_muted="#61736A",
    text_faint="#809188", accent="#468E71", accent_soft="#CFE7DA", mode_quality="#66539A",
    mode_economy="#34745B", mode_manual="#8A6200", delegation="#66539A", budget_fill="#468E71",
    budget_warning="#8A6200", budget_critical="#A43D3A", budget_empty="#C9DAD0",
    diff_added="#34745B", diff_added_surface="#D3EBDD", diff_removed="#A43D3A",
    diff_removed_surface="#F1D9D7", dimmed="#809188", error="#A43D3A", error_surface="#F1D9D7",
    approval="#8A6200", approval_surface="#F5E9C3", agent_one="#2F6E92", agent_two="#66539A",
    agent_three="#34745B", shimmer_base="#AFC7BA", shimmer_peak="#1F2E28", focus_ring="#2E6D54",
    selection="#C7DED2", link="#2F6E92",
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
    if name == "pistachio-night":
        return PISTACHIO_NIGHT_THEME
    if name == "pistachio-paper":
        return PISTACHIO_PAPER_THEME
    if name == "mint-porcelain":
        return MINT_PORCELAIN_THEME
    raise KeyError("Use resolve_system_theme() for the 'system' theme name.")


def contrast_ratio(foreground: str, background: str) -> float:
    """Return the WCAG contrast ratio for two six-digit hex colors."""
    def channel(value: str) -> float:
        channel_value = int(value, 16) / 255
        return (
            channel_value / 12.92
            if channel_value <= 0.04045
            else ((channel_value + 0.055) / 1.055) ** 2.4
        )

    def luminance(color: str) -> float:
        return (
            0.2126 * channel(color[1:3])
            + 0.7152 * channel(color[3:5])
            + 0.0722 * channel(color[5:7])
        )

    first, second = luminance(foreground), luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


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
