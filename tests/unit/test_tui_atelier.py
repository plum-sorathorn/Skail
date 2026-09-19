"""Unit tests for the ATELIER chrome (dateline, transcript header, footer, plan/route)."""

from decimal import Decimal

from skail.tui.app import render_dateline, render_transcript_header
from skail.tui.projection import RouteViewItem, WorkspaceIntegrationItem
from skail.tui.widgets.footer import AtelierFooter, format_footer_hints
from skail.tui.widgets.plan import (
    PROPOSED_ACTS,
    integration_lines,
    plan_header_spaced,
    receipt_lines,
    section_head,
)
from skail.tui.widgets.route import role_floor_line, shadow_section


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
    assert wide_hints.endswith("\u22ef[/]")
    assert wide_hint == "[textMuted]? all shortcuts[/]"
    assert narrow_hints.count("[surfaceRaised]") == 4
    assert narrow_hints.endswith("\u22ef[/]")
    assert narrow_hint == "[textMuted]? all[/]"


def test_section_head_is_letterspaced_hairline() -> None:
    """Hairline heads: the label is letterspaced between hairline runs."""
    assert section_head("RECEIPTS") == "\u2500\u2500  R E C E I P T S  \u2500\u2500"
    assert section_head("ELIGIBLE") == "\u2500\u2500  E L I G I B L E  \u2500\u2500"


def test_integration_lines_render_key_value_or_nothing() -> None:
    """Integrations render as 'task: status' (+ error) and vanish when absent."""
    assert integration_lines({}) == []
    integrated = WorkspaceIntegrationItem(
        changeset_id="cs-1",
        task_id="task-1",
        attempt_id="attempt-1",
        status="integrated",
        base_head="main",
    )
    assert integration_lines({"cs-1": integrated}) == ["task-1: integrated"]
    blocked = WorkspaceIntegrationItem(
        changeset_id="cs-2",
        task_id="task-2",
        attempt_id="attempt-2",
        status="in_doubt",
        base_head="main",
        error="lease lost",
    )
    assert integration_lines({"cs-2": blocked}) == ["task-2: in_doubt \u00b7 lease lost"]


def test_receipt_lines_bullet_and_empty() -> None:
    """Each receipt becomes one bullet row; no receipts, no rows."""
    assert receipt_lines([]) == []
    assert receipt_lines(["wrote 3 files", "passed 5 checks"]) == [
        "\u00b7 wrote 3 files",
        "\u00b7 passed 5 checks",
    ]


def test_plan_header_spaced_letterspaces_only_the_word() -> None:
    """The PLAN word is letterspaced; the counts keep their compact shape."""
    assert plan_header_spaced(1, 3) == "P L A N \u00b7 1/3"
    assert plan_header_spaced(0, 0) == "P L A N \u00b7 0/0"


def test_plan_proposed_acts_copy() -> None:
    """The proposed block offers the three acts with their keys."""
    assert PROPOSED_ACTS == (
        "[underline]Accept[/underline] A / [underline]Reject[/underline] R"
        " / [underline]Change[/underline] C"
    )


def _route_item() -> RouteViewItem:
    """Minimal guaranteed-fields route item for the pure-helper tests."""
    return RouteViewItem(
        task_id="lead",
        attempt_number=1,
        model="standard-model",
        provider="fake",
        routing_mode="auto",
        capability_floor=0.7,
        estimated_cost_usd=Decimal("0.05"),
        explanation=(),
    )


def test_role_floor_line_formats_slot_and_floor() -> None:
    """The floors row shows the role and its capability floor."""
    assert role_floor_line(_route_item()) == "lead \u00b7 floor 0.70"


def test_shadow_section_eligible_when_evidence_sufficient() -> None:
    """Sufficient evidence elects the shadow candidate, with its revision."""
    item = RouteViewItem(
        task_id="lead",
        attempt_number=1,
        model="standard-model",
        provider="fake",
        routing_mode="auto",
        capability_floor=0.7,
        estimated_cost_usd=Decimal("0.05"),
        explanation=(),
        evidence_status="sufficient",
        evidence_revision="rev-9",
        shadow_recommendation="economy",
        shadow_reasons=("cheaper",),
    )
    head, lines = shadow_section(item)
    assert head == "ELIGIBLE"
    assert lines == ["SHADOW: economy (evidence rev-9)"]


def test_shadow_section_excluded_without_sufficient_evidence() -> None:
    """Without sufficient evidence the candidate is listed with its reasons."""
    item = RouteViewItem(
        task_id="lead",
        attempt_number=1,
        model="standard-model",
        provider="fake",
        routing_mode="auto",
        capability_floor=0.7,
        estimated_cost_usd=Decimal("0.05"),
        explanation=(),
        evidence_status=None,
        shadow_recommendation="economy",
        shadow_reasons=("economy candidate is cheaper",),
    )
    head, lines = shadow_section(item)
    assert head == "EXCLUDED"
    assert lines == ["SHADOW: economy", "\u00b7 economy candidate is cheaper"]


def test_shadow_section_absent_without_recommendation() -> None:
    """No shadow recommendation, no ELIGIBLE/EXCLUDED section: nothing invented."""
    assert shadow_section(_route_item()) == ("", [])
