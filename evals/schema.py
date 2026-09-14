from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class ScriptedUsage(BaseModel):
    """Usage reported by one deterministic fake-provider response."""

    model_config = ConfigDict(frozen=True)

    input_tokens: int
    output_tokens: int
    cost_usd: Decimal


class ScriptedToolCall(BaseModel):
    """One model-authored tool call in an execution script."""

    model_config = ConfigDict(frozen=True)

    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    id: str


class ScriptedModelResponse(BaseModel):
    """One deterministic response, independent of the fixture's scoring oracle."""

    model_config = ConfigDict(frozen=True)

    content: str = ""
    tool_calls: tuple[ScriptedToolCall, ...] = ()
    usage: ScriptedUsage


class ExecutionScript(BaseModel):
    """Private runtime input; scoring code never supplies this to the fake model."""

    model_config = ConfigDict(frozen=True)

    responses: tuple[ScriptedModelResponse, ...] = ()
    final_response: ScriptedModelResponse
    child_response: ScriptedModelResponse | None = None


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
    execution: ExecutionScript | None = None
    oracle: OracleSpec
    route_invariants: RouteInvariants = Field(default_factory=RouteInvariants)
    metadata: dict[str, Any] = Field(default_factory=dict)
    parallel_eligible: bool = False
    expected_run_status: Literal["completed", "blocked", "failed", "cancelled"] = "completed"
    economic_eligible: bool = True

    @model_validator(mode="after")
    def validate_expected_outcome(self) -> EvaluationFixture:
        if self.expected_run_status != "completed" and self.economic_eligible:
            raise ValueError("expected-failure fixtures cannot be economic successes")
        return self


class EvaluationPolicy(StrEnum):
    AUTO = "auto"
    ECONOMY = "economy"
    QUALITY = "quality"
    SERIAL = "serial"
    NO_DELEGATION = "no_delegation"

    def controls(self) -> EvaluationPolicyControls:
        match self:
            case EvaluationPolicy.ECONOMY:
                return EvaluationPolicyControls(
                    routing_mode=RoutingMode.ECONOMY,
                    lead_model="eval-provider:eval-mini",
                    child_model="eval-provider:eval-mini",
                )
            case EvaluationPolicy.QUALITY:
                return EvaluationPolicyControls(
                    routing_mode=RoutingMode.QUALITY,
                    lead_model="eval-provider:eval-flagship",
                    child_model="eval-provider:eval-flagship",
                )
            case EvaluationPolicy.SERIAL:
                return EvaluationPolicyControls(
                    routing_mode=RoutingMode.AUTO,
                    max_children=1,
                )
            case EvaluationPolicy.NO_DELEGATION:
                return EvaluationPolicyControls(
                    routing_mode=RoutingMode.AUTO,
                    delegation="off",
                )
            case EvaluationPolicy.AUTO:
                return EvaluationPolicyControls(routing_mode=RoutingMode.AUTO)


class EvaluationPolicyControls(BaseModel):
    """Deterministic controller inputs used for one evaluation-policy run."""

    model_config = ConfigDict(frozen=True)

    routing_mode: RoutingMode
    lead_model: str | None = None
    child_model: str | None = None
    delegation: Literal["auto", "off"] = "auto"
    max_children: int = Field(default=3, ge=1, le=3)


class EvaluationRunProfile(BaseModel):
    """Frozen controls for a named, reproducible evaluation run."""

    model_config = ConfigDict(frozen=True)

    id: str
    policies: tuple[EvaluationPolicy, ...]
    paired_seeds: tuple[int, ...]
    repetitions: int = Field(ge=1)


CANONICAL_PAIRED_RUNTIME_PROFILE = EvaluationRunProfile(
    id="paired-runtime-v1",
    policies=(
        EvaluationPolicy.AUTO,
        EvaluationPolicy.ECONOMY,
        EvaluationPolicy.QUALITY,
        EvaluationPolicy.SERIAL,
        EvaluationPolicy.NO_DELEGATION,
    ),
    paired_seeds=(42, 100),
    repetitions=5,
)


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
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    fixture_id: str
    policy: EvaluationPolicy
    seed: int = Field(default=42, ge=0)
    repetition: int = Field(default=1, ge=1)
    execution_order: int = Field(default=0, ge=0)
    completed: bool
    passed_oracle: bool
    contract_passed: bool = True
    wall_time_seconds: float = Field(ge=0)
    total_cost_usd: Decimal = Field(ge=0)
    models_used: tuple[str, ...]
    assignments_count: int = Field(ge=0)
    escalations_count: int = Field(ge=0)
    interrupts_count: int = Field(ge=0)
    safety_defects: tuple[str, ...] = ()
    context_metrics: ContextEvalMetrics = Field(default_factory=ContextEvalMetrics)
    error: str | None = None
    catalog_revision: str = "default"
    provider_mode: str = "fake"
    child_wall_seconds: float = Field(default=0.0, ge=0)
    child_peak_active: int = Field(default=0, ge=0)
    child_count: int = Field(default=0, ge=0)


