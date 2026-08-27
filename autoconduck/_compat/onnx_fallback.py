"""Compatibility layer and fallback for ONNX Runtime embedded SLM models."""
from __future__ import annotations

import logging
import time
from typing import Any, Iterator, Sequence

logger = logging.getLogger(__name__)

try:
    import onnxruntime
    HAS_ONNX = True
except Exception:
    onnxruntime = None
    HAS_ONNX = False

try:
    import onnxruntime_genai
    HAS_ONNX_GENAI = True
except Exception:
    onnxruntime_genai = None
    HAS_ONNX_GENAI = False


def is_onnx_available() -> bool:
    """Return True if onnxruntime is installed and importable."""
    return HAS_ONNX and onnxruntime is not None


def is_onnx_genai_available() -> bool:
    """Return True if onnxruntime-genai is installed and importable."""
    return HAS_ONNX_GENAI and onnxruntime_genai is not None


class ONNXModelFallback:
    """Pure-Python fallback emulator for ONNX embedded SLM inference."""

    def __init__(self, model_path: str = "", **kwargs: Any) -> None:
        self.model_path = model_path
        self.extra_kwargs = kwargs
        self._is_fallback = True

    def create_completion(
        self,
        prompt: str = "",
        max_tokens: int = 256,
        temperature: float = 0.2,
        stop: list[str] | str | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any] | Iterator[dict[str, Any]]:
        """Simulate completion generation for testing and graceful fallback."""
        text_response = "{}"
        result = {
            "id": f"cmpl-onnx-fallback-{int(time.time())}",
            "object": "text_completion",
            "created": int(time.time()),
            "model": self.model_path or "fallback-slm-onnx",
            "choices": [
                {
                    "text": text_response,
                    "index": 0,
                    "logprobs": None,
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": len(prompt.split()),
                "completion_tokens": len(text_response.split()),
                "total_tokens": len(prompt.split()) + len(text_response.split()),
            },
        }
        if stream:
            return iter([result])
        return result

    def create_chat_completion(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int = 256,
        temperature: float = 0.2,
        stop: list[str] | str | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any] | Iterator[dict[str, Any]]:
        """Simulate chat completion for testing and graceful fallback."""
        content = "{}"
        result = {
            "id": f"chatcmpl-onnx-fallback-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self.model_path or "fallback-slm-onnx",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": sum(len(str(m.get("content", "")).split()) for m in messages),
                "completion_tokens": len(content.split()),
                "total_tokens": sum(len(str(m.get("content", "")).split()) for m in messages) + len(content.split()),
            },
        }
        if stream:
            return iter([result])
        return result

    def __call__(self, prompt: str = "", **kwargs: Any) -> dict[str, Any]:
        return self.create_completion(prompt=prompt, **kwargs)  # type: ignore[return-value]


import os
from pathlib import Path


