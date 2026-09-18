from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, NotRequired, cast

from deepagents.graph import DeepAgentState
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.language_models.chat_models import BaseChatModel

from skail.providers.base import ProviderAdapter
from skail.providers.errors import ProviderError
from skail.providers.fallback import FallbackBinding, ProviderFallbackPolicy
from skail.routing.assignment import AccountingReconciliationRequired
from skail.runtime.errors import FrameworkContractError


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
        call_begin: Callable[[str, str], str] | None = None,
        call_ambiguous: Callable[[str, Exception], None] | None = None,
        active_assignments: Mapping[str, FallbackBinding] | None = None,
        redactor: Any = None,
    ) -> None:
        self._models = dict(models)
        self._assignments = dict(assignments)
        self._allow_delegation = allow_delegation
        self._providers = dict(providers or {})
        self._fallback_policy = fallback_policy
        self._usage_callback = usage_callback
        self._call_begin = call_begin
        self._call_ambiguous = call_ambiguous
        self._active_assignments = dict(active_assignments or {})
        self._call_counts: dict[str, int] = {}
        self._redactor = redactor

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        bound = self._bind(self._redact_request(request))
        call_id = self._begin_call(request)
        try:
            response = handler(bound)
        except Exception as error:
            self._mark_ambiguous(call_id, error)
            if call_id is not None:
                raise AccountingReconciliationRequired(
                    "provider outcome is ambiguous; paid execution is blocked"
                ) from error
            response, assignment_id = self._fallback_sync(request, handler, error)
            self._record_usage(
                request, response, assignment_id=assignment_id, call_id=call_id
            )
            return self._redact_response(response)
        self._complete_call(request, response, call_id=call_id)
        return self._redact_response(response)

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        bound = self._bind(self._redact_request(request))
        call_id = self._begin_call(request)
        try:
            response = await handler(bound)
        except Exception as error:
            self._mark_ambiguous(call_id, error)
            if call_id is not None:
                raise AccountingReconciliationRequired(
                    "provider outcome is ambiguous; paid execution is blocked"
                ) from error
            response, assignment_id = await self._fallback_async(request, handler, error)
            self._record_usage(
                request, response, assignment_id=assignment_id, call_id=call_id
            )
            return self._redact_response(response)
        self._complete_call(request, response, call_id=call_id)
        return self._redact_response(response)

    def _redact_request(self, request: ModelRequest[Any]) -> ModelRequest[Any]:
        if self._redactor is None:
            return request
        return request.override(messages=self._redactor.scrub(request.messages))

    def _redact_response(self, response: ModelResponse[Any]) -> ModelResponse[Any]:
        if self._redactor is None:
            return response
        return ModelResponse(
            result=self._redactor.scrub(response.result),
            structured_response=self._redactor.scrub(response.structured_response),
        )

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
        call_id: str | None = None,
    ) -> None:
        if self._usage_callback is None:
            return
        selected_id = assignment_id or request.state.get("current_assignment_id")
        assert isinstance(selected_id, str)
        if call_id is None:
            self._call_counts[selected_id] = self._call_counts.get(selected_id, 0) + 1
            call_id = f"call-{self._call_counts[selected_id]}"
        self._usage_callback(
            selected_id,
            response,
            call_id,
        )

    def _begin_call(self, request: ModelRequest[Any]) -> str | None:
        if self._call_begin is None:
            return None
        assignment_id = request.state.get("current_assignment_id")
        assert isinstance(assignment_id, str)
        serialized = json.dumps(
            [
                message.model_dump(mode="json")
                if hasattr(message, "model_dump")
                else str(message)
                for message in request.messages
            ],
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        execution_key = hashlib.sha256(serialized.encode()).hexdigest()
        return self._call_begin(assignment_id, execution_key)

    def _mark_ambiguous(self, call_id: str | None, error: Exception) -> None:
        if call_id is not None and self._call_ambiguous is not None:
            self._call_ambiguous(call_id, error)

    def _complete_call(
        self,
        request: ModelRequest[Any],
        response: object,
        *,
        call_id: str | None,
        assignment_id: str | None = None,
    ) -> None:
        try:
            self._record_usage(
                request,
                response,
                call_id=call_id,
                assignment_id=assignment_id,
            )
        except Exception:
            if call_id is None:
                raise
            # The provider returned successfully, so its outcome is known even when
            # local usage normalization or persistence fails. Leave the call started;
            # finalization will complete it conservatively from the reservation.

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
