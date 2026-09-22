from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from threading import Lock
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from pydantic import Field, PrivateAttr

ModelCallHook = Callable[["ScriptedChatModel", tuple[BaseMessage, ...]], None]
AsyncModelCallHook = Callable[["ScriptedChatModel", tuple[BaseMessage, ...]], Awaitable[None]]


class ScriptedChatModel(BaseChatModel):
    """A tool-capable fake chat model with thread-safe, observable responses."""

    model_name: str = "scripted-fake"
    responses: list[AIMessage]
    call_hook: ModelCallHook | None = Field(default=None, exclude=True)
    async_call_hook: AsyncModelCallHook | None = Field(default=None, exclude=True)

    _calls: list[tuple[BaseMessage, ...]] = PrivateAttr(default_factory=list)
    _bound_tool_names: set[str] = PrivateAttr(default_factory=set)
    _bound_tools: list[Any] = PrivateAttr(default_factory=list)
    _response_index: int = PrivateAttr(default=0)
    _lock: Lock = PrivateAttr(default_factory=Lock)

    @property
    def calls(self) -> tuple[tuple[BaseMessage, ...], ...]:
        with self._lock:
            return tuple(self._calls)

    @property
    def bound_tool_names(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._bound_tool_names)

    @property
    def bound_tools(self) -> tuple[Any, ...]:
        with self._lock:
            return tuple(self._bound_tools)

    @property
    def _llm_type(self) -> str:
        return "skail-scripted-fake"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model_name": self.model_name}

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[Any, AIMessage]:
        del tool_choice, kwargs
        names = {_tool_name(tool) for tool in tools}
        with self._lock:
            self._bound_tool_names.update(names)
            self._bound_tools.extend(tools)
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        call, response = self._take_response(messages)
        if self.call_hook is not None:
            self.call_hook(self, call)
        return ChatResult(generations=[ChatGeneration(message=response)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        call, response = self._take_response(messages)
        if self.async_call_hook is not None:
            await self.async_call_hook(self, call)
        elif self.call_hook is not None:
            self.call_hook(self, call)
        return ChatResult(generations=[ChatGeneration(message=response)])

    def _take_response(
        self, messages: list[BaseMessage]
    ) -> tuple[tuple[BaseMessage, ...], AIMessage]:
        call = tuple(messages)
        with self._lock:
            if self._response_index >= len(self.responses):
                raise AssertionError(f"{self.model_name} received an unexpected model call")
            response = self.responses[self._response_index]
            self._response_index += 1
            self._calls.append(call)
        return call, response


def tool_call_message(
    name: str,
    arguments: dict[str, Any],
    *,
    call_id: str,
) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": name,
                "args": arguments,
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )


def parallel_tool_call_message(
    calls: Sequence[tuple[str, dict[str, Any], str]],
) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": arguments, "id": call_id, "type": "tool_call"}
            for name, arguments, call_id in calls
        ],
    )


def _tool_name(tool: Any) -> str:
    if isinstance(tool, dict):
        function = tool.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            return str(function["name"])
        if isinstance(tool.get("name"), str):
            return str(tool["name"])
    name = getattr(tool, "name", None) or getattr(tool, "__name__", None)
    if not isinstance(name, str):
        raise AssertionError(f"cannot determine fake-bound tool name for {tool!r}")
    return name
