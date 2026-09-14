from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from threading import Lock
from typing import Any

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel, Field, PrivateAttr

from skail.domain.usage import NormalizedUsage, UsageAuthority
from skail.providers.base import ModelOptions, ModelProfile, ProviderSupportLevel
from skail.providers.errors import ProviderError, ProviderErrorKind

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "providers"


@dataclass(frozen=True)
class RecordedRequest:
    method: str
    path: str
    headers: Mapping[str, str]
    json: Mapping[str, Any] | None


class _AsyncFixtureStream(httpx.AsyncByteStream):
    def __init__(self, chunks: Sequence[bytes]) -> None:
        self._chunks = tuple(chunks)

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


class ProviderHTTPFixtureTransport(httpx.AsyncBaseTransport):
    """Offline OpenAI-compatible transport with inspectable requests."""

    def __init__(
        self,
        *,
        provider: str = "llmgateway",
        failure_status: int | None = None,
    ) -> None:
        self.provider = provider
        self.failure_status = failure_status
        self.requests: list[RecordedRequest] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raw = await request.aread()
        body = json.loads(raw) if raw else None
        self.requests.append(
            RecordedRequest(
                method=request.method,
                path=request.url.path,
                headers=dict(request.headers),
                json=body,
            )
        )

        if self.failure_status is not None:
            return httpx.Response(
                self.failure_status,
                headers={"content-type": "application/json"},
                json=_error_body(self.failure_status),
                request=request,
            )
        if request.method == "GET" and request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=(FIXTURES / "llmgateway" / "models.json").read_bytes(),
                request=request,
            )
        if request.method != "POST" or not request.url.path.endswith("/chat/completions"):
            return httpx.Response(404, json=_error_body(404), request=request)
        if not isinstance(body, dict):
            return httpx.Response(400, json=_error_body(400), request=request)

        if body.get("stream") is True:
            fixture = "chat_tool.sse" if body.get("tools") else "chat_text.sse"
            payload = (FIXTURES / "llmgateway" / fixture).read_bytes()
            # Split inside an SSE record as well as between records. Parsers must
            # not assume one network chunk equals one SSE line.
            one_third = max(1, len(payload) // 3)
            chunks = (
                payload[:one_third],
                payload[one_third : 2 * one_third],
                payload[2 * one_third :],
            )
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=_AsyncFixtureStream(chunks),
                request=request,
            )

        if body.get("response_format"):
            fixture_path = FIXTURES / "llmgateway" / "chat_structured.json"
        elif self.provider == "llmgateway":
            fixture_path = FIXTURES / "llmgateway" / "chat_structured.json"
        elif self.provider == "devpass":
            fixture_path = FIXTURES / "devpass" / "chat.json"
        else:
            fixture_path = FIXTURES / "openai_compatible" / "chat.json"
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=fixture_path.read_bytes(),
            request=request,
        )

    @property
    def last_request(self) -> RecordedRequest:
        if not self.requests:
            raise AssertionError("fixture transport received no request")
        return self.requests[-1]


def _error_body(status: int) -> dict[str, object]:
    details = {
        400: ("invalid_request_error", "invalid_request", "request was invalid"),
        401: ("authentication_error", "invalid_api_key", "authentication failed"),
        403: ("permission_error", "permission_denied", "model is not available"),
        404: ("invalid_request_error", "model_not_found", "model was not found"),
        408: ("timeout_error", "timeout", "request timed out"),
        429: ("rate_limit_error", "rate_limit_exceeded", "rate limit reached"),
        500: ("api_error", "internal_error", "provider failed"),
        529: ("overloaded_error", "overloaded", "provider overloaded"),
    }
    error_type, code, message = details.get(
        status,
        ("api_error", "unexpected_status", "unexpected provider response"),
    )
    return {"error": {"message": message, "type": error_type, "param": None, "code": code}}


class FakeInjectedProviderFailure(RuntimeError):
    def __init__(self, kind: ProviderErrorKind) -> None:
        self.kind = kind
        super().__init__(f"injected provider failure: {kind.value}")


