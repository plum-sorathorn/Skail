from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from deepagents.middleware.subagents import CompiledSubAgent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable

from skail.domain.routing import RoutingMode
from skail.routing.requirements import TaskRisk
from skail.runtime.leases import WorkspaceLeaseManager
from skail.tools.assembly import build_default_agent, default_registry
from skail.tools.registry import SideEffect, ToolMetadata, ToolRegistry

DelegationMode = Literal["auto", "ask", "off"]

TASK_PACKET_GUIDANCE = """Before any operational tool call, call execution_decision with mode,
objective, constraints, and reason. Use direct for bounded work (direct must NOT
send plan or revision), discovery only for read-only evidence work with a checkpoint,
or planned with a validated finite plan. planned/discovery REQUIRE plan: a validated
finite plan object (or JSON string of one) with a checkpoint node; discovery plan nodes
must all be read-only. constraints may be a string or a list of strings. A final
answer needs no execution_decision. When delegating, call task(description,
subagent_type). The description may be plain text or one JSON object with: description,
success_criteria, depends_on (persisted task IDs), priority, write_scope, model_policy,
budget_usd, and background. subagent_type and profile are aliases; description may
itself be a JSON-encoded object string. Preserve the user's criteria, dependencies,
scope, model constraints, and budget. Never invent dependency IDs. Operational tools
take exact args: grep(pattern, path='.', glob=None) e.g. {"pattern": "SKAIL_LIVE_OK",
"path": ".", "glob": "*.py"}; read(file_path, offset=0, limit=2000) e.g.
{"file_path": "src/skail/agents/lead.py"}; ls(path='.') e.g. {"path": "."};
glob(pattern, path=None) e.g. {"pattern": "*.py"}. Use pattern (not query/search),
path (not dir), glob (not include), file_path (not path/file). When Skail wakes
you at a plan checkpoint, call execution_decision again with the full revised plan and
revision metadata using only the supplied evidence references."""


@dataclass(frozen=True)
class LeadControls:
    delegation: DelegationMode = "auto"
    model: str | None = None
    profile: str | None = None
    write_allowed: bool | None = None
    max_children: int = 3
    routing_mode: RoutingMode = RoutingMode.AUTO
    risk: TaskRisk = TaskRisk.ROUTINE


#: Operational tools the lead must not call directly in worktree mode. The
#: canonical checkout is read-only for the lead there; all mutations flow
#: through ``task`` children whose edits integrate via changesets.
LEAD_WORKTREE_BLOCKED_WRITES = frozenset({"edit_file", "write_file", "execute"})


def lead_worktree_blocked_message(tool_name: str) -> str:
    return (
        f"{tool_name} is blocked for the lead in worktree mode: the canonical "
        "checkout is read-only for the lead; delegate mutations through task "
        "children whose edits integrate via changesets."
    )


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
    isolate_lead_writes: bool = False,
    leases: WorkspaceLeaseManager,
    extra_middleware: Sequence[AgentMiddleware[Any, Any, Any]] = (),
    redactor: Any = None,
    checkpointer: Any = None,
    approvals: Any = None,
    question_store: Any = None,
    runtime_event: Callable[[str, str], None] | None = None,
    runtime_model_name: str | None = None,
    model_response_observer: Callable[[Any], None] | None = None,
    extension_tools: Sequence[Any] = (),
    session_id: str = "",
    run_id: str = "",
) -> Runnable[object, object]:
    allow_children = controls.delegation in ("auto", "ask")
    registry = _lead_registry(
        allow_delegation=controls.delegation != "off",
        write_allowed=controls.write_allowed is not False,
        isolate_lead_writes=isolate_lead_writes,
    )
    return cast(
        Runnable[object, object],
        build_default_agent(
            model,
            workspace=workspace,
            profile="lead",
            subagents=list(subagents) if allow_children else [],
            extension_tools=extension_tools,
            registry=registry,
            blocked_tool_message=(
                lead_worktree_blocked_message if isolate_lead_writes else None
            ),
            lease_manager=leases,
            extra_middleware=extra_middleware,
            redactor=redactor,
            checkpointer=checkpointer,
            approvals=approvals,
            question_store=question_store,
            runtime_event=runtime_event,
            runtime_model_name=runtime_model_name,
            model_response_observer=model_response_observer,
            system_prompt=TASK_PACKET_GUIDANCE,
            session_id=session_id,
            run_id=run_id,
            graph_id=f"{session_id}:{run_id}:lead",
        ),
    )


def _lead_registry(
    *,
    allow_delegation: bool,
    write_allowed: bool,
    isolate_lead_writes: bool = False,
) -> ToolRegistry:
    source = default_registry()
    tools: list[ToolMetadata] = []
    for name in source.names:
        metadata = source.get(name)
        profiles = metadata.profiles
        if not write_allowed and metadata.side_effect is not SideEffect.READ_ONLY:
            profiles = frozenset(item for item in profiles if item != "lead")
        if not allow_delegation and name == "task":
            profiles = frozenset(item for item in profiles if item != "lead")
        if isolate_lead_writes and name in LEAD_WORKTREE_BLOCKED_WRITES:
            profiles = frozenset(item for item in profiles if item != "lead")
        tools.append(metadata.model_copy(update={"profiles": profiles}))
    return ToolRegistry(tools)
