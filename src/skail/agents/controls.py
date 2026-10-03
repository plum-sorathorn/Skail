from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from skail.domain.decisions import ExecutionMode
from skail.domain.routing import RoutingMode
from skail.routing.requirements import TaskRisk

DelegationMode = Literal["auto", "ask", "off"]


@dataclass(frozen=True)
class LeadControls:
    delegation: DelegationMode = "auto"
    model: str | None = None
    profile: str | None = None
    write_allowed: bool | None = None
    max_children: int = 3
    direct_only: bool = False
    required_mode: ExecutionMode | None = None
    requires_user_answer: bool = False
    required_agent_count: int | None = None
    required_agent_profile: str | None = None
    routing_mode: RoutingMode = RoutingMode.AUTO
    risk: TaskRisk = TaskRisk.ROUTINE
