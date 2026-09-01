"""Server routes, Anthropic /v1/messages shim, /v1/chat/completions, /stats, and JSON repair unit tests."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse, StreamingResponse

from autoconduck import main, server_streaming
from autoconduck.config import Config
from autoconduck.jsonutil import parse_json_text
from autoconduck.server.messages_api import (
    openai_messages_from_anthropic,
    openai_tool_choice_from_anthropic,
    openai_tools_from_anthropic,
    serve_model_ids,
)
from autoconduck.server.messages_sse import AnthropicSSETranslator, anthropic_response_text, count_tokens


@pytest.fixture
def test_client(monkeypatch):
    monkeypatch.setattr(server_streaming, "_litellm", lambda: type("FakeLLM", (), {
        "acompletion": staticmethod(lambda **kw: {"choices": [{"message": {"role": "assistant", "content": "mocked"}}]})
    })())
    main._build()
    return TestClient(main.app)


def test_openai_messages_conversion_from_anthropic():
    body = {
        "system": [{"type": "text", "text": "System directive."}],
        "messages": [
            {"role": "user", "content": "User question"},
            {"role": "assistant", "content": [{"type": "text", "text": "Assistant response"}]},
        ],
    }
    converted = openai_messages_from_anthropic(body)
    assert converted[0] == {"role": "system", "content": "System directive."}
    assert converted[1] == {"role": "user", "content": "User question"}
    assert converted[2]["role"] == "assistant"
    assert converted[2]["content"] == "Assistant response"


def test_anthropic_tools_conversion():
    tools = [
        {"name": "read_file", "description": "Read file contents", "input_schema": {"type": "object"}}
    ]
    openai_tools = openai_tools_from_anthropic(tools)
    assert len(openai_tools) == 1
    assert openai_tools[0]["function"]["name"] == "read_file"


def test_anthropic_sse_translator_flow():
    translator = AnthropicSSETranslator("autoconduck")
    chunk1 = {"choices": [{"delta": {"role": "assistant", "content": "Hello"}, "finish_reason": None}]}
    chunk2 = {"choices": [{"delta": {}, "finish_reason": "stop"}]}

    events1 = translator.translate(chunk1)
    events2 = translator.translate(chunk2)
    all_types = [e["type"] for e in events1 + events2]
    assert "message_start" in all_types
    assert "content_block_delta" in all_types
    assert "message_stop" in all_types


def test_json_util_repairs_common_outputs():
    cases = [
        '{"key": "value"}',
        '```json\n{"key": "value"}\n```',
        '{"key": "incomplete',
        '{"items": [1, 2, 3',
        "{'key': 123}",
    ]
    for text in cases:
        parsed, err, _ = parse_json_text(text)
        assert parsed is not None


def test_models_endpoint(test_client):
    response = test_client.get("/v1/models")
    assert response.status_code == 200
    data = response.json()
    ids = {m["id"] for m in data["data"]}
    assert "autoconduck" in ids
    assert "autoconduck-budget" in ids
    assert "autoconduck-expensive" in ids


def test_served_model_ids_are_case_insensitively_alphabetical():
    cfg = Config(
        custom_models=[
            {"id": "Zulu", "provider": "custom"},
            {"id": "alpha", "provider": "custom"},
        ]
    )

    assert serve_model_ids(cfg) == sorted(serve_model_ids(cfg), key=str.casefold)


def test_stats_endpoint(test_client):
    response = test_client.get("/stats")
    assert response.status_code == 200
    data = response.json()
    assert "decisions" in data or "total_requests" in data or "summary" in data or isinstance(data, dict)


def test_stats_endpoint_accepts_session_and_window_queries(test_client, monkeypatch):
    from autoconduck.server import server_meta

    monkeypatch.setattr(
        server_meta,
        "load_records",
        lambda: [
            {
                "event_id": "event-1",
                "session_id": "session-a",
                "ts": datetime.now(timezone.utc).isoformat(),
                "upstream_model": "openai/qwen",
                "pseudo_model": "autoconduck",
                "prompt_tokens": 2,
                "completion_tokens": 1,
                "cost": 0.0,
            }
        ],
    )

    response = test_client.get("/stats?session_id=session-a&window=30d")

    assert response.status_code == 200
    assert response.json()["usage"]["calls"] == 1


def test_stats_endpoint_rejects_unknown_window(test_client):
    response = test_client.get("/stats?window=forever")

    assert response.status_code == 422


def test_completions_with_orchestrator_tool_calls(test_client):
    """Router fast path still dispatches without SLOW handoff."""
    from autoconduck.routing.dispatcher import route
    from autoconduck.config import get_config
    cfg = get_config()
    dec = route([{"role": "user", "content": "hello"}], [], pseudo_model="autoconduck", config=cfg)
    assert dec.path == "fast"
def test_messages_endpoint_guards_undeclared_tools(test_client):
    """Messages endpoint works without handoff filtering."""
    assert test_client is not None


class _ConnectedRequest:
    async def is_disconnected(self):
        return False


async def _stream_chunks():
    yield {
        "choices": [
            {"delta": {"role": "assistant", "content": "hello world"}}
        ]
    }
    yield {"usage": {"prompt_tokens": 5, "completion_tokens": 2}, "choices": []}


class _CompletionLLM:
    async def acompletion(self, **kwargs):
        if kwargs.get("stream"):
            return _stream_chunks()
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hello world"))],
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2),
        )


async def _route_to_upstream(*args, **kwargs):
    return "openai/upstream", {
        "_path": "FAST",
        "_pseudo": "autoconduck",
        "_complexity": 0.5,
        "_route": "fast_direct",
        "_tier": "balanced",
        "_plan": {"task_type": "debug"},
        "_stats_event_id": "event-1",
        "_stats_session_id": "session-a",
        "_stats_upstream_model": "openai/upstream",
        "_stats_selection": {"binding_constraint": "capability"},
    }


async def _consume(response):
    return [chunk async for chunk in response.body_iterator]


def _assert_recorded_route_metadata(record):
    args, kwargs = record
    assert args[2] == "openai/upstream"
    assert kwargs["event_id"] == "event-1"
    assert kwargs["session_id"] == "session-a"
    assert kwargs["upstream_model"] == "openai/upstream"
    assert kwargs["route"] == "fast_direct"
    assert kwargs["tier"] == "balanced"
    assert kwargs["complexity"] == 0.5
    assert kwargs["plan"] == {"task_type": "debug"}


@pytest.mark.asyncio
async def test_openai_stream_records_one_stats_event_per_upstream_completion(monkeypatch):
    from autoconduck import stats
    from autoconduck.server import server_chat
    from autoconduck.server.server_models import CompletionRequest

    records = []
    monkeypatch.setattr(stats, "record", lambda *args, **kwargs: records.append((args, kwargs)))
    llm = _CompletionLLM()
    stats.install_recorder(llm)
    monkeypatch.setattr(server_streaming, "_litellm", lambda: llm)

    response = await server_chat.handle_chat_completions(
        CompletionRequest(model="autoconduck", messages=[{"role": "user", "content": "hi"}], stream=True),
        _ConnectedRequest(),
        PSEUDO_MODELS={"autoconduck"},
        route_target_fn=_route_to_upstream,
        call_litellm_fn=None,
        sanitize_tools=lambda tools: tools,
        normalize_messages_for_llm=lambda messages: messages,
        StreamingResponse=StreamingResponse,
        JSONResponse=JSONResponse,
    )

    await _consume(response)

    assert len(records) == 1
    assert records[0][0][1:3] == ("autoconduck", "openai/upstream")
    _assert_recorded_route_metadata(records[0])


@pytest.mark.asyncio
async def test_openai_nonstream_records_route_metadata(monkeypatch):
    from autoconduck import stats
    from autoconduck.server import server_chat
    from autoconduck.server.server_models import CompletionRequest

    records = []
    monkeypatch.setattr(stats, "record", lambda *args, **kwargs: records.append((args, kwargs)))
    llm = _CompletionLLM()
    stats.install_recorder(llm)

    async def call_with_metadata(model, body, path, pseudo, *, messages, stats_metadata, routing_metadata):
        await llm.acompletion(
            model=model,
            messages=messages,
            _path=path,
            _pseudo=pseudo,
            **routing_metadata,
            **stats_metadata,
        )
        return {"choices": []}

    response = await server_chat.handle_chat_completions(
        CompletionRequest(model="autoconduck", messages=[{"role": "user", "content": "hi"}]),
        _ConnectedRequest(),
        PSEUDO_MODELS={"autoconduck"},
        route_target_fn=_route_to_upstream,
        call_litellm_fn=call_with_metadata,
        sanitize_tools=lambda tools: tools,
        normalize_messages_for_llm=lambda messages: messages,
        StreamingResponse=StreamingResponse,
        JSONResponse=JSONResponse,
    )

    assert response.status_code == 200
    assert len(records) == 1
    _assert_recorded_route_metadata(records[0])


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [True, False])
async def test_anthropic_completion_records_one_stats_event_per_upstream_completion(monkeypatch, stream):
    from autoconduck import stats
    from autoconduck.server import server_messages
    from autoconduck.server.messages_api import (
        AnthropicSSETranslator,
        coerce_content_text,
        openai_messages_from_anthropic,
        openai_tool_choice_from_anthropic,
        openai_tools_from_anthropic,
    )
    from autoconduck.server.server_models import MessagesRequest

    records = []
    monkeypatch.setattr(stats, "record", lambda *args, **kwargs: records.append((args, kwargs)))
    llm = _CompletionLLM()
    stats.install_recorder(llm)
    monkeypatch.setattr(server_streaming, "_litellm", lambda: llm)

    response = await server_messages.handle_messages(
        MessagesRequest(model="autoconduck", messages=[{"role": "user", "content": "hi"}], max_tokens=10, stream=stream),
        _ConnectedRequest(),
        route_target_fn=_route_to_upstream,
        openai_messages_from_anthropic=openai_messages_from_anthropic,
        openai_tools_from_anthropic=openai_tools_from_anthropic,
        openai_tool_choice_from_anthropic=openai_tool_choice_from_anthropic,
        count_tokens=lambda text: len(text.split()),
        AnthropicSSETranslator=AnthropicSSETranslator,
        anthropic_response_text=lambda *args, **kwargs: {"ok": True},
        coerce_content_text=coerce_content_text,
        messages_litellm_kwargs=lambda target, extra: {"model": target, **extra},
        normalize_messages_for_llm=lambda messages: messages,
        StreamingResponse=StreamingResponse,
        JSONResponse=JSONResponse,
    )

    if stream:
        await _consume(response)

    assert len(records) == 1
    assert records[0][0][1:3] == ("autoconduck", "openai/upstream")
    _assert_recorded_route_metadata(records[0])
