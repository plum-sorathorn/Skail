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
    model_config = ConfigDict(frozen=True)

    fixture_id: str
    policy: EvaluationPolicy
    seed: int = 42
    repetition: int = 1
    execution_order: int = 0
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


class ExecutedAssignment(BaseModel):
    """Stable assignment facts captured from the controller's persisted journal."""

    model_config = ConfigDict(frozen=True)

    attempt_number: Literal[1, 2]
    provider: str
    model: str
    routing_mode: RoutingMode
    capability_floor: float | None
    estimated_attempt_cost_usd: Decimal
    explanation: tuple[str, ...]
    catalog_revision: str


class RawExecutionRecord(BaseModel):
    """Immutable execution evidence captured before oracle scoring and summaries."""

    model_config = ConfigDict(frozen=True)

    fixture_id: str
    policy: EvaluationPolicy
    seed: int = 42
    repetition: int = 1
    execution_order: int = 0
    evidence_class: Literal["synthetic_offline"] = "synthetic_offline"
    script_digest: str
    run_status: str | None = None
    error: str | None = None
    usage_cost_usd: Decimal
    usage_records: tuple[Decimal, ...] = ()
    assignments: tuple[ExecutedAssignment, ...] = ()
    workspace_files: tuple[tuple[str, str], ...] = ()


class PolicySummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy: EvaluationPolicy
    total_runs: int
    completed_count: int
    completion_rate: float
    oracle_pass_rate: float
    total_cost_usd: Decimal
    failed_work_cost_usd: Decimal = Decimal("0.00")
    cost_per_successful_task_usd: Decimal | None = None
    median_cost_usd: Decimal
    mean_cost_usd: Decimal
    median_wall_time_seconds: float
    total_escalations: int
    total_interrupts: int
    safety_defect_count: int


class PairedSpeedup(BaseModel):
    """One complete auto/serial timing pair for a parallel fixture and seed."""

    model_config = ConfigDict(frozen=True)

    fixture_id: str
    seed: int
    auto_median_wall_time: float
    serial_median_wall_time: float
    speedup_pct: float


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
    parallel_fixture_speedups: tuple[PairedSpeedup, ...] = ()
    parallel_seed_speedups_pct: dict[int, float] = Field(default_factory=dict)
    parallel_pair_count: int = 0
    parallel_expected_pair_count: int = 0
    parallel_pairing_complete: bool = False
    parallel_cross_seed_spread_pct: float | None = None
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
    model_config = ConfigDict(frozen=True)

    run_id: str
    timestamp: datetime
    catalog_revision: str
    provider_mode: str
    evidence_class: Literal["synthetic_offline"] = "synthetic_offline"
    production_qualified: Literal[False] = False
    fixture_count: int
    run_profile_id: str | None = None
    paired_seeds: tuple[int, ...] = (42,)
    repetitions: int = 1
    provenance: EvaluationProvenance | None = None
    policy_controls: dict[str, EvaluationPolicyControls] = Field(default_factory=dict)
    policy_summaries: dict[str, PolicySummary]
    comparison: EvaluationComparison | None = None
    results: tuple[TaskEvalResult, ...] = ()
    raw_records: tuple[RawExecutionRecord, ...] = ()
