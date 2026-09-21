"""Phase 1 theme token tests (draft sections 3.2, 13.2)."""

from __future__ import annotations

import os
import re
from dataclasses import replace
from pathlib import Path

import pytest
from rich.style import Style

from skail.tui.theme import (
    BUDGET_CRITICAL_THRESHOLD,
    BUDGET_WARNING_THRESHOLD,
    DARK_THEME,
    LIGHT_THEME,
    MINT_PORCELAIN_THEME,
    PISTACHIO_NIGHT_THEME,
    PISTACHIO_PAPER_THEME,
    REQUIRED_TOKENS,
    agent_slot_token,
    as_dict,
    budget_token_for_ratio,
    contrast_ratio,
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
    "background": "#14110E",
    "surface": "#1B1714",
    "surfaceRaised": "#221D19",
    "surfaceInset": "#100D0A",
    "border": "#322A24",
    "borderStrong": "#4F4238",
    "text": "#EDE4D6",
    "textMuted": "#9A8C7B",
    "textFaint": "#6E6154",
    "accent": "#D98E4A",
    "accentSoft": "#2E2318",
    "modeQuality": "#B39DDB",
    "modeEconomy": "#82C9A5",
    "modeManual": "#D9A441",
    "delegation": "#B39DDB",
    "budgetFill": "#C9A227",
    "budgetWarning": "#D98E4A",
    "budgetCritical": "#E0645A",
    "budgetEmpty": "#2C2620",
    "diffAdded": "#8FBF7A",
    "diffAddedSurface": "#182114",
    "diffRemoved": "#E0645A",
    "diffRemovedSurface": "#2A1614",
    "dimmed": "#6E6154",
    "error": "#E0645A",
    "errorSurface": "#2A1614",
    "approval": "#D9A441",
    "approvalSurface": "#241E14",
    "agentOne": "#7FB3D5",
    "agentTwo": "#B39DDB",
    "agentThree": "#82C9A5",
    "shimmerBase": "#6E6154",
    "shimmerPeak": "#F6E7D0",
    "focusRing": "#E8B978",
    "selection": "#3A2F22",
    "link": "#8FC7E8",
}

EXPECTED_LIGHT = {
    "background": "#F4F0E7",
    "surface": "#FBF8F1",
    "surfaceRaised": "#EDE7DA",
    "surfaceInset": "#E7E0D2",
    "border": "#D6CCBB",
    "borderStrong": "#A99C87",
    "text": "#241E17",
    "textMuted": "#6E6154",
    "textFaint": "#948878",
    "accent": "#9E5518",
    "accentSoft": "#F0E0CB",
    "modeQuality": "#5E46A0",
    "modeEconomy": "#2C7355",
    "modeManual": "#8A6200",
    "delegation": "#5E46A0",
    "budgetFill": "#8A6A0C",
    "budgetWarning": "#9E5518",
    "budgetCritical": "#AE3227",
    "budgetEmpty": "#DCD4C5",
    "diffAdded": "#2C7355",
    "diffAddedSurface": "#DDF3E6",
    "diffRemoved": "#AE3227",
    "diffRemovedSurface": "#F6E2DE",
    "dimmed": "#948878",
    "error": "#AE3227",
    "errorSurface": "#F6E2DE",
    "approval": "#8A6200",
    "approvalSurface": "#FAEEC9",
    "agentOne": "#2F6E92",
    "agentTwo": "#5E46A0",
    "agentThree": "#2C7355",
    "shimmerBase": "#A99C87",
    "shimmerPeak": "#241E17",
    "focusRing": "#7A3F0E",
    "selection": "#E3D3BC",
    "link": "#2F6E92",
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


def test_pistachio_themes_expose_the_complete_semantic_palette() -> None:
    for theme in (PISTACHIO_NIGHT_THEME, PISTACHIO_PAPER_THEME, MINT_PORCELAIN_THEME):
        validate_theme(theme)
        assert set(as_dict(theme)) == set(REQUIRED_TOKENS)


def test_new_theme_text_and_focus_contrast_meets_wcag_targets() -> None:
    for theme in (PISTACHIO_NIGHT_THEME, PISTACHIO_PAPER_THEME, MINT_PORCELAIN_THEME):
        assert contrast_ratio(theme.text, theme.background) >= 4.5
        assert contrast_ratio(theme.focus_ring, theme.surface) >= 3.0


def test_new_theme_preview_escape_restores_the_committed_theme() -> None:
    from skail.tui.app import SkailApp

    app = SkailApp(theme_name="pistachio-night")
    app._previous_theme = "pistachio-night"  # type: ignore[attr-defined]
    app.apply_theme_preview("pistachio-paper")

    app.restore_theme()

    assert app.current_theme_name == "pistachio-night"


def test_every_token_is_valid_six_digit_hex() -> None:
    for theme in (DARK_THEME, LIGHT_THEME):
        validate_theme(theme)
        for name, value in as_dict(theme).items():
            assert HEX_RE.match(value), f"{name}={value}"


def test_validate_theme_raises_on_eight_digit_and_missing_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    eight_digit = replace(DARK_THEME, diff_added_surface="#18211400")
    with pytest.raises(ValueError):
        validate_theme(eight_digit)
    monkeypatch.setattr(
        "skail.tui.theme.REQUIRED_TOKENS",
        (*REQUIRED_TOKENS, "ghostToken"),
    )
    with pytest.raises(ValueError):
        validate_theme(DARK_THEME)


def test_lookup_and_unknown_token() -> None:
    assert lookup(DARK_THEME, "accent") == "#D98E4A"
    assert lookup(LIGHT_THEME, "background") == "#F4F0E7"
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
    assert variables["--accent"] == "#D98E4A"
    assert len(variables) == len(REQUIRED_TOKENS)
    css = to_textual_css(DARK_THEME)
    assert "--background: #14110E;" in css
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
