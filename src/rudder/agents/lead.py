from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from deepagents.middleware.subagents import CompiledSubAgent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable

from rudder.domain.routing import RoutingMode
from rudder.routing.requirements import TaskRisk
from rudder.runtime.leases import WorkspaceLeaseManager
from rudder.tools.assembly import build_default_agent, default_registry
from rudder.tools.registry import SideEffect, ToolMetadata, ToolRegistry

DelegationMode = Literal["auto", "ask", "off"]


@dataclass(frozen=True)
class LeadControls:
    delegation: DelegationMode = "auto"
    model: str | None = None
    profile: str | None = None
    write_allowed: bool | None = None
    max_children: int = 3
    routing_mode: RoutingMode = RoutingMode.AUTO
    risk: TaskRisk = TaskRisk.ROUTINE


def delegation_allowed(controls: LeadControls, *, requested: bool) -> bool:
    if controls.delegation == "off":
        return False
    if controls.delegation == "ask":
        return requested
    return True


def build_production_lead(
    model: BaseChatModel,
    *,
    workspace: Path,
    controls: LeadControls,
    subagents: Sequence[CompiledSubAgent] = (),
    delegation_approved: bool = False,
    leases: WorkspaceLeaseManager,
    extra_middleware: Sequence[AgentMiddleware[Any, Any, Any]] = (),
    redactor: Any = None,
    checkpointer: Any = None,
    approvals: Any = None,
    question_store: Any = None,
    runtime_event: Callable[[str, str], None] | None = None,
    runtime_model_name: str | None = None,
) -> Runnable[object, object]:
    allow_children = controls.delegation in ("auto", "ask")
    registry = _lead_registry(
        allow_delegation=controls.delegation != "off",
        write_allowed=controls.write_allowed is not False,
    )
    return cast(
        Runnable[object, object],
        build_default_agent(
            model,
            workspace=workspace,
            profile="lead",
            subagents=list(subagents) if allow_children else [],
            registry=registry,
            lease_manager=leases,
            extra_middleware=extra_middleware,
            redactor=redactor,
            checkpointer=checkpointer,
            approvals=approvals,
            question_store=question_store,
            runtime_event=runtime_event,
            runtime_model_name=runtime_model_name,
        ),
    )


def _lead_registry(*, allow_delegation: bool, write_allowed: bool) -> ToolRegistry:
    source = default_registry()
    tools: list[ToolMetadata] = []
    for name in source.names:
        metadata = source.get(name)
        profiles = metadata.profiles
        if not write_allowed and metadata.side_effect is not SideEffect.READ_ONLY:
            profiles = frozenset(item for item in profiles if item != "lead")
        if not allow_delegation and name == "task":
            profiles = frozenset(item for item in profiles if item != "lead")
        tools.append(metadata.model_copy(update={"profiles": profiles}))
    return ToolRegistry(tools)
