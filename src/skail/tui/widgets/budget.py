"""Budget sidebar: meter, thresholds, per-agent costs, unavailable copy."""

from __future__ import annotations

from typing import Any

from textual.containers import VerticalScroll
from textual.widgets import Static

from skail.tui.projection import (
    BUDGET_UNAVAILABLE_COPY,
    BudgetViewItem,
    budget_view_model,
)
from skail.tui.theme import (
    BUDGET_CRITICAL_THRESHOLD,
    BUDGET_WARNING_THRESHOLD,
    budget_token_for_ratio,
)


def budget_state_label(state: Any) -> str:
    """Display label for a budget state (normal/NEAR LIMIT/CRITICAL/...)."""
    text = str(state).strip().lower()
    if text in ("near", "near limit", "near_limit"):
        return "NEAR LIMIT"
    if text == "critical":
        return "CRITICAL"
    if text in ("exceeded", "limit reached", "limit_reached"):
        return "LIMIT REACHED"
    return "normal"


def render_budget_lines(
    used: float, limit: float | None, per_agent: dict[str, float] | None = None
) -> list[str]:
    """Pure budget lines including meter, pct, per-agent costs, Remaining."""
    if limit is None:
        return [BUDGET_UNAVAILABLE_COPY]
    model = budget_view_model(float(used), float(limit))
    lines = [
        "BUDGET",
        f"Session ${float(used):.2f} / ${float(limit):.2f}",
        f"{model.cells} {model.pct:.1f}%",
        budget_state_label(model.state),
    ]
    for agent_id, cost in sorted(
        (per_agent or {}).items(), key=lambda kv: kv[1], reverse=True
    ):
        lines.append(f"{agent_id}: ${float(cost):.2f}")
    lines.append(f"Remaining: ${max(float(limit) - float(used), 0.0):.2f}")
    return lines


_LEDGER_CELLS = 23
_LEDGER_INNER_WIDTH = 35
_LEDGER_FILLED = "▓"
_LEDGER_EMPTY = "░"


def render_ledger_lines(item: BudgetViewItem) -> list[str]:
    """ATELIER margin LEDGER (redesign §6): header, spend, 23-cell meter, thresholds.

    Lines carry bare theme token names ([textMuted], [budgetFill], ...) resolved at
    paint time; only fields the projection supplies are shown.
    """
    used = (
        item.authoritative_actual_usd
        + item.estimated_actual_usd
        + item.reserved_usd
        + item.unknown_cost_usd
    )
    limit = item.hard_limit_usd
    ratio: float | None = None
    if limit is not None and float(limit) > 0:
        ratio = float(used) / float(limit)
    token = budget_token_for_ratio(ratio)

    lead = "──"
    pad = "─" * (_LEDGER_INNER_WIDTH - len(lead) - 1 - len("LEDGER"))
    header = f"[textFaint]{lead}[/] LEDGER [textFaint]{pad}[/]"

    if limit is not None:
        money = f"${float(used):.4f} of ${float(limit):.2f}"
        if ratio is not None:
            pct = f"{ratio * 100:.1f}%"
            gap = max(2, _LEDGER_INNER_WIDTH - len(money) - len(pct))
            spend = f"[textMuted]{money}[/]{' ' * gap}[textFaint]{pct}[/]"
        else:
            spend = f"[textMuted]{money}[/]"
    else:
        spend = f"[textMuted]${float(used):.4f} of —[/]"

    filled = 0 if ratio is None else min(int(ratio * _LEDGER_CELLS), _LEDGER_CELLS)
    parts: list[str] = []
    if filled:
        parts.append(f"[{token}]{_LEDGER_FILLED * filled}[/]")
    spare = _LEDGER_CELLS - filled
    if spare:
        parts.append(f"[budgetEmpty]{_LEDGER_EMPTY * spare}[/]")

    thresholds = (
        "[textFaint]warn ┊ "
        f"{BUDGET_WARNING_THRESHOLD * 100:.0f}%   "
        f"critical ┊ {BUDGET_CRITICAL_THRESHOLD * 100:.0f}%[/]"
    )
    return [header, spend, "".join(parts), thresholds]


class BudgetLedger(Static):
    """ATELIER margin LEDGER: always-visible spend block under #tabs."""

    DEFAULT_CSS = """
    BudgetLedger {
        height: auto;
        padding: 0 1;
    }
    """

    def update_budget(self, item: BudgetViewItem) -> None:
        """Re-render the ledger from the projection's budget item."""
        self.update("\n".join(render_ledger_lines(item)))


