from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from deepagents.middleware.subagents import CompiledSubAgent
from langchain_core.language_models.chat_models import BaseChatModel

from skail.domain.routing import TaskAssignment
from skail.providers.base import ProviderAdapter
from skail.providers.fallback import ProviderFallbackPolicy
from skail.routing.assignment import AssignmentUsageSettler, PersistedAssignmentRegistry
from skail.runtime.errors import FrameworkContractError
from skail.runtime.task_graph_spike import SpikeAssignment, build_compiled_task_subagent


def build_persisted_task_subagent(
    *,
    name: str,
    description: str,
    attempt_id: str,
    assignment: TaskAssignment,
    registry: PersistedAssignmentRegistry,
    models: Mapping[str, BaseChatModel],
    tools: Sequence[Any] = (),
    providers: Mapping[str, ProviderAdapter] | None = None,
    fallback_policy: ProviderFallbackPolicy | None = None,
    usage_settler: AssignmentUsageSettler | None = None,
) -> CompiledSubAgent:
    assignments, active = registry.runtime_bindings()
    assignment_id = str(assignment.assignment_id)
    model_key = assignments.get(assignment_id)
    binding = active.get(attempt_id)
    if model_key is None or binding is None or binding.assignment_id != assignment_id:
        raise FrameworkContractError(
            "route.assignment_not_persisted",
            "the compiled child requires the active persisted assignment",
            assignment_id=assignment_id,
            attempt_id=attempt_id,
        )
    return build_compiled_task_subagent(
        name=name,
        description=description,
        assignment=SpikeAssignment(
            assignment_id=assignment_id,
            attempt_id=attempt_id,
            model_id=model_key,
            provider=binding.provider,
            reservation_id=binding.reservation_id,
        ),
        models=models,
        tools=tools,
        providers=providers,
        fallback_policy=fallback_policy,
        assignment_models=assignments,
        active_assignments=active,
        usage_callback=(
            None
            if usage_settler is None
            else lambda assignment_id, response, call_id: usage_settler.record_call(
                assignment_id, response, call_id=call_id
            )
        ),
    )
