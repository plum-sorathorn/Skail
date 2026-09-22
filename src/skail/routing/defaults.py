from __future__ import annotations

from decimal import Decimal
from typing import Final

from skail.domain.routing import RoutingMode
from skail.routing.requirements import MODE_ADJUSTMENTS, RISK_FLOORS, ROLE_FLOORS, TaskRisk

DEFAULT_ROUTING_MODE: Final[RoutingMode] = RoutingMode.AUTO
DEFAULT_MAX_CHILDREN: Final[int] = 3
DEFAULT_BUDGET_USD: Final[Decimal] = Decimal("10.00")

DEFAULT_ROLE_FLOORS: Final[dict[str, float]] = ROLE_FLOORS
DEFAULT_RISK_FLOORS: Final[dict[TaskRisk, float]] = RISK_FLOORS
DEFAULT_MODE_ADJUSTMENTS: Final[dict[RoutingMode, float]] = MODE_ADJUSTMENTS

# Evaluated numerical gates per SPEC.md Section 21
COMPLETION_MARGIN_GATE_PCT: Final[float] = 5.0  # within 5 percentage points
COST_REDUCTION_GATE_PCT: Final[float] = 20.0    # at least 20% reduction
PARALLEL_SPEEDUP_GATE_PCT: Final[float] = 15.0  # at least 15% speedup
SAFETY_DEFECTS_ALLOWED: Final[int] = 0          # zero defects
