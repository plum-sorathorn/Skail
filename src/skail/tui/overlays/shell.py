"""Shared ATELIER dressing for the overlay screens (region 15).

Every overlay screen composes the same 3-part shell -- a ``.ovl-head`` row
(letterspaced bold title + right-aligned faint action hint), a
``.ovl-rule-strong`` double rule, and a faint ``.ovl-foot`` note -- over a
translucent ``$surfaceInset 80%`` page. ``Screen`` is deliberately not
migrated to ``ModalScreen``: the unit tests drive these screens via doubles,
and the ``$surfaceInset 80%`` backdrop already reads as the dim.
"""

from __future__ import annotations

from typing import Any

OVERLAY_CSS = """\
/* Shared overlay dressing (region 15). */
Screen {
    background: $surfaceInset 80%;
}
.ovl-head {
    height: 1;
    color: $textFaint;
}
.ovl-head .ovl-title {
    width: 1fr;
    color: $text;
    text-style: bold;
}
.ovl-head .ovl-hint {
    width: auto;
}
.ovl-rule-strong {
    height: 1;
    border-bottom: double $borderStrong;
}
.ovl-foot {
    height: 1;
    color: $textFaint;
}
.ovl-grid {
    height: 1fr;
}
.ovl-col {
    width: 36;
    height: 1fr;
    overflow-y: auto;
}
.ovl-grid .hairline {
    width: 1;
    height: 100%;
    background: $border;
}
"""


def letterspaced(title: str) -> str:
    """Bake the letterspacing in: ``SHORTCUTS`` -> ``S H O R T C U T S``."""
    return " ".join(title)


def ovl_head(title: str, hint: str) -> Any:
    """1-row head: bold letterspaced title left, faint action hint right."""
    from textual.containers import Horizontal
    from textual.widgets import Static

    return Horizontal(
        Static(letterspaced(title), classes="ovl-title"),
        Static(hint, classes="ovl-hint"),
        classes="ovl-head",
    )


def ovl_rule_strong() -> Any:
    """1-row strong rule: border-bottom double $borderStrong."""
    from textual.widgets import Static

    return Static("", classes="ovl-rule-strong")


def ovl_foot(note: str) -> Any:
    """1-row faint footnote."""
    from textual.widgets import Static

    return Static(note, classes="ovl-foot")


__all__ = ["OVERLAY_CSS", "letterspaced", "ovl_foot", "ovl_head", "ovl_rule_strong"]
