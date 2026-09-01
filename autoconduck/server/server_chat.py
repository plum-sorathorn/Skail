"""OpenAI-compatible /v1/chat/completions endpoint handler and SSE streaming."""

from __future__ import annotations

import json
import time
from typing import Any

import autoconduck.config as config_module
from autoconduck.server.server_models import CompletionRequest


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
        pass
    body.messages = normalize_messages_for_llm(body.messages)

    target, extra = await route_target_fn(
        body.model,
        body.messages,
        request,
        tools=body.tools,
        payload_session_id=body.autoconduck_session_id,
    )

    if extra.get("_oma_result"):
        oma_res = extra["_oma_result"]
        report = oma_res.get("report", "")
        try:
            from autoconduck.stats import record_oma_outcomes

            record_oma_outcomes(
                extra.get("_stats_session_id"), extra.get("_oma_outcomes", [])
            )
        except Exception:
            pass
        if body.stream:
            async def oma_relay():
                chunk = {
                    "id": f"chatcmpl-oma-{int(time.time())}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": target or body.model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": report},
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(chunk)}\n\n"
                stop_chunk = {
                    "id": chunk["id"],
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": target or body.model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": "stop",
                        }
                    ],
                }
                yield f"data: {json.dumps(stop_chunk)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(oma_relay(), media_type="text/event-stream")
        else:
            return JSONResponse({
                "id": f"chatcmpl-oma-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": target or body.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": report},
                        "finish_reason": "stop",
                    }
                ],
                "usage": oma_res.get("totalTokenUsage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}),
            })

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
            kwargs.pop("autoconduck_session_id", None)
            kwargs["messages"] = normalize_messages_for_llm(messages)
            if kwargs.get("tools"):
                kwargs["tools"] = sanitize_tools(kwargs["tools"])
            kwargs.update(model=target, drop_params=True)
            kwargs.update(extra)

            try:
                response = await llm.acompletion(**kwargs)
                async for chunk in response:
                    if await request.is_disconnected():
                        break
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
                yield "data: [DONE]\n\n"

        return StreamingResponse(relay(), media_type="text/event-stream")
    try:
        result = await call_litellm_fn(
            target,
            body,
            extra.get("_path"),
            extra.get("_pseudo"),
            messages=messages,
            stats_metadata={
                key: value for key, value in extra.items() if key.startswith("_stats_")
            },
            routing_metadata={
                key: extra[key]
                for key in ("_complexity", "_route", "_tier", "_plan")
                if key in extra
            },
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
