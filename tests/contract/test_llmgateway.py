from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

import httpx
import pytest
from fakes.provider import ProviderHTTPFixtureTransport
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel

from skail.config.models import ProviderConfig
from skail.domain.usage import UsageAuthority
from skail.providers.base import ModelOptions, ModelProfile, ProviderSupportLevel
from skail.providers.errors import ProviderError, ProviderErrorKind
from skail.providers.llmgateway import LLMGATEWAY_BASE_URL, LLMGatewayAdapter


class StructuredAnswer(BaseModel):
    answer: str
    confidence: int


@tool
def read_file(path: str) -> str:
    """Read a fixture file."""

    return f"contents:{path}"


class ToolLoopTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.bodies: list[dict[str, object]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(await request.aread()))
        if len(self.bodies) == 1:
            message = {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path":"README.md"}',
                        },
                    }
                ],
            }
        else:
            message = {"role": "assistant", "content": "tool loop complete"}
        return httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": message}], "usage": {}},
        )


def _config() -> ProviderConfig:
    return ProviderConfig(
        type="openai-compatible",
        base_url=LLMGATEWAY_BASE_URL,
        api_key_env="LLMGATEWAY_API_KEY",
        models=("openai/test-model",),
    )


def _profile() -> ModelProfile:
    return ModelProfile(
        provider="llmgateway",
        model="openai/test-model",
        support_level=ProviderSupportLevel.OPENAI_COMPATIBLE,
    )


def _combined(chunks: list[AIMessageChunk]) -> AIMessageChunk:
    if not chunks:
        raise AssertionError("expected at least one model chunk")
    combined = chunks[0]
    for chunk in chunks[1:]:
        combined += chunk
    return combined


@pytest.mark.asyncio
async def test_llmgateway_uses_canonical_v1_auth_and_chat_streaming() -> None:
    transport = ProviderHTTPFixtureTransport()
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = LLMGatewayAdapter(
            _config(),
            api_key="fixture-credential",
            http_async_client=client,
        )
        model = adapter.create_model(_profile(), ModelOptions())

        chunks = [chunk async for chunk in model.astream([HumanMessage(content="Say hello")])]

    combined = _combined(chunks)
    request = transport.last_request
    assert combined.content == "Hello Skail"
    assert request.method == "POST"
    assert request.path == "/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer fixture-credential"
    assert request.json is not None
    assert request.json["model"] == "openai/test-model"
    assert request.json["stream"] is True
    assert request.json["stream_options"] == {"include_usage": True}


@pytest.mark.asyncio
async def test_llmgateway_assembles_fragmented_streaming_tool_arguments() -> None:
    transport = ProviderHTTPFixtureTransport()
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = LLMGatewayAdapter(
            _config(),
            api_key="fixture-credential",
            http_async_client=client,
        )
        model = adapter.create_model(_profile(), ModelOptions())
        with_tools = model.bind_tools(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "Read one file",
                        "parameters": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                            "required": ["path"],
                        },
                    },
                }
            ]
        )

        chunks = [chunk async for chunk in with_tools.astream("Read the project readme")]

    assert _combined(chunks).tool_calls == [
        {
            "name": "read_file",
            "args": {"path": "README.md"},
            "id": "call_read",
            "type": "tool_call",
        }
    ]
    assert transport.last_request.json is not None
    assert transport.last_request.json["tools"][0]["function"]["name"] == "read_file"  # type: ignore[index]


@pytest.mark.asyncio
async def test_llmgateway_supports_declared_structured_output() -> None:
    transport = ProviderHTTPFixtureTransport()
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = LLMGatewayAdapter(
            _config(),
            api_key="fixture-credential",
            http_async_client=client,
        )
        model = adapter.create_model(_profile(), ModelOptions())

        response = await model.with_structured_output(
            StructuredAnswer,
            method="json_schema",
        ).ainvoke("Report status")

    assert response == StructuredAnswer(answer="ready", confidence=9)
    assert transport.last_request.json is not None
    assert transport.last_request.json["response_format"]["type"] == "json_schema"  # type: ignore[index]


