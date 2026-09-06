from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rudder.domain.plans import EffectScope, ExecutionPlan, PlanNodeKind


class ExecutionMode(StrEnum):
    DIRECT = "direct"
    DISCOVERY = "discovery"
    PLANNED = "planned"


class ExecutionDecision(BaseModel):
    """The lead's typed choice of how a run should proceed."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    mode: ExecutionMode
    objective: str = Field(min_length=1)
    constraints: tuple[str, ...] = ()
    reason: str = Field(min_length=1)
    plan: ExecutionPlan | None = None

    @model_validator(mode="after")
    def validate_mode(self) -> ExecutionDecision:
        if self.mode is ExecutionMode.DIRECT:
            if self.plan is not None:
                raise ValueError("decision.direct_plan_forbidden")
            return self
        if self.plan is None:
            raise ValueError("decision.plan_required")
        if self.mode is ExecutionMode.DISCOVERY:
            if not any(node.kind is PlanNodeKind.CHECKPOINT for node in self.plan.nodes):
                raise ValueError("decision.discovery_checkpoint_required")
            if any(node.effect_scope is not EffectScope.READ for node in self.plan.nodes):
                raise ValueError("decision.discovery_effect_forbidden")
        return self
