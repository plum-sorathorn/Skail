"""Budget sidebar: meter, thresholds, per-agent costs, unavailable copy."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from textual.containers import VerticalScroll
from textual.widgets import Static

from skail.tui.projection import (
    BUDGET_UNAVAILABLE_COPY,
    BudgetViewItem,
    budget_meter,
    budget_view_model,
)
from skail.tui.theme import (
    BUDGET_CRITICAL_THRESHOLD,
    BUDGET_WARNING_THRESHOLD,
    budget_token_for_ratio,
    lookup,
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


class BudgetView(VerticalScroll):
    """Budget panel driven by ``budget_view_model`` + ``budget_meter``."""

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
            self.mount(Static("BUDGET & USAGE", classes="budget-header"))
            if not budget_available or item is None:
                self.mount(Static(BUDGET_UNAVAILABLE_COPY))
                return
            limit = item.hard_limit_usd
            if limit is None:
                self.mount(Static(BUDGET_UNAVAILABLE_COPY))
                return
            used = (
                float(item.authoritative_actual_usd)
                + float(item.estimated_actual_usd)
                + float(item.reserved_usd)
                + float(item.unknown_cost_usd)
            )
            ratio = used / float(limit) if float(limit) > 0 else 0.0
            model = budget_view_model(used, float(limit))
            meter = budget_meter(used, float(limit))
            token = budget_token_for_ratio(ratio)
            try:
                from skail.tui.theme import get_theme

                _ = lookup(get_theme("dark"), token)
            except Exception:
                pass
            label = budget_state_label(model.state)
            per_agent = {
                str(k): float(v) for k, v in (item.per_agent_costs or {}).items()
            }
            lines = render_budget_lines(used, float(limit), per_agent)
            for line in lines:
                if line == label and label != "normal":
                    self.mount(Static(f"[{token}]{line}[/{token}]"))
                elif line == meter or line.startswith("■■") or "■" in line:
                    self.mount(Static(f"[{token}]{line}[/{token}]"))
                else:
                    self.mount(Static(line))
            if isinstance(item.hard_limit_usd, Decimal):
                pass
        except Exception:
            pass


__all__ = [
    "BudgetLedger",
    "BudgetView",
    "budget_state_label",
    "render_budget_lines",
    "render_ledger_lines",
]
