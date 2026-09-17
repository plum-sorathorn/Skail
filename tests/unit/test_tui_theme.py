"""Phase 1 theme token tests (draft sections 3.2, 13.2)."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from rich.style import Style

from skail.tui.theme import (
    BUDGET_CRITICAL_THRESHOLD,
    BUDGET_WARNING_THRESHOLD,
    DARK_THEME,
    LIGHT_THEME,
    REQUIRED_TOKENS,
    agent_slot_token,
    as_dict,
    budget_token_for_ratio,
    detect_system_preference,
    get_theme,
    lookup,
    reduced_motion_enabled,
    resolve_system_theme,
    rich_style,
    theme_token_names,
    to_css_variables,
    to_textual_css,
    validate_theme,
)

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

EXPECTED_DARK = {
    "background": "#0B0D10",
    "surface": "#11151A",
    "surfaceRaised": "#171C22",
    "surfaceInset": "#0E1216",
    "border": "#2A313A",
    "borderStrong": "#3A4552",
    "text": "#E8EDF2",
    "textMuted": "#8E99A6",
    "textFaint": "#59636F",
    "accent": "#5CC8FF",
    "accentSoft": "#173748",
    "modeQuality": "#B69CFF",
    "modeEconomy": "#58D6A7",
    "modeManual": "#F2B866",
    "delegation": "#A88BFA",
    "budgetFill": "#5CC8FF",
    "budgetWarning": "#F2B866",
    "budgetCritical": "#FF6B7A",
    "budgetEmpty": "#303842",
    "diffAdded": "#4FCB8D",
    "diffAddedSurface": "#102A20",
    "diffRemoved": "#FF7D88",
    "diffRemovedSurface": "#32171C",
    "dimmed": "#66717D",
    "error": "#FF6B7A",
    "errorSurface": "#34171D",
    "approval": "#F5C451",
    "approvalSurface": "#302711",
    "agentOne": "#5CC8FF",
    "agentTwo": "#B69CFF",
    "agentThree": "#58D6A7",
    "shimmerBase": "#56616D",
    "shimmerPeak": "#D5F3FF",
    "focusRing": "#86D8FF",
    "selection": "#24495D",
    "link": "#79D1FF",
}

EXPECTED_LIGHT = {
    "background": "#F6F7F9",
    "surface": "#FFFFFF",
    "surfaceRaised": "#EEF1F4",
    "surfaceInset": "#E8ECF0",
    "border": "#CBD2DA",
    "borderStrong": "#98A3AF",
    "text": "#18202A",
    "textMuted": "#66717D",
    "textFaint": "#9099A3",
    "accent": "#006F9F",
    "accentSoft": "#D9F1FC",
    "modeQuality": "#6545B8",
    "modeEconomy": "#087A55",
    "modeManual": "#98600B",
    "delegation": "#6741C7",
    "budgetFill": "#007AAE",
    "budgetWarning": "#98600B",
    "budgetCritical": "#B42335",
    "budgetEmpty": "#D5DBE1",
    "diffAdded": "#087A49",
    "diffAddedSurface": "#DDF6E9",
    "diffRemoved": "#B42335",
    "diffRemovedSurface": "#FCE2E5",
    "dimmed": "#89929C",
    "error": "#B42335",
    "errorSurface": "#FCE4E7",
    "approval": "#8A6200",
    "approvalSurface": "#FFF2C4",
    "agentOne": "#006F9F",
    "agentTwo": "#6545B8",
    "agentThree": "#087A55",
    "shimmerBase": "#98A3AF",
    "shimmerPeak": "#006F9F",
    "focusRing": "#005D86",
    "selection": "#CBEAF8",
    "link": "#006F9F",
}


def test_required_token_names_match_draft_table() -> None:
    assert set(theme_token_names()) == set(EXPECTED_DARK)
    assert set(theme_token_names()) == set(EXPECTED_LIGHT)
    assert len(REQUIRED_TOKENS) == 36


def test_dark_theme_matches_draft_table() -> None:
    assert as_dict(DARK_THEME) == EXPECTED_DARK


def test_light_theme_matches_draft_table() -> None:
    assert as_dict(LIGHT_THEME) == EXPECTED_LIGHT


def test_dark_and_light_expose_identical_token_names() -> None:
    assert set(as_dict(DARK_THEME)) == set(as_dict(LIGHT_THEME))


def test_every_token_is_valid_six_digit_hex() -> None:
    for theme in (DARK_THEME, LIGHT_THEME):
        validate_theme(theme)
        for name, value in as_dict(theme).items():
            assert HEX_RE.match(value), f"{name}={value}"


def test_lookup_and_unknown_token() -> None:
    assert lookup(DARK_THEME, "accent") == "#5CC8FF"
    assert lookup(LIGHT_THEME, "background") == "#F6F7F9"
    with pytest.raises(KeyError):
        lookup(DARK_THEME, "notAToken")


def test_get_theme_names() -> None:
    assert get_theme("dark") is DARK_THEME
    assert get_theme("light") is LIGHT_THEME
    with pytest.raises(KeyError):
        get_theme("system")


def test_system_resolution_falls_back_to_dark_and_says_so() -> None:
    theme, detail = resolve_system_theme(None)
    assert theme is DARK_THEME
    assert "Dark" in detail
    theme, _ = resolve_system_theme("light")
    assert theme is LIGHT_THEME
    theme, _ = resolve_system_theme("dark")
    assert theme is DARK_THEME


def test_detect_system_preference_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SKAIL_THEME", raising=False)
    monkeypatch.delenv("COLORFTO", raising=False)
    monkeypatch.delenv("OS_APPEARANCE", raising=False)
    assert detect_system_preference() is None
    monkeypatch.setenv("SKAIL_THEME", "light")
    assert detect_system_preference() == "light"


def test_reduced_motion_pref(monkeypatch: pytest.MonkeyPatch) -> None:
    assert reduced_motion_enabled(explicit=True) is True
    assert reduced_motion_enabled(explicit=False) is False
    for var in ("SKAIL_REDUCED_MOTION", "REDUCED_MOTION", "NO_ANIMATION"):
        monkeypatch.delenv(var, raising=False)
    assert reduced_motion_enabled() is False
    monkeypatch.setenv("SKAIL_REDUCED_MOTION", "1")
    assert reduced_motion_enabled() is True


def test_css_variables_and_textual_css() -> None:
    variables = to_css_variables(DARK_THEME)
    assert variables["--accent"] == "#5CC8FF"
    assert len(variables) == len(REQUIRED_TOKENS)
    css = to_textual_css(DARK_THEME)
    assert "--background: #0B0D10;" in css
    assert "theme.py" not in css


def test_rich_style_helper() -> None:
    style = rich_style(DARK_THEME, "error")
    assert isinstance(style, Style)
    assert style.color is not None


def test_agent_slots_map_stably_to_slots_1_to_3() -> None:
    assert agent_slot_token(1) == "agentOne"
    assert agent_slot_token(2) == "agentTwo"
    assert agent_slot_token(3) == "agentThree"
    with pytest.raises(KeyError):
        agent_slot_token(4)


def test_budget_thresholds_change_at_exactly_75_and_90() -> None:
    assert BUDGET_WARNING_THRESHOLD == 0.75
    assert BUDGET_CRITICAL_THRESHOLD == 0.90
    assert budget_token_for_ratio(0.0) == "budgetFill"
    assert budget_token_for_ratio(0.749) == "budgetFill"
    assert budget_token_for_ratio(0.75) == "budgetWarning"
    assert budget_token_for_ratio(0.89) == "budgetWarning"
    assert budget_token_for_ratio(0.90) == "budgetCritical"
    assert budget_token_for_ratio(1.0) == "budgetCritical"
    assert budget_token_for_ratio(None) == "budgetEmpty"


def test_new_tui_modules_contain_no_raw_hex() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    checked = [
        repo_root / "src/skail/tui/onboarding.py",
        repo_root / "src/skail/tui/widgets/onboarding.py",
    ]
    assert all(path.exists() for path in checked)
    for path in checked:
        matches = re.findall(r"#[0-9A-Fa-f]{6}\b", path.read_text(encoding="utf-8"))
        assert matches == [], f"{path} contains raw hex: {matches}"


def test_no_legacy_hex_leaks_into_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", {})
    assert detect_system_preference() is None
