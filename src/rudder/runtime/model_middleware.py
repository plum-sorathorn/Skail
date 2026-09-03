from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, NotRequired, cast

from deepagents.graph import DeepAgentState
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.language_models.chat_models import BaseChatModel

from rudder.providers.base import ProviderAdapter
from rudder.providers.errors import ProviderError
from rudder.providers.fallback import FallbackBinding, ProviderFallbackPolicy
from rudder.runtime.errors import FrameworkContractError


class AssignmentState(DeepAgentState):
    current_assignment_id: NotRequired[str]
    locked_assignment_id: NotRequired[str]
    assigned_model: NotRequired[str]
    attempt_id: NotRequired[str]
    assigned_provider: NotRequired[str]
    reservation_id: NotRequired[str]


class AssignmentInvariantError(FrameworkContractError):
    pass


class TaskBoundModelMiddleware(AgentMiddleware[AssignmentState, Any, Any]):
    """Install a preselected model and reject assignment drift within an attempt."""

    state_schema = AssignmentState

    def __init__(
        self,
        models: Mapping[str, BaseChatModel],
        *,
        assignments: Mapping[str, str],
        allow_delegation: bool = True,
        providers: Mapping[str, ProviderAdapter] | None = None,
        fallback_policy: ProviderFallbackPolicy | None = None,
        usage_callback: Callable[[str, object, str], None] | None = None,
        active_assignments: Mapping[str, FallbackBinding] | None = None,
    ) -> None:
        self._models = dict(models)
        self._assignments = dict(assignments)
        self._allow_delegation = allow_delegation
        self._providers = dict(providers or {})
        self._fallback_policy = fallback_policy
        self._usage_callback = usage_callback
        self._active_assignments = dict(active_assignments or {})
        self._call_counts: dict[str, int] = {}

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        bound = self._bind(request)
        try:
            response = handler(bound)
        except Exception as error:
            response, assignment_id = self._fallback_sync(request, handler, error)
            self._record_usage(request, response, assignment_id=assignment_id)
            return response
        self._record_usage(request, response)
        return response

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        bound = self._bind(request)
        try:
            response = await handler(bound)
        except Exception as error:
            response, assignment_id = await self._fallback_async(request, handler, error)
            self._record_usage(request, response, assignment_id=assignment_id)
            return response
        self._record_usage(request, response)
        return response

    def _provider_error(self, request: ModelRequest[Any], error: Exception) -> ProviderError | None:
        provider_name = request.state.get("assigned_provider")
        if not isinstance(provider_name, str) or provider_name not in self._providers:
            return error if isinstance(error, ProviderError) else None
        return self._providers[provider_name].classify_error(error)

    def _fallback_binding(
        self, request: ModelRequest[Any], error: Exception
    ) -> FallbackBinding | None:
        classified = self._provider_error(request, error)
        if classified is None or self._fallback_policy is None:
            return None
        assignment_id = request.state.get("current_assignment_id")
        provider = request.state.get("assigned_provider")
        model = request.state.get("assigned_model")
        if not all(isinstance(value, str) for value in (assignment_id, provider, model)):
            return None
        assert isinstance(assignment_id, str)
        assert isinstance(provider, str)
        assert isinstance(model, str)
        return self._fallback_policy.fallback_for(
            provider=provider, model=model, assignment_id=assignment_id, error=classified
        )

    def _fallback_request(
        self, request: ModelRequest[Any], binding: FallbackBinding
    ) -> ModelRequest[Any]:
        if binding.assignment_id == request.state.get("current_assignment_id"):
            raise AssignmentInvariantError(
                "route.fallback_assignment_reused",
                "provider fallback must create a new assignment",
            )
        state = dict(request.state)
        state.update(
            current_assignment_id=binding.assignment_id,
            locked_assignment_id=binding.assignment_id,
            assigned_provider=binding.provider,
            assigned_model=binding.model_key,
            reservation_id=binding.reservation_id,
        )
        cast(dict[str, Any], request.state).update(state)
        self._assignments[binding.assignment_id] = binding.model_key
        attempt_id = request.state.get("attempt_id")
        assert isinstance(attempt_id, str)
        self._active_assignments[attempt_id] = binding
        return request.override(state=cast(AssignmentState, state))

    def _fallback_sync(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
        error: Exception,
    ) -> tuple[ModelResponse[Any], str]:
        binding = self._fallback_binding(request, error)
        if binding is None:
            classified = self._provider_error(request, error)
            raise classified or error
        response = handler(self._bind(self._fallback_request(request, binding)))
        return response, binding.assignment_id

    async def _fallback_async(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
        error: Exception,
    ) -> tuple[ModelResponse[Any], str]:
        binding = self._fallback_binding(request, error)
        if binding is None:
            classified = self._provider_error(request, error)
            raise classified or error
        response = await handler(self._bind(self._fallback_request(request, binding)))
        return response, binding.assignment_id

    def _record_usage(
        self,
        request: ModelRequest[Any],
        response: object,
        *,
        assignment_id: str | None = None,
    ) -> None:
        if self._usage_callback is None:
            return
        selected_id = assignment_id or request.state.get("current_assignment_id")
        assert isinstance(selected_id, str)
        self._call_counts[selected_id] = self._call_counts.get(selected_id, 0) + 1
        self._usage_callback(
            selected_id,
            response,
            f"call-{self._call_counts[selected_id]}",
        )

    def _bind(self, request: ModelRequest[Any]) -> ModelRequest[Any]:
        attempt = request.state.get("attempt_id")
        active = self._active_assignments.get(attempt) if isinstance(attempt, str) else None
        if (
            active is not None
            and request.state.get("current_assignment_id") != active.assignment_id
        ):
            state = dict(request.state)
            state.update(
                current_assignment_id=active.assignment_id,
                locked_assignment_id=active.assignment_id,
                assigned_provider=active.provider,
                assigned_model=active.model_key,
                reservation_id=active.reservation_id,
            )
            cast(dict[str, Any], request.state).update(state)
            request = request.override(state=cast(AssignmentState, state))
        assignment_id = request.state.get("current_assignment_id")
        locked_id = request.state.get("locked_assignment_id")
        model_id = request.state.get("assigned_model")
        attempt_id = request.state.get("attempt_id")
        if not all(
            isinstance(value, str) and value
            for value in (assignment_id, locked_id, model_id, attempt_id)
        ):
            raise AssignmentInvariantError(
                "route.assignment_missing",
                "a complete model assignment must exist before the first call",
            )
        assert isinstance(assignment_id, str)
        assert isinstance(locked_id, str)
        assert isinstance(model_id, str)
        assert isinstance(attempt_id, str)
        if assignment_id != locked_id:
            raise AssignmentInvariantError(
                "route.assignment_changed",
                "a healthy attempt cannot change its assignment",
                assignment_id=assignment_id,
                locked_assignment_id=locked_id,
                attempt_id=attempt_id,
            )
        recorded_model = self._assignments.get(assignment_id)
        if recorded_model is None:
            raise AssignmentInvariantError(
                "route.assignment_unknown",
                "the assignment is not present in the runtime assignment registry",
                assignment_id=assignment_id,
                attempt_id=attempt_id,
            )
        if recorded_model != model_id:
            raise AssignmentInvariantError(
                "route.assignment_model_mismatch",
                "the assignment does not own the requested model",
                assignment_id=assignment_id,
                recorded_model=recorded_model,
                requested_model=model_id,
            )
        try:
            model = self._models[model_id]
        except KeyError as exc:
            raise AssignmentInvariantError(
                "route.assigned_model_unavailable",
                "the assigned model is not available in the runtime registry",
                model=model_id,
                attempt_id=attempt_id,
            ) from exc

        tools = request.tools
        if not self._allow_delegation:
            tools = [tool for tool in tools if _tool_name(tool) != "task"]
        return request.override(model=model, tools=tools)


def _tool_name(tool: Any) -> str | None:
    if isinstance(tool, Mapping):
        name = tool.get("name")
        if isinstance(name, str):
            return name
        function = tool.get("function")
        if isinstance(function, Mapping):
            function_name = function.get("name")
            if isinstance(function_name, str):
                return function_name
        return None
    name = getattr(tool, "name", None)
    return name if isinstance(name, str) else None
