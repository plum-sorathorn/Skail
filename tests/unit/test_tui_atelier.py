"""Unit tests for the ATELIER chrome (dateline)."""

from skail.tui.app import render_dateline


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
