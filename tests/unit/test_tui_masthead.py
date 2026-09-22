"""Unit tests for the ATELIER masthead formatter."""

from skail import __version__
from skail.tui.app import format_masthead


def test_format_masthead_contains_wordmark_version_and_provider() -> None:
    """Masthead row starts with the letterspaced wordmark and carries version/provider."""
    result = format_masthead(__version__, "fake", "12:00:00")
    assert result.startswith("S K A I L")
    assert __version__ in result
    assert "  fake" in result
