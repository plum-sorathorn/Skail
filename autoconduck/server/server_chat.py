"""OpenAI-compatible /v1/chat/completions endpoint handler and SSE streaming."""

from __future__ import annotations

import json
import time
from typing import Any

import autoconduck.config as config_module
from autoconduck.server.server_models import CompletionRequest
from autoconduck.stats import record


async def handle_chat_completions(
    body: CompletionRequest,
    request: Any,
    *,
    PSEUDO_MODELS: set[str],
    route_target_fn: Any,
    call_litellm_fn: Any,
    sanitize_tools: Any,
    normalize_messages_for_llm: Any,
    StreamingResponse: Any,
    JSONResponse: Any,
) -> Any:
    """Handle OpenAI /v1/chat/completions request — pure router mode."""
    try:
        from autoconduck.server.session_guard import SessionGuard

        body.messages = SessionGuard().guard_context(body.messages).messages
    except Exception:
        try:
            from autoconduck.orchestrator.session_guard import SessionGuard

            body.messages = SessionGuard().guard_context(body.messages).messages
        except Exception:
            pass
    body.messages = normalize_messages_for_llm(body.messages)

    target, extra = await route_target_fn(body.model, body.messages, request, tools=body.tools)

    messages = normalize_messages_for_llm(body.messages)
    if extra.get("_path") == "FAST":
        try:
            from autoconduck.digest import maybe_digest_messages

            digest = await maybe_digest_messages(
                messages, config_module.get_config(), request=request
            )
            if digest:
                messages = messages + digest
        except Exception:
            pass

    if body.stream:

        async def relay():
            from autoconduck.server.server_streaming import _litellm

            llm = _litellm()
            if llm is None:
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "error": {
                                "message": "litellm unavailable",
                                "type": "api_error",
                            }
                        }
                    )
                    + "\n\n"
                )
                yield "data: [DONE]\n\n"
                return
            kwargs = body.model_dump(exclude_none=True)
            kwargs["messages"] = normalize_messages_for_llm(messages)
            if kwargs.get("tools"):
                kwargs["tools"] = sanitize_tools(kwargs["tools"])
            kwargs.update(model=target, drop_params=True)
            kwargs.update(extra)

            t0 = time.perf_counter()
            prompt_tokens = 0
            completion_tokens = 0
            generated_text_tokens = 0
            try:
                response = await llm.acompletion(**kwargs)
                async for chunk in response:
                    if await request.is_disconnected():
                        break
                    usage = getattr(chunk, "usage", None)
                    if isinstance(chunk, dict):
                        usage = chunk.get("usage", usage)
                    if usage:
                        p = getattr(usage, "prompt_tokens", None) if not isinstance(usage, dict) else usage.get("prompt_tokens")
                        c = getattr(usage, "completion_tokens", None) if not isinstance(usage, dict) else usage.get("completion_tokens")
                        if p:
                            prompt_tokens = max(prompt_tokens, int(p))
                        if c:
                            completion_tokens = max(completion_tokens, int(c))
                    choices = getattr(chunk, "choices", None) if not isinstance(chunk, dict) else chunk.get("choices")
                    if choices and len(choices) > 0:
                        choice = choices[0]
                        delta = getattr(choice, "delta", None) if not isinstance(choice, dict) else choice.get("delta")
                        if delta:
                            content = getattr(delta, "content", None) if not isinstance(delta, dict) else delta.get("content")
                            if content:
                                generated_text_tokens += len(str(content).split())
                    payload = (
                        chunk.model_dump()
                        if hasattr(chunk, "model_dump")
                        else chunk
                    )
                    yield f"data: {json.dumps(payload)}\n\n"
            except Exception as exc:
                from autoconduck.routing.pricing import record_error
                record_error(target)
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "error": {
                                "message": str(exc),
                                "type": "api_error",
                            }
                        }
                    )
                    + "\n\n"
                )
            finally:
                lat_ms = round((time.perf_counter() - t0) * 1000, 1)
                if prompt_tokens == 0:
                    try:
                        from autoconduck.server.messages_api import count_tokens
                        prompt_tokens = count_tokens(json.dumps(kwargs.get("messages", [])))
                    except Exception:
                        pass
                if completion_tokens == 0:
                    completion_tokens = int(generated_text_tokens * 1.3)
                try:
                    record(
                        extra.get("_path", "FAST"),
                        extra.get("_pseudo", body.model),
                        target or body.model,
                        prompt_tokens,
                        completion_tokens,
                        complexity=extra.get("_complexity"),
                        route=extra.get("_route"),
                        tier=extra.get("_tier"),
                        latency_ms=lat_ms,
                        plan=extra.get("_plan"),
                    )
                except Exception:
                    pass
                yield "data: [DONE]\n\n"

        return StreamingResponse(relay(), media_type="text/event-stream")
    try:
        result = await call_litellm_fn(
            target,
            body,
            extra.get("_path"),
            extra.get("_pseudo"),
            messages=messages,
        )
        return JSONResponse(result)
    except Exception as exc:
        from autoconduck.routing.pricing import record_error
        record_error(target)
        return JSONResponse(
            {
                "error": {
                    "message": str(exc),
                    "type": "api_error",
                }
            },
            status_code=502,
        )
