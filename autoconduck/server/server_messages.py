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
            t0 = time.perf_counter()
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

                from autoconduck.stats import record
                record(
                    extra.get("_path", "FAST"),
                    extra.get("_pseudo", body.model),
                    target or body.model,
                    translator.input_tokens,
                    translator.output_tokens,
                    complexity=extra.get("_complexity"),
                    route=extra.get("_route"),
                    tier=extra.get("_tier"),
                    latency_ms=(time.perf_counter() - t0) * 1000,
                    plan=extra.get("_plan"),
                )
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
                    from autoconduck.stats import record
                    record(
                        extra.get("_path", "FAST"),
                        extra.get("_pseudo", body.model),
                        target or body.model,
                        translator.input_tokens,
                        translator.output_tokens,
                        complexity=extra.get("_complexity"),
                        route=extra.get("_route"),
                        tier=extra.get("_tier"),
                        latency_ms=(time.perf_counter() - t0) * 1000,
                        plan=extra.get("_plan"),
                    )
                else:
                    for ev in translator.error(str(exc)):
                        yield f"event: {ev['event']}\ndata: {ev['data']}\n\n"

        return StreamingResponse(relay(), media_type="text/event-stream")
    t0 = time.perf_counter()
    try:
        result = await llm.acompletion(
            messages=oai_messages, stream=False, drop_params=True, **kwargs
        )
        text = (
            result.choices[0].message.content
            if hasattr(result, "choices")
            else None
        )
        from autoconduck.stats import record
        in_tok = count_tokens(json.dumps(oai_messages))
        out_tok = count_tokens(coerce_content_text(text))
        record(
            extra.get("_path", "FAST"),
            extra.get("_pseudo", body.model),
            target or body.model,
            in_tok,
            out_tok,
            complexity=extra.get("_complexity"),
            route=extra.get("_route"),
            tier=extra.get("_tier"),
            latency_ms=(time.perf_counter() - t0) * 1000,
            plan=extra.get("_plan"),
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
