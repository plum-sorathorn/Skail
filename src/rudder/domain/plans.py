from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PlanValidationError(ValueError):
    pass


class PlanNodeKind(StrEnum):
    AGENT = "agent"
    TOOL = "tool"
    VERIFICATION = "verification"
    INTEGRATION = "integration"
    CHECKPOINT = "checkpoint"


class PlanNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    local_id: str = Field(min_length=1)
    kind: PlanNodeKind
    objective: str = Field(min_length=1)
    depends_on: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()
    effect_scope: str = "read"


class ExecutionPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = Field(ge=1)
    policy_version: str = Field(min_length=1)
    revision: int = Field(ge=1)
    nodes: tuple[PlanNode, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_graph(self) -> ExecutionPlan:
        nodes = {node.local_id: node for node in self.nodes}
        if len(nodes) != len(self.nodes):
            raise PlanValidationError("plan.duplicate_node")
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
    model_config = ConfigDict(frozen=True)

    expected_revision: int = Field(ge=1)
    added_nodes: tuple[PlanNode, ...] = ()
    replaced_local_ids: tuple[str, ...] = ()
    cancelled_local_ids: tuple[str, ...] = ()
    justification: str = Field(min_length=1)
