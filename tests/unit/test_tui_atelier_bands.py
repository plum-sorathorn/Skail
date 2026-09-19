"""ATELIER Phase 5: the approval renders as the full-bleed band, not a box.

Contract: ids/classes survive, the round-box Button variants are gone,
TCSS is the band styling (IMPLEMENTATION_PLAN.md §7.1).
"""

from __future__ import annotations

import inspect

from skail.tui.widgets.interrupts import InterruptWidget


def test_interrupt_widget_uses_band_tcss() -> None:
    css = InterruptWidget.DEFAULT_CSS
    assert "background: $approvalSurface;" in css
    assert "border: none;" in css
    assert "border-left: heavy $approval;" in css
    assert "padding: 1 2;" in css
    assert "border-bottom: dashed $borderStrong;" in css
    assert "border-left: heavy $focusRing;" in css
    assert "text-style: underline;" in css
    assert ": round" not in css
    assert "outline" not in css


def test_interrupt_acts_are_flat_underlined_words() -> None:
    src = inspect.getsource(InterruptWidget.compose)
    assert '"Approve A"' in src
    assert '"Reject R"' in src
    assert '"Add instruction E"' in src
    assert "esc keeps pending" in src
    assert "variant=" not in src


def test_interrupt_contract_ids_and_classes_kept() -> None:
    src = inspect.getsource(InterruptWidget)
    for selector in ("#btn-approve", "#btn-reject", "#btn-instruct",
                     "#interrupt-input", "approved", "rejected"):
        assert selector in src