def _hairline_head(label: str, *, spaced: bool = False) -> str:
    """Hairline section head: faint rule, label, faint filler (redesign §6)."""
    text = " ".join(label) if spaced else label
    pad = "─" * (_LEDGER_INNER_WIDTH - 2 - 1 - len(text) - 1)
    return f"[textFaint]──[/] {text} [textFaint]{pad}[/]"


def budget_meter_markup(ratio: float | None, cells: int = _LEDGER_CELLS) -> str:
    """23-cell ▓/░ meter markup; fill token flips at 0.75/0.90 via the theme."""
    if ratio is None:
        return f"[budgetEmpty]{_LEDGER_EMPTY * cells}[/]"
    filled = min(int(ratio * cells), cells)
    parts: list[str] = []
    if filled:
        parts.append(f"[{budget_token_for_ratio(ratio)}]{_LEDGER_FILLED * filled}[/]")
    spare = cells - filled
    if spare:
        parts.append(f"[budgetEmpty]{_LEDGER_EMPTY * spare}[/]")
    return "".join(parts)


def budget_threshold_legend() -> str:
    """Legend line: ``thresholds 0.75 / 0.90`` from the theme constants."""
    return (
        "[textFaint]thresholds "
        f"{BUDGET_WARNING_THRESHOLD:.2f} / {BUDGET_CRITICAL_THRESHOLD:.2f}[/]"
    )


def budget_breakdown_lines(item: BudgetViewItem) -> list[str]:
    """BREAKDOWN kv rows: only the four cost components the projection supplies.

    Never invents values: reserved / authoritative / estimated / unknown, 4dp.
    """
    fields = (
        ("reserved", item.reserved_usd),
        ("authoritative", item.authoritative_actual_usd),
        ("estimated", item.estimated_actual_usd),
        ("unknown", item.unknown_cost_usd),
    )
    lines = [_hairline_head("BREAKDOWN")]
    lines.extend(
        f"  [textFaint]{name:<13}[/] [textMuted]${float(value):.4f}[/]"
        for name, value in fields
    )
    return lines


def budget_panel_lines(item: BudgetViewItem) -> list[str]:
    """ATELIER BUDGET tab body: money, 23-cell meter, thresholds, BREAKDOWN.

    When the projection supplies no hard limit, only the unavailable copy is
    returned; supplied components are never augmented with invented fields.
    """
    limit = item.hard_limit_usd
    if limit is None:
        return [BUDGET_UNAVAILABLE_COPY]
    used = (
        item.authoritative_actual_usd
        + item.estimated_actual_usd
        + item.reserved_usd
        + item.unknown_cost_usd
    )
    ratio = float(used) / float(limit) if float(limit) > 0 else 0.0
    money = f"${float(used):.4f} of ${float(limit):.2f}"
    pct = f"{ratio * 100:.1f}%"
    gap = max(2, _LEDGER_INNER_WIDTH - len(money) - len(pct))
    return [
        f"[textMuted]{money}[/]{' ' * gap}[textFaint]{pct}[/]",
        budget_meter_markup(ratio),
        budget_threshold_legend(),
        *budget_breakdown_lines(item),
    ]


class BudgetView(VerticalScroll):
    """ATELIER BUDGET tab: hairline head, money, 23-cell meter, legend, BREAKDOWN."""

    can_focus = False

    DEFAULT_CSS = """
    BudgetView {
        width: 100%;
        height: 100%;
        padding: 0 1;
        scrollbar-size: 1 1;
    }
    BudgetView:focus-within {
        outline: solid $focusRing;
    }
    .budget-header {
        text-style: bold;
        color: $accent;
        padding-bottom: 1;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.item: BudgetViewItem = BudgetViewItem()
        self.budget_available: bool = True

    def update_budget(
        self, item: BudgetViewItem | None, budget_available: bool = True
    ) -> None:
        if item is not None:
            self.item = item
        self.budget_available = budget_available
        try:
            self.remove_children()
            self.mount(
                Static(_hairline_head("BUDGET", spaced=True), classes="budget-header")
            )
            if not budget_available or item is None:
                self.mount(Static(BUDGET_UNAVAILABLE_COPY))
                return
            for line in budget_panel_lines(item):
                self.mount(Static(line))
        except Exception:
            pass


__all__ = [
    "BudgetLedger",
    "BudgetView",
    "budget_breakdown_lines",
    "budget_meter_markup",
    "budget_panel_lines",
    "budget_state_label",
    "budget_threshold_legend",
    "render_budget_lines",
    "render_ledger_lines",
]