class FakeProviderChatModel(BaseChatModel):
    """Deterministic provider fake covering agent-relevant model features."""

    model_name: str = "fake/capable"
    response_text: str = "fake response"
    stream_parts: tuple[str, ...] = ("fake ", "response")
    structured_value: dict[str, Any] = Field(default_factory=lambda: {"answer": "ready"})
    tool_call: dict[str, Any] | None = None
    input_tokens: int = 7
    output_tokens: int = 3
    cost_usd: Decimal = Decimal("0.000010")
    failures: list[ProviderErrorKind] = Field(default_factory=list)

    _calls: list[tuple[BaseMessage, ...]] = PrivateAttr(default_factory=list)
    _bound_tool_names: set[str] = PrivateAttr(default_factory=set)
    _lock: Lock = PrivateAttr(default_factory=Lock)

    @property
    def _llm_type(self) -> str:
        return "skail-provider-fake"

    @property
    def calls(self) -> tuple[tuple[BaseMessage, ...], ...]:
        with self._lock:
            return tuple(self._calls)

    @property
    def bound_tool_names(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._bound_tool_names)

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[Any, AIMessage]:
        del tool_choice, kwargs
        with self._lock:
            self._bound_tool_names.update(_tool_name(tool) for tool in tools)
        return self

    def with_structured_output(
        self,
        schema: dict[str, Any] | type[BaseModel],
        *,
        include_raw: bool = False,
        **kwargs: Any,
    ) -> Runnable[Any, Any]:
        del kwargs

        def invoke_structured(value: Any) -> Any:
            raw = self.invoke(value)
            parsed: Any
            if isinstance(schema, type) and issubclass(schema, BaseModel):
                parsed = schema.model_validate(self.structured_value)
            else:
                parsed = dict(self.structured_value)
            if include_raw:
                return {"raw": raw, "parsed": parsed, "parsing_error": None}
            return parsed

        return RunnableLambda(invoke_structured)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        self._record(messages)
        tool_calls = [self.tool_call] if self.tool_call is not None else []
        message = AIMessage(
            content="" if tool_calls else self.response_text,
            tool_calls=tool_calls,
            usage_metadata=self._usage_metadata(),
            response_metadata={"skail_cost_usd": str(self.cost_usd)},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        del stop, run_manager, kwargs
        self._record(messages)
        for part in self.stream_parts:
            yield ChatGenerationChunk(message=AIMessageChunk(content=part))
        yield ChatGenerationChunk(
            message=AIMessageChunk(content="", usage_metadata=self._usage_metadata())
        )

    def _record(self, messages: list[BaseMessage]) -> None:
        with self._lock:
            if self.failures:
                raise FakeInjectedProviderFailure(self.failures.pop(0))
            self._calls.append(tuple(messages))

    def _usage_metadata(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
        }


class FakeProviderAdapter:
    name = "fake"
    support_level = ProviderSupportLevel.NATIVE

    def __init__(self, model: FakeProviderChatModel | None = None) -> None:
        self.model = model or FakeProviderChatModel()
        self.created_with: list[tuple[ModelProfile, ModelOptions]] = []

    def validate_config(self, config: object) -> None:
        del config

    def create_model(self, model: ModelProfile, options: ModelOptions) -> BaseChatModel:
        self.created_with.append((model, options))
        return self.model

    async def discover_models(self) -> tuple[object, ...]:
        return ()

    def normalize_usage(self, response: object) -> NormalizedUsage | None:
        if not isinstance(response, BaseMessage) or response.usage_metadata is None:
            return None
        raw_cost = response.response_metadata.get("skail_cost_usd", self.model.cost_usd)
        return NormalizedUsage(
            input_tokens=response.usage_metadata["input_tokens"],
            output_tokens=response.usage_metadata["output_tokens"],
            cost_usd=Decimal(str(raw_cost)),
            authority=UsageAuthority.AUTHORITATIVE_ACTUAL,
        )

    def classify_error(self, error: Exception) -> ProviderError:
        kind = (
            error.kind
            if isinstance(error, FakeInjectedProviderFailure)
            else ProviderErrorKind.PROTOCOL
        )
        return ProviderError(
            kind=kind,
            summary=str(error),
            provider=self.name,
            retry_safe=kind in {ProviderErrorKind.RATE_LIMIT, ProviderErrorKind.TRANSIENT},
        )


def _tool_name(tool: Any) -> str:
    if isinstance(tool, dict):
        function = tool.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            return function["name"]
        if isinstance(tool.get("name"), str):
            return tool["name"]
    name = getattr(tool, "name", None) or getattr(tool, "__name__", None)
    if not isinstance(name, str):
        raise AssertionError(f"cannot determine tool name for {tool!r}")
    return name
