"""Compatibility fallback for Outlines structured generation when outlines is absent."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, TypeVar, Type
from pydantic import BaseModel

logger = logging.getLogger(__name__)

try:
    import outlines
    from outlines import generate as outlines_generate
    HAS_OUTLINES = True
except Exception:
    outlines = None
    outlines_generate = None
    HAS_OUTLINES = False

T = TypeVar("T", bound=BaseModel)


def is_outlines_available() -> bool:
    """Return True if outlines library is installed and available."""
    return HAS_OUTLINES and outlines is not None


class OutlinesFallback:
    """Fallback handler for structured JSON generation with or without outlines."""

    def __init__(self, model: Any = None) -> None:
        self.model = model
        self._is_fallback = not is_outlines_available()

    def build_json_generator(self, schema_or_model: type[T] | dict[str, Any] | str) -> Callable[..., Any]:
        """Build a callable generator for the given schema."""
        if is_outlines_available() and self.model is not None and not getattr(self.model, "_is_fallback", False):
            try:
                return outlines_generate.json(self.model, schema_or_model)  # type: ignore[union-attr]
            except Exception as exc:
                logger.warning("outlines.generate.json failed: %s. Using fallback.", exc)

        schema_cls: type[T] | None = None
        if isinstance(schema_or_model, type) and issubclass(schema_or_model, BaseModel):
            schema_cls = schema_or_model

        def fallback_generator(prompt: str, **kwargs: Any) -> Any:
            raw_text = "{}"
            if self.model is not None:
                if hasattr(self.model, "create_chat_completion"):
                    messages = [
                        {
                            "role": "system",
                            "content": "JSON classifier. Output strictly compact 1-line JSON matching schema without codeblocks.",
                        },
                        {"role": "user", "content": prompt},
                    ]
                    call_kwargs: dict[str, Any] = dict(kwargs)
                    # Pass JSON schema grammar when schema_cls is a Pydantic model.
                    # llama-cpp-python ≥0.2.56 supports response_format={"type": "json_object",
                    # "schema": <dict>} for grammar-constrained decoding — same guarantee as
                    # Outlines constrained generation but without the Outlines dependency.
                    if schema_cls is not None and "response_format" not in call_kwargs:
                        try:
                            json_schema = schema_cls.model_json_schema()
                            call_kwargs["response_format"] = {
                                "type": "json_object",
                                "schema": json_schema,
                            }
                        except Exception:
                            pass  # model doesn't support response_format; continue unconstrained
                    resp = self.model.create_chat_completion(messages, **call_kwargs)
                    if isinstance(resp, dict) and "choices" in resp and len(resp["choices"]) > 0:
                        raw_text = resp["choices"][0].get("message", {}).get("content", "{}")
                elif hasattr(self.model, "create_completion"):
                    resp = self.model.create_completion(prompt, **kwargs)
                    if isinstance(resp, dict) and "choices" in resp and len(resp["choices"]) > 0:
                        raw_text = resp["choices"][0].get("text", "{}")
                elif callable(self.model):
                    resp = self.model(prompt, **kwargs)
                    if isinstance(resp, dict) and "choices" in resp and len(resp["choices"]) > 0:
                        raw_text = resp["choices"][0].get("text", "{}")
                    elif isinstance(resp, str):
                        raw_text = resp

            # Strip markdown code fencing if present
            raw_text = raw_text.strip()
            if raw_text.startswith("```"):
                lines = raw_text.splitlines()
                if len(lines) >= 2 and lines[0].startswith("```"):
                    end_idx = -1 if lines[-1].strip() == "```" else len(lines)
                    raw_text = "\n".join(lines[1:end_idx]).strip()

            # Try parsing with json_repair if available, else json.loads
            try:
                import json_repair
                parsed = json_repair.loads(raw_text)
            except Exception:
                try:
                    parsed = json.loads(raw_text)
                except Exception:
                    parsed = {}

            if schema_cls is not None:
                if isinstance(parsed, dict):
                    try:
                        return schema_cls.model_validate(parsed)
                    except Exception:
                        try:
                            return schema_cls(**parsed)
                        except Exception:
                            try:
                                defaults = schema_cls().model_dump()
                                defaults.update(parsed)
                                return schema_cls.model_construct(**defaults)
                            except Exception:
                                return schema_cls.model_construct(**parsed)
                try:
                    return schema_cls()
                except Exception:
                    return schema_cls.model_construct()
            return parsed

        return fallback_generator


def generate_structured_json(
    model: Any,
    prompt: str,
    schema_or_model: type[T] | dict[str, Any],
    **kwargs: Any,
) -> Any:
    """Generate structured output adhering to schema_or_model."""
    handler = OutlinesFallback(model)
    generator = handler.build_json_generator(schema_or_model)
    return generator(prompt, **kwargs)
