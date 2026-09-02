from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, NotRequired

from deepagents.graph import DeepAgentState
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.language_models.chat_models import BaseChatModel

from rudder.runtime.errors import FrameworkContractError


class AssignmentState(DeepAgentState):
    current_assignment_id: NotRequired[str]
    locked_assignment_id: NotRequired[str]
    assigned_model: NotRequired[str]
    attempt_id: NotRequired[str]


class AssignmentInvariantError(FrameworkContractError):
    pass


class TaskBoundModelMiddleware(AgentMiddleware[AssignmentState, Any, Any]):
    """Install a preselected model and reject assignment drift within an attempt."""

    state_schema = AssignmentState

    def __init__(
        self,
        models: Mapping[str, BaseChatModel],
        *,
        allow_delegation: bool = True,
    ) -> None:
        self._models = dict(models)
        self._allow_delegation = allow_delegation

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        return handler(self._bind(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        return await handler(self._bind(request))

    def _bind(self, request: ModelRequest[Any]) -> ModelRequest[Any]:
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