@pytest.mark.asyncio
async def test_llmgateway_marks_missing_stream_cost_as_estimated() -> None:
    transport = ProviderHTTPFixtureTransport()
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = LLMGatewayAdapter(
            _config(),
            api_key="fixture-credential",
            http_async_client=client,
        )
        model = adapter.create_model(_profile(), ModelOptions())
        chunks = [chunk async for chunk in model.astream("Count usage")]

    usage = adapter.normalize_usage(_combined(chunks))
    assert usage is not None
    assert usage.input_tokens == 7
    assert usage.output_tokens == 3
    assert usage.cost_usd == Decimal("0")
    assert usage.authority is UsageAuthority.ESTIMATED_ACTUAL


def test_llmgateway_marks_reported_gateway_cost_as_authoritative() -> None:
    adapter = LLMGatewayAdapter(_config(), api_key="fixture-credential")
    response = AIMessage(
        content="done",
        usage_metadata={"input_tokens": 7, "output_tokens": 3, "total_tokens": 10},
        response_metadata={"skail_cost_usd": "0.00042"},
    )

    usage = adapter.normalize_usage(response)

    assert usage is not None
    assert usage.cost_usd == Decimal("0.00042")
    assert usage.authority is UsageAuthority.AUTHORITATIVE_ACTUAL


@pytest.mark.asyncio
async def test_llmgateway_runs_a_complete_loop_with_a_real_langchain_tool() -> None:
    transport = ToolLoopTransport()
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = LLMGatewayAdapter(
            _config(), api_key="fixture-credential", http_async_client=client
        )
        original = adapter.create_model(_profile(), ModelOptions())
        bound = original.bind_tools([read_file])
        first = await bound.ainvoke([HumanMessage(content="Read the file")])
        second = await bound.ainvoke(
            [
                HumanMessage(content="Read the file"),
                first,
                ToolMessage(content="contents", tool_call_id="call-1"),
            ]
        )

    assert bound is not original
    assert second.content == "tool loop complete"
    assert transport.bodies[0]["tools"][0]["function"]["name"] == "read_file"  # type: ignore[index]
    assistant = transport.bodies[1]["messages"][1]  # type: ignore[index]
    assert assistant["tool_calls"][0]["function"]["arguments"] == '{"path":"README.md"}'  # type: ignore[index]


@pytest.mark.asyncio
async def test_llmgateway_discovers_models_with_authenticated_provider_provenance() -> None:
    transport = ProviderHTTPFixtureTransport()
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = LLMGatewayAdapter(
            _config(),
            api_key="fixture-credential",
            http_async_client=client,
        )

        discovered = await adapter.discover_models()

    assert len(discovered) == 1
    entry = discovered[0]
    assert entry.provider == "llmgateway"
    assert entry.model == "openai/test-model"
    assert entry.source.value == "discovered"
    assert entry.trusted is True
    assert entry.as_of.tzinfo is not None
    assert entry.as_of <= datetime.now(tz=entry.as_of.tzinfo)
    assert entry.fields["input_usd_per_million"] == Decimal("1.25")
    assert entry.fields["output_usd_per_million"] == Decimal("10.00")
    assert entry.fields["cached_input_usd_per_million"] == Decimal("0.125")
    assert entry.fields["context_tokens"] == 128000
    assert entry.fields["max_output_tokens"] == 16384
    assert entry.fields["supports_tools"] is True
    assert entry.fields["supports_structured_output"] is True
    assert "capability" not in entry.fields
    assert transport.last_request.method == "GET"
    assert transport.last_request.path == "/v1/models"
    assert transport.last_request.query["exclude_deprecated"] == "true"
    assert entry.provenance == "llmgateway:/v1/models?exclude_deprecated=true"