class ONNXRuntimeDirectModel:
    """Standard ONNX Runtime model inference engine with tokenizer and KV-cache management."""

    def __init__(self, model_path: str, **kwargs: Any) -> None:
        self.model_path = model_path
        self._session = onnxruntime.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self._tokenizer = self._load_tokenizer(model_path)
        self._is_fallback = False

    def _load_tokenizer(self, model_path: str) -> Any:
        import tokenizers

        p = Path(model_path)
        candidates = [
            p.parent / "tokenizer.json",
            p.parent / f"{p.stem}.tokenizer.json",
            p.parent / f"{p.stem.split('-q')[0]}.tokenizer.json",
            p.parent / f"{p.stem.split('-')[0]}.tokenizer.json",
        ]
        for c in candidates:
            if c.is_file() and c.stat().st_size > 0:
                try:
                    return tokenizers.Tokenizer.from_file(str(c))
                except Exception:
                    pass

        lower = p.name.lower()
        if "lfm" in lower:
            try:
                return tokenizers.Tokenizer.from_pretrained("LiquidAI/LFM2.5-1.2B-Instruct-ONNX")
            except Exception:
                pass
        elif "qwen" in lower:
            try:
                return tokenizers.Tokenizer.from_pretrained("onnx-community/Qwen2.5-Coder-0.5B-Instruct")
            except Exception:
                pass

        if candidates[0].is_file():
            return tokenizers.Tokenizer.from_file(str(candidates[0]))
        raise RuntimeError(f"Tokenizer not found for {model_path}")

    def create_completion(
        self,
        prompt: str = "",
        max_tokens: int = 256,
        temperature: float = 0.1,
        stop: list[str] | str | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any] | Iterator[dict[str, Any]]:
        import numpy as np

        encoded = self._tokenizer.encode(prompt)
        input_ids = np.array([encoded.ids], dtype=np.int64)
        attention_mask = np.ones((1, len(encoded.ids)), dtype=np.int64)

        feed: dict[str, Any] = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
        }

        # Initialize past states
        for inp in self._session.get_inputs():
            if inp.name.startswith("past_conv"):
                feed[inp.name] = np.zeros((1, 2048, 3), dtype=np.float32)
            elif inp.name.startswith("past_key_values"):
                feed[inp.name] = np.zeros((1, 8, 0, 64), dtype=np.float32)

        stop_list = [stop] if isinstance(stop, str) else list(stop or [])
        stop_list.extend(["<|im_end|>", "<|endoftext|>", "</s>"])

        output_names = [o.name for o in self._session.get_outputs()]
        generated_tokens: list[int] = []

        for _ in range(max_tokens):
            outputs = self._session.run(output_names, feed)
            output_dict = dict(zip(output_names, outputs))

            logits = output_dict["logits"]
            next_id = int(np.argmax(logits[0, -1, :]))

            token_str = self._tokenizer.decode([next_id])
            generated_tokens.append(next_id)

            if next_id in (0, 1, 2, 7) or any(s in token_str for s in stop_list):
                break

            feed["input_ids"] = np.array([[next_id]], dtype=np.int64)
            feed["attention_mask"] = np.ones((1, feed["attention_mask"].shape[1] + 1), dtype=np.int64)

            for inp in self._session.get_inputs():
                if inp.name.startswith("past_conv."):
                    idx = inp.name.split(".")[1]
                    pres = f"present_conv.{idx}"
                    if pres in output_dict:
                        feed[inp.name] = output_dict[pres]
                elif inp.name.startswith("past_key_values."):
                    parts = inp.name.split(".")
                    layer_idx, kv_type = parts[1], parts[2]
                    pres = f"present.{layer_idx}.{kv_type}"
                    if pres in output_dict:
                        feed[inp.name] = output_dict[pres]

        text = self._tokenizer.decode(generated_tokens)
        for s in stop_list:
            if s in text:
                text = text.split(s)[0]

        result = {
            "id": f"cmpl-onnx-{int(time.time())}",
            "object": "text_completion",
            "created": int(time.time()),
            "model": self.model_path,
            "choices": [
                {
                    "text": text,
                    "index": 0,
                    "logprobs": None,
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": len(encoded.ids),
                "completion_tokens": len(generated_tokens),
                "total_tokens": len(encoded.ids) + len(generated_tokens),
            },
        }
        if stream:
            return iter([result])
        return result

    def create_chat_completion(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int = 256,
        temperature: float = 0.1,
        stop: list[str] | str | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any] | Iterator[dict[str, Any]]:
        prompt = ""
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            prompt += f"<|im_start|>{role}\n{content}<|im_end|>\n"
        prompt += "<|im_start|>assistant\n"

        res = self.create_completion(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=stop,
            stream=False,
            **kwargs,
        )
        text = res["choices"][0]["text"]  # type: ignore[index]
        result = {
            "id": f"chatcmpl-onnx-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self.model_path,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": res["usage"],  # type: ignore[index]
        }
        if stream:
            return iter([result])
        return result

    def __call__(self, prompt: str = "", **kwargs: Any) -> dict[str, Any]:
        return self.create_completion(prompt=prompt, **kwargs)  # type: ignore[return-value]


def get_onnx_model(model_path: str, **kwargs: Any) -> Any:
    """Instantiate an ONNX runtime model wrapper if available, or return ONNXModelFallback."""
    if not model_path:
        return ONNXModelFallback(model_path=model_path, **kwargs)

    # 1. Try direct ONNX Runtime + tokenizers (native, robust)
    if is_onnx_available():
        try:
            return ONNXRuntimeDirectModel(model_path=model_path, **kwargs)
        except Exception as exc:
            logger.warning("Direct ONNX runtime failed for %s (%s); trying fallback.", model_path, exc)

    # 2. Try ONNX GenAI if available
    if is_onnx_genai_available():
        try:
            return ONNXGenAIModel(model_path=model_path, **kwargs)
        except Exception as exc:
            logger.warning("ONNX GenAI failed for %s (%s); trying fallback.", model_path, exc)

    return ONNXModelFallback(model_path=model_path, **kwargs)
