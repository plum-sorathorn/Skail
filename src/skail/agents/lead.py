from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, cast

from deepagents.middleware.subagents import CompiledSubAgent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable

from skail.domain.routing import RoutingMode
from skail.domain.usage import NormalizedUsage
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
must all be read-only. Minimal planned shape (copy this):
{"mode": "planned", "objective": "<goal>", "reason": "<why>", "plan":
{"schema_version": 1, "policy_version": "adaptive-v1", "revision": 1,
"nodes": [{"local_id": "survey", "kind": "agent", "objective": "<survey work>"},
{"local_id": "gate", "kind": "checkpoint", "objective": "<review evidence>"}]}}
Unknown plan fields are rejected; use ONLY schema_version, policy_version,
revision, nodes{local_id,kind,objective}. constraints may be a string or a list of strings. A final
answer needs no execution_decision. When delegating, call task(description,
subagent_type). The description may be plain text or one JSON object with: description,
success_criteria, depends_on (persisted task IDs), priority, write_scope, model_policy,
budget_usd, and background. subagent_type and profile are aliases; description may
itself be a JSON-encoded object string. Preserve the user's criteria, dependencies,
scope, model constraints, and budget. Never invent dependency IDs. Give the user a concise answer
with relevant file/function citations; do not paste criteria, verification objects, route data, or
Python representations into prose. If returning JSON, put user-facing text in an `answer` or
`summary` field and keep verification in separate structured fields. Preserve technical detail the
user explicitly requests. Operational tools
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
    direct_only: bool = False
    required_agent_count: int | None = None
    routing_mode: RoutingMode = RoutingMode.AUTO
    risk: TaskRisk = TaskRisk.ROUTINE


class LeadIntentError(ValueError):
    """An explicit user instruction conflicts with the available run policy."""


def resolve_lead_controls(
    instruction: str, controls: LeadControls | None = None
) -> LeadControls:
    """Translate clear user directives into constraints for this run only."""

    resolved = controls or LeadControls()
    normalized = instruction.casefold()
    direct_only = any(
        re.search(pattern, normalized)
        for pattern in (
            r"\bdo (?:this|it|the work) yourself\b",
            r"\bhandle (?:this|it|the work) yourself\b",
            r"\bwithout delegating\b",
            r"\bdo not delegate\b",
            r"\bdon't delegate\b",
            r"\bno delegation\b",
            r"\bno subagents?\b",
        )
    )
    no_write = any(
        re.search(pattern, normalized)
        for pattern in (
            r"\bdo not edit(?: any| the)? (?:files?|workspace|code)?\b",
            r"\bdon't edit(?: any| the)? (?:files?|workspace|code)?\b",
            r"\bdo not modify(?: any| the)? (?:files?|workspace|code)?\b",
            r"\bdon't modify(?: any| the)? (?:files?|workspace|code)?\b",
            r"\bdo not change (?:any |the )?(?:files?|workspace|code)\b",
            r"\bread[- ]only\b",
            r"\bno file (?:edits?|writes?|modifications?)\b",
        )
    )
    count_match = re.search(
        r"\bexactly\s+(\d+|one|two|three|four|five)\s+"
        r"(?:agents?|subagents?|children)\b",
        normalized,
    )
    required_agent_count: int | None = None
    if count_match is not None:
        count = count_match.group(1)
        required_agent_count = (
            int(count)
            if count.isdigit()
            else {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}[count]
        )
        if (
            required_agent_count < 1
            or required_agent_count > 3
            or resolved.delegation == "off"
            or required_agent_count > resolved.max_children
            or direct_only
        ):
            raise LeadIntentError(
                "execution.intent_conflict: the requested agent count conflicts "
                "with the current delegation policy or three-child limit"
            )

    return replace(
        resolved,
        delegation="off" if direct_only else resolved.delegation,
        write_allowed=False if no_write else resolved.write_allowed,
        required_agent_count=(
            required_agent_count
            if required_agent_count is not None
            else resolved.required_agent_count
        ),
        max_children=(
            required_agent_count if required_agent_count is not None else resolved.max_children
        ),
        direct_only=direct_only or resolved.direct_only,
    )


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
    runtime_event: Callable[..., None] | None = None,
    runtime_model_name: str | None = None,
    model_response_observer: Callable[[Any], None] | None = None,
    usage_normalizer: Callable[[Any], NormalizedUsage | None] | None = None,
    model_call_guard: Callable[[], None] | None = None,
    extension_tools: Sequence[Any] = (),
    session_id: str = "",
    run_id: str = "",
    state_dir: Path | None = None,
    context_prompt: str | None = None,
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
              usage_normalizer=usage_normalizer,
              model_call_guard=model_call_guard,
            system_prompt=(
                TASK_PACKET_GUIDANCE
                if context_prompt is None
                else f"{TASK_PACKET_GUIDANCE}\n\n{context_prompt}"
            ),
            session_id=session_id,
            run_id=run_id,
            graph_id=f"{session_id}:{run_id}:lead",
            state_dir=state_dir,
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