@pytest.mark.asyncio
async def test_llmgateway_keeps_malformed_prices_unavailable() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={
                "data": [
                    {
                        "id": "bad-price",
                        "pricing": {"prompt": "not-a-price", "completion": None},
                        "context_length": 4096,
                        "max_output": 1024,
                        "supported_parameters": [],
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = LLMGatewayAdapter(
            _config(), api_key="fixture-credential", http_async_client=client
        )
        entry = (await adapter.discover_models())[0]

    assert entry.fields["input_usd_per_million"] is None
    assert entry.fields["output_usd_per_million"] is None


@pytest.mark.asyncio
async def test_llmgateway_trusts_authenticated_facts_and_provider_mapping_capabilities() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={
                "data": [
                    {
                        "id": "mapped-model",
                        "pricing": {
                            "prompt": "0.000001",
                            "completion": "0.000002",
                            "input_cache_read": "0.0000005",
                        },
                        "architecture": {
                            "input_modalities": ["text"],
                            "output_modalities": ["text"],
                        },
                        "context_length": 32768,
                        "supported_parameters": [],
                        "json_output": True,
                        "providers": [
                            {
                                "providerId": "provider-a",
                                "tools": True,
                                "reasoning": True,
                                "parallelToolCalls": True,
                            }
                        ],
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = LLMGatewayAdapter(
            _config().model_copy(update={"models": ("mapped-model",)}),
            api_key="fixture-credential",
            http_async_client=client,
        )
        entry = (await adapter.discover_models())[0]

    assert entry.trusted is True
    assert entry.fields["input_usd_per_million"] == Decimal("1")
    assert entry.fields["output_usd_per_million"] == Decimal("2")
    assert entry.fields["cached_input_usd_per_million"] == Decimal("0.5")
    assert entry.fields["supports_tools"] is True
    assert entry.fields["supports_reasoning"] is True
    assert entry.fields["supports_structured_output"] is True


@pytest.mark.parametrize(
    ("status", "kind", "retry_safe"),
    [
        (400, ProviderErrorKind.PROTOCOL, False),
        (401, ProviderErrorKind.AUTHENTICATION, False),
        (403, ProviderErrorKind.AUTHENTICATION, False),
        (404, ProviderErrorKind.INVALID_MODEL, False),
        (408, ProviderErrorKind.TRANSIENT, True),
        (429, ProviderErrorKind.RATE_LIMIT, True),
        (500, ProviderErrorKind.TRANSIENT, True),
        (529, ProviderErrorKind.TRANSIENT, True),
    ],
)
def test_llmgateway_classifies_http_failures(
    status: int,
    kind: ProviderErrorKind,
    retry_safe: bool,
) -> None:
    adapter = LLMGatewayAdapter(_config(), api_key="fixture-credential")
    request = httpx.Request("POST", f"{LLMGATEWAY_BASE_URL}/chat/completions")
    error_body = transport_error_body(status)
    response = httpx.Response(status, request=request, json=error_body)
    error = httpx.HTTPStatusError("provider failed", request=request, response=response)

    normalized = adapter.classify_error(error)

    assert normalized.kind is kind
    assert normalized.retry_safe is retry_safe
    assert normalized.provider == "llmgateway"


def test_llmgateway_classifies_malformed_success_as_protocol_failure() -> None:
    adapter = LLMGatewayAdapter(_config(), api_key="fixture-credential")

    normalized = adapter.classify_error(ValueError("response body was not valid JSON"))

    assert normalized.kind is ProviderErrorKind.PROTOCOL
    assert normalized.retry_safe is False


@pytest.mark.asyncio
async def test_llmgateway_surfaces_midstream_error_events() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = (
            b'data: {"error":{"code":"rate_limit_exceeded"}}\n\n'
            b"data: [DONE]\n\n"
        )
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/event-stream"},
            content=payload,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = LLMGatewayAdapter(
            _config(), api_key="fixture-credential", http_async_client=client
        )
        model = adapter.create_model(_profile(), ModelOptions())

        with pytest.raises(ProviderError) as caught:
            _ = [chunk async for chunk in model.astream("trigger stream error")]

    assert caught.value.kind is ProviderErrorKind.RATE_LIMIT
    assert caught.value.retry_safe is True


def transport_error_body(status: int) -> dict[str, object]:
    # Exercise the exact same public wire shapes used by the fixture transport
    # without reaching into adapter implementation details.
    details = {
        400: ("invalid_request_error", "invalid_request"),
        401: ("authentication_error", "invalid_api_key"),
        403: ("permission_error", "permission_denied"),
        404: ("invalid_request_error", "model_not_found"),
        408: ("timeout_error", "timeout"),
        429: ("rate_limit_error", "rate_limit_exceeded"),
        500: ("api_error", "internal_error"),
        529: ("overloaded_error", "overloaded"),
    }
    error_type, code = details[status]
    return {"error": {"message": "fixture failure", "type": error_type, "code": code}}
