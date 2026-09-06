from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from rudder.domain.routing import RoutingMode
from rudder.domain.tasks import CapabilityRequirements


class TaskRisk(StrEnum):
    TRIVIAL = "trivial"
    ROUTINE = "routine"
    BOUNDED = "bounded"
    COMPLEX = "complex"
    HIGH = "high-risk"


ROLE_FLOORS: dict[str, float] = {
    "explorer": 0.35,
    "tester": 0.40,
    "researcher": 0.45,
    "general-purpose": 0.50,
    "implementer": 0.50,
    "reviewer": 0.55,
    "lead": 0.60,
}
RISK_FLOORS: dict[TaskRisk, float] = {
    TaskRisk.TRIVIAL: 0.25,
    TaskRisk.ROUTINE: 0.35,
    TaskRisk.BOUNDED: 0.45,
    TaskRisk.COMPLEX: 0.60,
    TaskRisk.HIGH: 0.70,
}
MODE_ADJUSTMENTS: dict[RoutingMode, float] = {
    RoutingMode.AUTO: 0.0,
    RoutingMode.ECONOMY: -0.10,
    RoutingMode.QUALITY: 0.15,
    RoutingMode.MANUAL: 0.0,
}


class RoutingRequirements(CapabilityRequirements):
    role: str
    risk: TaskRisk
    mode: RoutingMode
    role_hard_min: float = Field(ge=0, le=1)
    escalated: bool = False
    excluded_models: frozenset[tuple[str, str]] = frozenset()


class RequirementBuilder:
    def for_assignment(
        self,
        base: CapabilityRequirements,
        *,
        role: str,
        risk: TaskRisk,
        mode: RoutingMode,
        role_hard_min: float,
        escalated: bool = False,
        failed_model: tuple[str, str] | None = None,
        excluded_models: frozenset[tuple[str, str]] = frozenset(),
    ) -> RoutingRequirements:
        """Carry validated task requirements into an assignment-specific route decision."""
        return self.build(
            role=role,
            risk=risk,
            mode=mode,
            role_hard_min=role_hard_min,
            required_tools=base.tools_required,
            required_structured_output=base.structured_output_required,
            required_context_tokens=base.minimum_context_tokens,
            required_output_tokens=base.minimum_output_tokens,
            required_modalities=frozenset(base.modalities),
            hinted_floor=base.capability_floor,
            escalated=escalated,
            failed_model=failed_model,
            excluded_models=excluded_models,
        )

    def build(
        self,
        *,
        role: str,
        risk: TaskRisk,
        mode: RoutingMode = RoutingMode.AUTO,
        role_hard_min: float = 0.0,
        required_tools: bool = False,
        required_structured_output: bool = False,
        required_context_tokens: int = 0,
        required_output_tokens: int = 0,
        required_modalities: frozenset[str] = frozenset({"text"}),
        hinted_floor: float | None = None,
        hinted_context_tokens: int = 0,
        hinted_output_tokens: int = 0,
        hinted_modalities: frozenset[str] = frozenset(),
        escalated: bool = False,
        failed_model: tuple[str, str] | None = None,
        excluded_models: frozenset[tuple[str, str]] = frozenset(),
    ) -> RoutingRequirements:
        if role not in ROLE_FLOORS:
            raise ValueError(f"unknown routing role: {role}")
        if not 0 <= role_hard_min <= ROLE_FLOORS[role]:
            raise ValueError("role_hard_min must be between zero and the role floor")
        base = max(ROLE_FLOORS[role], RISK_FLOORS[risk])
        if hinted_floor is not None:
            if not 0 <= hinted_floor <= 1:
                raise ValueError("hinted_floor must be between zero and one")
            base = max(base, hinted_floor)
        floor: float | None
        if mode is RoutingMode.MANUAL:
            floor = None
        else:
            floor = base + MODE_ADJUSTMENTS[mode] + (0.15 if escalated else 0.0)
            floor = round(min(max(floor, role_hard_min), 0.90 if escalated else 0.85), 2)
        exclusions = set(excluded_models)
        if failed_model is not None:
            exclusions.add(failed_model)
        return RoutingRequirements(
            role=role,
            risk=risk,
            mode=mode,
            capability_floor=floor,
            role_hard_min=role_hard_min,
            tools_required=required_tools,
            structured_output_required=required_structured_output,
            minimum_context_tokens=max(required_context_tokens, hinted_context_tokens),
            minimum_output_tokens=max(required_output_tokens, hinted_output_tokens),
            modalities=tuple(sorted(required_modalities | hinted_modalities)),
            escalated=escalated,
            excluded_models=frozenset(exclusions),
        )
