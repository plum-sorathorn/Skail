from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

SUPPORTED_PLAN_SCHEMA_VERSION = 1
SUPPORTED_EXECUTION_POLICY_VERSION = "adaptive-v1"


class PlanValidationError(ValueError):
    pass


class PlanNodeKind(StrEnum):
    AGENT = "agent"
    TOOL = "tool"
    VERIFICATION = "verification"
    INTEGRATION = "integration"
    CHECKPOINT = "checkpoint"


class PlanNodeState(StrEnum):
    WAITING = "waiting"
    READY = "ready"
    LAUNCHING = "launching"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class EffectScope(StrEnum):
    READ = "read"
    WORKSPACE_WRITE = "workspace_write"
    EXTERNAL_WRITE = "external_write"
    UNKNOWN = "unknown"


class PlanNode(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    local_id: str = Field(min_length=1)
    kind: PlanNodeKind
    objective: str = Field(min_length=1)
    depends_on: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()
    output_contract: str | None = None
    effect_scope: EffectScope = EffectScope.READ
    resource_scopes: tuple[str, ...] = ()
    task_features: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: tuple[str, ...] = ()
    task_lineage: str | None = None


class ExecutionPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    schema_version: int = Field(ge=1)
    policy_version: str = Field(min_length=1)
    revision: int = Field(ge=1)
    nodes: tuple[PlanNode, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_graph(self) -> ExecutionPlan:
        nodes = {node.local_id: node for node in self.nodes}
        if len(nodes) != len(self.nodes):
            raise PlanValidationError("plan.duplicate_node")
        objectives = [node.objective.strip().casefold() for node in self.nodes]
        if len(set(objectives)) != len(objectives):
            raise PlanValidationError("plan.duplicate_objective")
        for node in self.nodes:
            if node.local_id in node.depends_on or any(
                dependency not in nodes for dependency in node.depends_on
            ):
                raise PlanValidationError("plan.invalid_dependency")
        visited: set[str] = set()
        visiting: set[str] = set()

        def visit(local_id: str) -> None:
            if local_id in visiting:
                raise PlanValidationError("plan.cycle")
            if local_id in visited:
                return
            visiting.add(local_id)
            for dependency in nodes[local_id].depends_on:
                visit(dependency)
            visiting.remove(local_id)
            visited.add(local_id)

        for local_id in nodes:
            visit(local_id)
        return self


class PlanRevision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    expected_revision: int = Field(ge=1)
    added_nodes: tuple[PlanNode, ...] = ()
    replaced_local_ids: tuple[str, ...] = ()
    cancelled_local_ids: tuple[str, ...] = ()
    justification: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()
