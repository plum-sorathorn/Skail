"""Unit tests for the ATELIER chrome (dateline, transcript header, footer, plan/route)."""

from dataclasses import replace
from decimal import Decimal

from skail.tui.app import render_dateline, render_transcript_header
from skail.tui.projection import RouteViewItem, WorkspaceIntegrationItem
from skail.tui.widgets.footer import AtelierFooter, format_footer_hints
from skail.tui.widgets.plan import (
    PROPOSED_ACTS,
    integration_lines,
    plan_header_spaced,
    plan_header_state,
    receipt_lines,
    revision_lines,
    section_head,
)
from skail.tui.widgets.route import (
    policy_lead_line,
    role_floor_line,
    role_floor_lines,
    shadow_section,
)


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


def test_integration_lines_render_glyph_name_status_or_nothing() -> None:
    """Integrations render the ATELIER glyph+name+status row and vanish when absent."""
    assert integration_lines({}) == []
    integrated = WorkspaceIntegrationItem(
        changeset_id="cs-1",
        task_id="task-1",
        attempt_id="attempt-1",
        status="integrated",
        base_head="main",
    )
    assert integration_lines({"cs-1": integrated}) == ["\u2713 task-1 \u00b7 integrated"]
    blocked = WorkspaceIntegrationItem(
        changeset_id="cs-2",
        task_id="task-2",
        attempt_id="attempt-2",
        status="in_doubt",
        base_head="main",
        error="lease lost",
    )
    assert integration_lines({"cs-2": blocked}) == ["? task-2 \u00b7 in_doubt \u00b7 lease lost"]
    unnamed = WorkspaceIntegrationItem(
        changeset_id="cs-3",
        task_id="",
        attempt_id="attempt-3",
        status="applying",
        base_head="main",
    )
    assert integration_lines({"cs-3": unnamed}) == ["\u258c cs-3 \u00b7 applying"]


def test_receipt_lines_bold_primary_and_faint_continuation() -> None:
    """Each receipt renders a bold checked primary; extra lines become faint continuations."""
    assert receipt_lines([]) == []
    assert receipt_lines(["wrote 3 files", "passed 5 checks"]) == [
        "[b]\u2713 wrote 3 files[/]",
        "[b]\u2713 passed 5 checks[/]",
    ]
    # mirrors the fork receipt's newline layout (commands.fork_receipt)
    forked = receipt_lines(
        ["Session forked: 01JDEF\nResume this fork with:\nskail -r 01JDEF"]
    )
    assert forked == [
        "[b]\u2713 Session forked: 01JDEF[/]",
        "[textFaint]  Resume this fork with:[/]",
        "[textFaint]  skail -r 01JDEF[/]",
    ]


def test_plan_header_spaced_letterspaces_only_the_word() -> None:
    """The PLAN word is letterspaced; the counts keep their compact shape."""
    assert plan_header_spaced(1, 3) == "P L A N \u00b7 1/3"
    assert plan_header_spaced(0, 0) == "P L A N \u00b7 0/0"


def test_plan_header_state_appends_the_plan_state_word() -> None:
    """The header carries the current plan state; 'none' keeps the counts alone."""
    assert plan_header_state(1, 3, "accepted") == "P L A N \u00b7 1/3 \u00b7 accepted"
    assert plan_header_state(0, 0, "none") == "P L A N \u00b7 0/0"
    assert plan_header_state(2, 5, "") == "P L A N \u00b7 2/5"


def test_revision_lines_current_plus_receipt_carried_history() -> None:
    """REVISIONS shows the current revision + state; history only from receipt arrows."""
    assert revision_lines(None, None, "none", []) == []
    assert revision_lines(None, 1, "none", []) == []
    assert revision_lines("plan-3", 1, "none", []) == ["plan-3 \u00b7 r1"]
    assert revision_lines("plan-3", 2, "accepted", []) == ["plan-3 \u00b7 r2 \u00b7 accepted"]
    # receipts without the 'r1 -> r2' shape: just the current revision, no invented history
    assert revision_lines("plan-3", 2, "accepted", ["wrote 3 files", "passed 5 checks"]) == [
        "plan-3 \u00b7 r2 \u00b7 accepted"
    ]
    assert revision_lines("plan-3", 2, "accepted", ["r1 \u2192 r2: answers leveraged"]) == [
        "plan-3 \u00b7 r2 \u00b7 accepted",
        "[textFaint]  r1 \u2192 r2[/]",
    ]
    assert revision_lines(None, 2, "proposed", ["r1 -> r2 answers leveraged"]) == [
        "r2 \u00b7 proposed",
        "[textFaint]  r1 -> r2[/]",
    ]


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
    assert lines == ["economy \u00b7 evidence rev-9"]


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
    assert lines == ["economy \u00b7 economy candidate is cheaper"]


def test_shadow_section_absent_without_recommendation() -> None:
    """No shadow recommendation, no ELIGIBLE/EXCLUDED section: nothing invented."""
    assert shadow_section(_route_item()) == ("", [])


def test_shadow_section_excluded_joins_multiple_reasons() -> None:
    """Carried reasons join the candidate on one middle-dot detail line."""
    item = replace(
        _route_item(),
        evidence_status=None,
        shadow_recommendation="economy",
        shadow_reasons=("cheaper", "faster"),
    )
    head, lines = shadow_section(item)
    assert head == "EXCLUDED"
    assert lines == ["economy \u00b7 cheaper \u00b7 faster"]


def test_role_floor_lines_render_every_carried_floor() -> None:
    """One row per carried floor; the 0.50 projection default means not carried."""
    routes = {
        "lead": _route_item(),
        "t2": replace(_route_item(), task_id="t2", capability_floor=0.5),
        "t3": replace(_route_item(), task_id="t3", capability_floor=0.9),
    }
    assert role_floor_lines(routes) == ["lead \u00b7 floor 0.70", "t3 \u00b7 floor 0.90"]
    assert role_floor_lines({"lead": routes["t2"]}) == []
    assert role_floor_lines({}) == []


def test_policy_lead_line_mode_then_slot() -> None:
    """The policy lead row reads mode then slot under a 'policy' label."""
    assert policy_lead_line(_route_item()) == "policy: auto \u2192 lead"
    assert policy_lead_line(replace(_route_item(), task_id="")) == "policy: auto \u2192 lead"
