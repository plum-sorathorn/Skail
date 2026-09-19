"""Unit tests for the ATELIER chrome (dateline)."""

from skail.tui.app import render_dateline, render_transcript_header


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
