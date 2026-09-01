"""Anthropic /v1/messages translation endpoint."""

from __future__ import annotations

import json
import time
from typing import Any

import autoconduck.config as config_module
from autoconduck.server.server_models import MessagesRequest


async def handle_messages(
    body: MessagesRequest,
    request: Any,
    *,
    route_target_fn: Any,
    openai_messages_from_anthropic: Any,
    openai_tools_from_anthropic: Any,
    openai_tool_choice_from_anthropic: Any,
    count_tokens: Any,
    AnthropicSSETranslator: Any,
    anthropic_response_text: Any,
    coerce_content_text: Any,
    messages_litellm_kwargs: Any,
    normalize_messages_for_llm: Any,
    StreamingResponse: Any,
    JSONResponse: Any,
) -> Any:
    """Translate Anthropic /v1/messages request to OpenAI format."""
    try:
        oai_messages = normalize_messages_for_llm(
            openai_messages_from_anthropic(body.model_dump(exclude_none=True))
        )
        try:
            from autoconduck.server.session_guard import SessionGuard

            oai_messages = SessionGuard().guard_context(oai_messages).messages
        except Exception:
            pass
    except Exception as exc:
        return JSONResponse(
            {
                "type": "error",
                "error": {"type": "invalid_request_error", "message": str(exc)},
            },
            status_code=400,
        )
    try:
        tools_list = openai_tools_from_anthropic(body.tools) if body.tools else []
        target, extra = await route_target_fn(
            body.model, oai_messages, request, client_type="claude", tools=tools_list
        )
    except Exception as exc:
        # Fail-soft: route_target failure must never 500 — mirror upstream 502 degrade path.
        try:
            from autoconduck.config import resolve_orchestrator_model as _resolve_model
            import autoconduck.config as _cfg_mod

            _cfg = _cfg_mod.get_config()
            _fallback = _resolve_model(_cfg)
        except Exception:
            _fallback = body.model
        try:
            import logging as _logging

            _logging.getLogger("autoconduck").warning("route_target failed, fail-soft degrade: %s", exc)
        except Exception:
            pass
        # Return 502 degrade consistent with other upstream failures (never 5xx internal leak)
        return JSONResponse(
            {"type": "error", "error": {"type": "api_error", "message": str(exc)}},
            status_code=502,
        )
    if extra.get("_oma_result"):
        oma_res = extra["_oma_result"]
        report = oma_res.get("report", "")
        if body.stream:
            async def oma_messages_relay():
                msg_id = f"msg_oma_{int(time.time())}"
                yield f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': {'id': msg_id, 'type': 'message', 'role': 'assistant', 'content': [], 'model': target or body.model, 'stop_reason': None, 'stop_sequence': None, 'usage': {'input_tokens': 0, 'output_tokens': 0}}})}\n\n"
                yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}})}\n\n"
                yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': report}})}\n\n"
                yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': 0})}\n\n"
                yield f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': 'end_turn', 'stop_sequence': None}, 'usage': {'output_tokens': len(report.split())}})}\n\n"
                yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"

            return StreamingResponse(oma_messages_relay(), media_type="text/event-stream")
        else:
            return JSONResponse({
                "id": f"msg_oma_{int(time.time())}",
                "type": "message",
                "role": "assistant",
                "model": target or body.model,
                "content": [{"type": "text", "text": report}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": len(report.split())},
            })

    if extra.get("_path") == "FAST":
        try:
            from autoconduck.digest import maybe_digest_messages

            digest = await maybe_digest_messages(
                oai_messages, config_module.get_config(), request=request
            )
            if digest:
                oai_messages = oai_messages + digest
        except Exception:
            pass
    kwargs = messages_litellm_kwargs(target, extra)
    kwargs.update(
        _path=extra.get("_path", "unknown"),
        _pseudo=extra.get("_pseudo", body.model),
    )
    for name, value in (
        ("tools", openai_tools_from_anthropic(body.tools)),
        ("tool_choice", openai_tool_choice_from_anthropic(body.tool_choice)),
        ("max_tokens", body.max_tokens),
        ("stop", body.stop_sequences),
        ("temperature", body.temperature),
        ("top_p", body.top_p),
        ("thinking", body.thinking),
        ("metadata", body.metadata),
        ("cache_control", body.cache_control),
    ):
        if value is not None:
            kwargs[name] = value
    from autoconduck.server.server_streaming import _litellm

    llm = _litellm()
    if llm is None:
        return JSONResponse(
            {
                "type": "error",
                "error": {"type": "api_error", "message": "litellm unavailable"},
            },
            status_code=502 if body.stream else 503,
        )
    if body.stream:
        try:
            response = await llm.acompletion(
                messages=oai_messages, stream=True, drop_params=True, **kwargs
            )
        except Exception as exc:
            from autoconduck.routing.pricing import record_error
            record_error(target)
            return JSONResponse(
                {
                    "type": "error",
                    "error": {"type": "api_error", "message": str(exc)},
                },
                status_code=502,
            )

        async def relay():
            translator = AnthropicSSETranslator(
                target, input_text=json.dumps(oai_messages)
            )
            try:
                for ev in translator._ensure_message_start():
                    yield f"event: {ev['type']}\ndata: {json.dumps(ev)}\n\n"
                async for chunk in response:
                    if await request.is_disconnected():
                        break
                    payload = (
                        chunk.model_dump()
                        if hasattr(chunk, "model_dump")
                        else chunk
                    )
                    for ev in translator.translate(payload):
                        yield f"event: {ev['type']}\ndata: {json.dumps(ev)}\n\n"
                for ev in translator.finish():
                    yield f"event: {ev['type']}\ndata: {json.dumps(ev)}\n\n"
            except Exception as exc:
                from autoconduck.routing.pricing import record_error
                record_error(target)
                exc_str = str(exc)
                if (
                    "Error building chunks" in exc_str
                    or "stream_chunk_builder" in exc_str
                    or "list index out of range" in exc_str
                ):
                    for ev in translator.finish():
                        yield f"event: {ev['type']}\ndata: {json.dumps(ev)}\n\n"
                else:
                    for ev in translator.error(str(exc)):
                        yield f"event: {ev['event']}\ndata: {ev['data']}\n\n"

        return StreamingResponse(relay(), media_type="text/event-stream")
    try:
        result = await llm.acompletion(
            messages=oai_messages, stream=False, drop_params=True, **kwargs
        )
        text = (
            result.choices[0].message.content
            if hasattr(result, "choices")
            else None
        )
    except Exception as exc:
        from autoconduck.routing.pricing import record_error
        record_error(target)
        return JSONResponse(
            {"type": "error", "error": {"type": "api_error", "message": str(exc)}},
            status_code=502,
        )
    return JSONResponse(
        anthropic_response_text(
            coerce_content_text(text), target, input_text=json.dumps(oai_messages)
        )
    )


async def handle_messages_count_tokens(
    request: Any,
    *,
    openai_messages_from_anthropic: Any,
    count_tokens: Any,
) -> dict[str, int]:
    """Count token input size for Anthropic client compatibility."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    return {
        "input_tokens": count_tokens(
            json.dumps(openai_messages_from_anthropic(body))
        )
    }
