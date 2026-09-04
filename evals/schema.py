from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from rudder.domain.routing import RoutingMode
from rudder.routing.requirements import TaskRisk


class OracleType(StrEnum):
    FILE_EXISTS = "file_exists"
    FILE_CONTAINS = "file_contains"
    FILE_CONTENT = "file_content"
    COMMAND_EXIT_ZERO = "command_exit_zero"
    MULTI_ASSERT = "multi_assert"


class OracleSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: OracleType
    target: str = ""
    expected: str | None = None
    command: str | None = None
    assertions: tuple[dict[str, Any], ...] = ()


class RouteInvariants(BaseModel):
    model_config = ConfigDict(frozen=True)

    min_floor: float | None = None
    expected_model: str | None = None
    forbid_models: tuple[str, ...] = ()
    max_cost_usd: Decimal | None = None
    allow_delegation: bool = True
    parallel_eligible: bool = False
    required_role: str | None = None


class EvaluationFixture(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    category: Literal[
        "trivial",
        "routine",
        "bounded",
        "complex",
        "high_risk",
        "parallel",
        "failure",
    ]
    role: str = "implementer"
    risk: TaskRisk = TaskRisk.ROUTINE
    prompt: str
    initial_files: dict[str, str] = Field(default_factory=dict)
    allowed_tools: tuple[str, ...] = ()
    oracle: OracleSpec
    route_invariants: RouteInvariants = Field(default_factory=RouteInvariants)
    metadata: dict[str, Any] = Field(default_factory=dict)
    parallel_eligible: bool = False


class EvaluationPolicy(StrEnum):
    AUTO = "auto"
    ECONOMY = "economy"
    QUALITY = "quality"
    SERIAL = "serial"
    NO_DELEGATION = "no_delegation"

    def to_routing_mode(self) -> RoutingMode:
        match self:
            case EvaluationPolicy.AUTO:
                return RoutingMode.AUTO
            case EvaluationPolicy.ECONOMY:
                return RoutingMode.ECONOMY
            case EvaluationPolicy.QUALITY:
                return RoutingMode.QUALITY
            case EvaluationPolicy.SERIAL:
                return RoutingMode.AUTO
            case EvaluationPolicy.NO_DELEGATION:
                return RoutingMode.AUTO


class ContextEvalMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    estimated_tokens: int = 0
    selected_tokens: int = 0
    compressed_tokens: int = 0
    dropped_tokens: int = 0
    omissions_count: int = 0
    artifact_retrievals: int = 0
    handoff_bytes: int = 0


class TaskEvalResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    fixture_id: str
    policy: EvaluationPolicy
    completed: bool
    passed_oracle: bool
    wall_time_seconds: float
    total_cost_usd: Decimal
    models_used: tuple[str, ...]
    assignments_count: int
    escalations_count: int
    interrupts_count: int
    safety_defects: tuple[str, ...] = ()
    context_metrics: ContextEvalMetrics = Field(default_factory=ContextEvalMetrics)
    error: str | None = None
    catalog_revision: str = "default"
    provider_mode: str = "fake"
    child_wall_seconds: float = 0.0
    child_peak_active: int = 0
    child_count: int = 0


class PolicySummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy: EvaluationPolicy
    total_runs: int
    completed_count: int
    completion_rate: float
    oracle_pass_rate: float
    total_cost_usd: Decimal
    median_cost_usd: Decimal
    mean_cost_usd: Decimal
    median_wall_time_seconds: float
    total_escalations: int
    total_interrupts: int
    safety_defect_count: int


class EvaluationComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    auto_completion_rate: float
    quality_completion_rate: float
    completion_delta: float
    auto_median_cost_usd: Decimal
    quality_median_cost_usd: Decimal
    cost_reduction_pct: float
    parallel_median_wall_time: float
    serial_median_wall_time: float
    speedup_pct: float
    gate_completion_passed: bool
    gate_cost_passed: bool
    gate_parallel_passed: bool
    gate_safety_passed: bool
    all_gates_passed: bool


class EvaluationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    timestamp: datetime
    catalog_revision: str
    provider_mode: str
    fixture_count: int
    policy_summaries: dict[str, PolicySummary]
    comparison: EvaluationComparison | None = None
    results: tuple[TaskEvalResult, ...] = ()
