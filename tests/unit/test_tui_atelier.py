"""Unit tests for the ATELIER chrome (dateline, transcript header, footer)."""

from skail.tui.app import render_dateline, render_transcript_header
from skail.tui.widgets.footer import AtelierFooter, format_footer_hints


def test_render_dateline_uses_theme_tokens_and_values() -> None:
    """Dateline markup carries theme-token styles plus model, mode and pct values."""
    result = render_dateline(
        model="auto",
        mode="quality",
        cost="$1.2345 / $10.00",
        ratio=0.1234,
        active=1,
        running=1,
        queued=2,
        badge="STARTING",
        badge_token="textMuted",
        active_mode="planned",
    )
    assert "[textFaint]MODEL[/] [text]auto[/]" in result
    assert "[modeQuality]quality[/]" in result
    assert "[budgetFill]▓[/]" in result
    assert "[budgetEmpty]░░░░░░░░░[/]" in result
    assert " 12.3%" in result
    assert "[agentOne]●1[/]" in result
    assert "[textMuted]1 running · 2 queued[/]" in result
    assert "[textMuted]STARTING[/]" in result
    assert "[planned]" in result


def test_render_transcript_header_uses_bare_token_markup_and_omits_absent_fields() -> None:
    """Header letterspaces TRANSCRIPT, marks run state faint, and omits absent fields."""
    result = render_transcript_header("a1b2", 3, True)
    assert "T R A N S C R I P T" in result
    assert "[textFaint]run-a1b2 · 3 events · pinned[/]" in result
    plain = render_transcript_header(None, 0, False)
    assert plain == "T R A N S C R I P T  [textFaint]0 events[/]"


def test_atelier_footer_hints_wide_and_narrow() -> None:
    """Footer hints: exactly 8 keys + more indicator + full hint in wide, 4 in narrow."""
    pairs = [(f"ctrl+{index}", f"Label {index}") for index in range(12)]
    footer = AtelierFooter(pairs, id="app-footer")
    footer.narrow = True
    assert footer.narrow is True
    wide_hints, wide_hint = format_footer_hints(pairs)
    narrow_hints, narrow_hint = format_footer_hints(pairs, narrow=True)
    assert wide_hints.count("[surfaceRaised]") == 8
    assert wide_hints.endswith("⋯[/]")
    assert wide_hint == "[textMuted]? all shortcuts[/]"
    assert narrow_hints.count("[surfaceRaised]") == 4
    assert narrow_hints.endswith("⋯[/]")
    assert narrow_hint == "[textMuted]? all[/]"