class ExecutedAssignment(BaseModel):
    """Stable assignment facts captured from the controller's persisted journal."""

    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    attempt_number: Literal[1, 2]
    provider: str
    model: str
    routing_mode: RoutingMode
    capability_floor: float | None
    estimated_attempt_cost_usd: Decimal = Field(ge=0)
    explanation: tuple[str, ...]
    catalog_revision: str


class RawExecutionRecord(BaseModel):
    """Immutable execution evidence captured before oracle scoring and summaries."""

    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    fixture_id: str
    policy: EvaluationPolicy
    seed: int = Field(default=42, ge=0)
    repetition: int = Field(default=1, ge=1)
    execution_order: int = Field(default=0, ge=0)
    evidence_class: Literal["synthetic_offline"] = "synthetic_offline"
    script_digest: str
    run_status: str | None = None
    error: str | None = None
    wall_time_seconds: float = Field(default=0.0, ge=0)
    usage_cost_usd: Decimal = Field(ge=0)
    usage_records: tuple[Decimal, ...] = ()
    assignments: tuple[ExecutedAssignment, ...] = ()
    workspace_files: tuple[tuple[str, str], ...] = ()
    workspace_text_files: tuple[tuple[str, str], ...] = ()
    oracle_command_exit_code: int | None = None


class PolicySummary(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    policy: EvaluationPolicy
    total_runs: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    completion_rate: float = Field(ge=0, le=1)
    oracle_pass_rate: float = Field(ge=0, le=1)
    total_cost_usd: Decimal = Field(ge=0)
    failed_work_cost_usd: Decimal = Field(default=Decimal("0.00"), ge=0)
    cost_per_successful_task_usd: Decimal | None = Field(default=None, ge=0)
    median_cost_usd: Decimal = Field(ge=0)
    mean_cost_usd: Decimal = Field(ge=0)
    median_wall_time_seconds: float = Field(ge=0)
    total_escalations: int = Field(ge=0)
    total_interrupts: int = Field(ge=0)
    safety_defect_count: int = Field(ge=0)


class PairedSpeedup(BaseModel):
    """One complete auto/serial timing pair for a parallel fixture and seed."""

    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    fixture_id: str
    seed: int
    auto_median_wall_time: float = Field(ge=0)
    serial_median_wall_time: float = Field(gt=0)
    speedup_pct: float


class EvaluationComparison(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    auto_completion_rate: float = Field(ge=0, le=1)
    quality_completion_rate: float = Field(ge=0, le=1)
    completion_delta: float
    auto_median_cost_usd: Decimal = Field(ge=0)
    quality_median_cost_usd: Decimal = Field(ge=0)
    cost_reduction_pct: float
    parallel_median_wall_time: float = Field(ge=0)
    serial_median_wall_time: float = Field(ge=0)
    speedup_pct: float
    parallel_fixture_speedups: tuple[PairedSpeedup, ...] = ()
    parallel_seed_speedups_pct: dict[int, float] = Field(default_factory=dict)
    parallel_pair_count: int = Field(default=0, ge=0)
    parallel_expected_pair_count: int = Field(default=0, ge=0)
    parallel_pairing_complete: bool = False
    parallel_cross_seed_spread_pct: float | None = Field(default=None, ge=0)
    gate_completion_passed: bool
    gate_cost_passed: bool
    gate_parallel_passed: bool
    gate_safety_passed: bool
    all_gates_passed: bool


class EvaluationProvenance(BaseModel):
    """Immutable local facts needed to reproduce an offline evaluation report."""

    model_config = ConfigDict(frozen=True)

    source_commit: str
    source_digest: str
    fixture_digest: str
    catalog_digest: str
    policy_digest: str
    operating_system: str
    python_version: str
    dependency_versions: dict[str, str]
    command: tuple[str, ...]


class EvaluationReport(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    run_id: str
    timestamp: datetime
    catalog_revision: str
    provider_mode: str
    evidence_class: Literal["synthetic_offline"] = "synthetic_offline"
    production_qualified: Literal[False] = False
    fixture_count: int = Field(ge=0)
    run_profile_id: str | None = None
    paired_seeds: tuple[int, ...] = (42,)
    repetitions: int = Field(default=1, ge=1)
    provenance: EvaluationProvenance | None = None
    policy_controls: dict[str, EvaluationPolicyControls] = Field(default_factory=dict)
    policy_summaries: dict[str, PolicySummary]
    comparison: EvaluationComparison | None = None
    results: tuple[TaskEvalResult, ...] = ()
    raw_records: tuple[RawExecutionRecord, ...] = ()
