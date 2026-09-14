from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any, cast

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolCallChunk,
    ToolMessage,
    UsageMetadata,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, PrivateAttr

from skail.config.models import ProviderConfig
from skail.domain.usage import NormalizedUsage, UsageAuthority
from skail.providers.base import ModelOptions
from skail.providers.catalog_sources import CatalogEntry
from skail.providers.errors import ProviderError, ProviderErrorKind
from skail.providers.models import ModelProfile, ProviderSupportLevel


class OpenAICompatibleChatModel(BaseChatModel):
    model_name: str
    _adapter: OpenAICompatibleAdapter = PrivateAttr()
    _options: ModelOptions = PrivateAttr()
    _tools: tuple[Any, ...] = PrivateAttr(default=())

    def __init__(
        self,
        *,
        adapter: OpenAICompatibleAdapter,
        model_name: str,
        options: ModelOptions,
    ) -> None:
        super().__init__(model_name=model_name)  # type: ignore[call-arg]
        self._adapter = adapter
        self._options = options

    @property
    def _llm_type(self) -> str:
        return f"skail-{self._adapter.name}-openai-compatible"

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[Any, AIMessage]:
        del tool_choice, kwargs
        bound = OpenAICompatibleChatModel(
            adapter=self._adapter,
            model_name=self.model_name,
            options=self._options,
        )
        bound._tools = tuple(convert_to_openai_tool(tool) for tool in tools)
        return bound

    def with_structured_output(
        self,
        schema: dict[str, Any] | type[BaseModel],
        *,
        include_raw: bool = False,
        **kwargs: Any,
    ) -> Runnable[Any, Any]:
        del kwargs

        async def ainvoke(value: Any) -> Any:
            response = await self._complete(value, response_schema=schema)
            try:
                raw = json.loads(str(response.content))
                parsed = schema.model_validate(raw) if isinstance(schema, type) else raw
                error = None
            except (ValueError, TypeError) as exc:
                if not include_raw:
                    raise
                parsed = None
                error = exc
            if include_raw:
                return {"raw": response, "parsed": parsed, "parsing_error": error}
            return parsed

        def invoke(value: Any) -> Any:
            raise RuntimeError("structured compatible-provider calls require async invocation")

        return RunnableLambda(invoke, ainvoke)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del messages, stop, run_manager, kwargs
        raise RuntimeError("compatible-provider calls require async invocation")

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        message = await self._complete(messages)
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        del stop, run_manager, kwargs
        body = self._body(messages, stream=True)
        async with self._adapter.stream_request("/chat/completions", body) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                raw = json.loads(data)
                if isinstance(raw.get("error"), Mapping):
                    raise self._adapter.classify_stream_error(raw["error"])
                usage = raw.get("usage")
                if isinstance(usage, Mapping):
                    yield ChatGenerationChunk(message=_usage_chunk(usage))
                for choice in raw.get("choices", []):
                    delta = choice.get("delta", {})
                    content = delta.get("content") or ""
                    tool_chunks = []
                    for call in delta.get("tool_calls", []):
                        function = call.get("function", {})
                        tool_chunks.append(
                            {
                                "name": function.get("name"),
                                "args": function.get("arguments") or "",
                                "id": call.get("id"),
                                "index": call.get("index", 0),
                                "type": "tool_call_chunk",
                            }
                        )
                    yield ChatGenerationChunk(
                        message=AIMessageChunk(
                            content=content,
                            tool_call_chunks=cast(list[ToolCallChunk], tool_chunks),
                        )
                    )

    async def _complete(
        self,
        value: Any,
        *,
        response_schema: dict[str, Any] | type[BaseModel] | None = None,
    ) -> AIMessage:
        messages = value if isinstance(value, list) else [HumanMessage(content=str(value))]
        body = self._body(messages, stream=False)
        if response_schema is not None:
            schema_value = (
                response_schema.model_json_schema()
                if isinstance(response_schema, type) and issubclass(response_schema, BaseModel)
                else response_schema
            )
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "skail_response", "schema": schema_value, "strict": True},
            }
        response = await self._adapter.request("POST", "/chat/completions", json=body)
        response.raise_for_status()
        raw = response.json()
        try:
            message = raw["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("provider returned a malformed chat response") from exc
        usage = raw.get("usage", {})
        return AIMessage(
            content=message.get("content") or "",
            tool_calls=_tool_calls(message.get("tool_calls", [])),
            usage_metadata=_usage_metadata(usage),
            response_metadata=(
                {"skail_cost_usd": str(usage["cost"])} if "cost" in usage else {}
            ),
        )

    def _body(self, messages: Sequence[BaseMessage], *, stream: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model_name,
            "messages": [_message_value(message) for message in messages],
            "stream": stream,
        }
        if stream:
            body["stream_options"] = {"include_usage": True}
        if self._tools:
            body["tools"] = list(self._tools)
        if self._options.temperature is not None:
            body["temperature"] = self._options.temperature
        if self._options.max_tokens is not None:
            body["max_tokens"] = self._options.max_tokens
        return body


class OpenAICompatibleAdapter:
    support_level = ProviderSupportLevel.MANUAL
    auto_routing_eligible = False

    def __init__(
        self,
        provider_name: str,
        config: ProviderConfig,
        *,
        api_key: str,
        http_async_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not config.base_url:
            raise ValueError("OpenAI-compatible provider requires base_url")
        if not config.models:
            raise ValueError("OpenAI-compatible provider requires declared models")
        self.name = provider_name
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        self._api_key = api_key
        self._client = http_async_client

    def validate_config(self, config: ProviderConfig) -> None:
        if config != self.config:
            raise ValueError("provider configuration changed after adapter creation")

    def create_model(self, model: ModelProfile, options: ModelOptions) -> BaseChatModel:
        if model.provider != self.name:
            raise ValueError("model provider does not match adapter provider")
        if model.model not in self.config.models:
            raise ValueError("model is not declared for this provider")
        return OpenAICompatibleChatModel(adapter=self, model_name=model.model, options=options)

    async def discover_models(self) -> tuple[CatalogEntry, ...]:
        return ()

    def normalize_usage(self, response: object) -> NormalizedUsage | None:
        if not isinstance(response, (AIMessage, AIMessageChunk)):
            return None
        if response.usage_metadata is None:
            return None
        raw_cost = response.response_metadata.get("skail_cost_usd")
        return NormalizedUsage(
            input_tokens=response.usage_metadata["input_tokens"],
            output_tokens=response.usage_metadata["output_tokens"],
            cost_usd=Decimal(str(raw_cost or "0")),
            authority=(
                UsageAuthority.AUTHORITATIVE_ACTUAL
                if raw_cost is not None
                else UsageAuthority.ESTIMATED_ACTUAL
            ),
        )

    def classify_error(self, error: Exception) -> ProviderError:
        kind = ProviderErrorKind.PROTOCOL
        code = None
        if isinstance(error, (httpx.TimeoutException, httpx.ConnectError)):
            kind = ProviderErrorKind.TRANSIENT
        elif isinstance(error, httpx.HTTPStatusError):
            status = error.response.status_code
            try:
                code = error.response.json().get("error", {}).get("code")
            except (ValueError, AttributeError):
                code = None
            if status in {401, 403}:
                kind = ProviderErrorKind.AUTHENTICATION
            elif status == 429:
                kind = ProviderErrorKind.RATE_LIMIT
            elif code == "model_not_found":
                kind = ProviderErrorKind.INVALID_MODEL
            elif status in {408, 504, 529} or status >= 500:
                kind = ProviderErrorKind.TRANSIENT
        return ProviderError(
            kind=kind,
            summary="provider request failed",
            provider=self.name,
            retry_safe=kind in {ProviderErrorKind.RATE_LIMIT, ProviderErrorKind.TRANSIENT},
            provider_code=code,
        )

    def classify_stream_error(self, error: Mapping[str, Any]) -> ProviderError:
        code = error.get("code")
        if code == "rate_limit_exceeded":
            kind = ProviderErrorKind.RATE_LIMIT
        elif code in {"timeout", "overloaded", "internal_error"}:
            kind = ProviderErrorKind.TRANSIENT
        elif code == "model_not_found":
            kind = ProviderErrorKind.INVALID_MODEL
        elif code == "invalid_api_key":
            kind = ProviderErrorKind.AUTHENTICATION
        else:
            kind = ProviderErrorKind.PROTOCOL
        return ProviderError(
            kind=kind,
            summary="provider stream failed",
            provider=self.name,
            retry_safe=kind in {ProviderErrorKind.RATE_LIMIT, ProviderErrorKind.TRANSIENT},
            provider_code=str(code) if code is not None else None,
        )

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if self._client is not None:
            return await self._client.request(
                method, self.base_url + path, headers=headers, **kwargs
            )
        async with httpx.AsyncClient() as client:
            return await client.request(method, self.base_url + path, headers=headers, **kwargs)

    @asynccontextmanager
    async def stream_request(
        self, path: str, body: dict[str, Any]
    ) -> AsyncIterator[httpx.Response]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if self._client is not None:
            async with self._client.stream(
                "POST", self.base_url + path, headers=headers, json=body
            ) as response:
                yield response
            return
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST", self.base_url + path, headers=headers, json=body
            ) as response:
                yield response


def _message_value(message: BaseMessage) -> dict[str, Any]:
    role = "user"
    if isinstance(message, SystemMessage):
        role = "system"
    elif isinstance(message, AIMessage):
        role = "assistant"
    elif isinstance(message, ToolMessage):
        role = "tool"
    value: dict[str, Any] = {"role": role, "content": message.content}
    if isinstance(message, AIMessage) and message.tool_calls:
        value["tool_calls"] = [
            {
                "id": call["id"],
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": json.dumps(call["args"], separators=(",", ":")),
                },
            }
            for call in message.tool_calls
        ]
    if isinstance(message, ToolMessage):
        value["tool_call_id"] = message.tool_call_id
    return value


def _usage_metadata(usage: Mapping[str, Any]) -> UsageMetadata:
    input_tokens = int(usage.get("prompt_tokens", 0))
    output_tokens = int(usage.get("completion_tokens", 0))
    return UsageMetadata(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=int(usage.get("total_tokens", input_tokens + output_tokens)),
    )


def _usage_chunk(usage: Mapping[str, Any]) -> AIMessageChunk:
    return AIMessageChunk(
        content="",
        usage_metadata=_usage_metadata(usage),
        response_metadata=(
            {"skail_cost_usd": str(usage["cost"])} if "cost" in usage else {}
        ),
    )


def _tool_calls(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for value in values:
        function = value.get("function", {})
        result.append(
            {
                "name": function.get("name", ""),
                "args": json.loads(function.get("arguments", "{}")),
                "id": value.get("id", ""),
                "type": "tool_call",
            }
        )
    return result
