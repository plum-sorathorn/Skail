"""SLM Architect & 100ms Circuit Breaker.

Embedded Qwen 2.5 Coder 0.5B Instruct / Outlines constrained generation producing
strictly validated ExecutionPlan JSON objects. Enforces a 100ms circuit breaker timeout
with graceful fail-soft fallback.
"""
from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

from autoconduck._compat import (
    is_outlines_available,
    get_onnx_model,
    is_onnx_available,
    is_onnx_genai_available,
)
from autoconduck.routing.model_pool import CapabilitySLA

logger = logging.getLogger(__name__)

# Reused single-thread executor for sync circuit-breaker (no per-call startup cost).
# ONNX inference thread is abandoned on timeout (cannot be killed) — route proceeds fail-soft.
_SLM_EXECUTOR: ThreadPoolExecutor | None = None
_SLM_EXECUTOR_LOCK = __import__("threading").Lock()

_GLOBAL_LLM_CACHE = None
_GLOBAL_LLM_CACHE_LOCK = __import__("threading").Lock()
_INFER_BUSY = False
_INFER_BUSY_LOCK = __import__("threading").Lock()


def _get_slm_executor() -> ThreadPoolExecutor:
    global _SLM_EXECUTOR
    with _SLM_EXECUTOR_LOCK:
        if _SLM_EXECUTOR is None:
            _SLM_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="slm-infer")
        return _SLM_EXECUTOR


def _infer_deterministic_task_type(text: str) -> tuple[str, int]:
    """Infer deterministic baseline task type and complexity from text in < 0.1ms (Brain Ladder baseline)."""
    if not text:
        return "chat", 1
    lower = text.lower()
    if any(k in lower for k in ["git commit", "git status", "git diff", "git add", "git log", "format code"]):
        return "git_ops", 2
    if any(k in lower for k in ["refactor", "rewrite", "overhaul", "redesign", "restructure", "clean up"]):
        return "refactor", 7
    if any(k in lower for k in ["debug", "stack trace", "traceback", "exception", "fix bug", "error:", "fail"]):
        return "debug", 6
    if any(k in lower for k in ["edit", "update", "modify", "change", "add", "implement", "patch", "create"]):
        return "single_edit", 4
    if any(k in lower for k in ["explain", "how does", "what is", "why does", "tell me about"]):
        return "explain", 3
    if any(k in lower for k in ["search", "find", "grep", "locate", "recon", "explore"]):
        return "recon", 3
    return "chat", 2


def normalize_confidence(value: Any) -> float:
    """Return a safe SLM confidence, defaulting conservatively to 0.5."""
    try:
        parsed = float(value)
        if parsed != parsed:
            raise ValueError("NaN confidence")
        return max(0.05, min(0.95, parsed))
    except (TypeError, ValueError, OverflowError):
        return 0.5


VALID_TASK_TYPES = {
    "chat", "explain", "recon", "single_edit", "multi_edit", "debug", "refactor",
    "full_workflow", "git_ops", "routine", "read_answer", "knowledge_query", "research",
}


def sanitize_task_type(val: Any) -> str:
    """Coerce an arbitrary value into a valid ExecutionPlan task_type Literal.

    This is a last-resort Pydantic pre-validator — NOT a classification heuristic.
    The authoritative fix for unconstrained SLM output is grammar/JSON-schema constrained
    decoding at the generation layer (outlines_fallback.py). This function only normalizes
    near-exact matches (case, whitespace, dash/underscore/space separators) and falls back
    to "chat" for anything unrecognizable. Keyword heuristics have been intentionally
    removed: they operated on the SLM's label string after semantic signal was already
    lost, not on the original user message, making them unreliable and order-dependent.
    """
    if not isinstance(val, str) or not val:
        return "chat"
    # Normalize: lowercase, strip whitespace, unify separators (spaces/dashes → underscores)
    s = val.strip().lower().replace("-", "_").replace(" ", "_")
    if s in VALID_TASK_TYPES:
        return s
    return "chat"


def resolve_slm_path(model_path: str = "", config: Any = None) -> str:
    """Resolve the active SLM model path from arguments, config, or default directory."""
    candidate = model_path
    if not candidate and config is not None:
        candidate = (
            getattr(getattr(config, "selection", None), "slm_model_path", "")
            or getattr(config, "slm_model_path", "")
        )
    if not candidate:
        try:
            from autoconduck.config import get_config
            cfg = get_config()
            candidate = getattr(getattr(cfg, "selection", None), "slm_model_path", "")
        except Exception:
            candidate = ""

    if not candidate:
        return ""

    p = Path(candidate)
    if p.is_file() and p.stat().st_size > 0:
        return str(p)

    # Check ~/.autoconduck/models/<name>
    from autoconduck.routing.slm_downloader import get_default_models_dir
    models_dir = get_default_models_dir()
    by_name = models_dir / p.name
    if by_name.is_file() and by_name.stat().st_size > 0:
        return str(by_name)

    # Check ~/.autoconduck/<candidate>
    ad_home = Path.home() / ".autoconduck" / candidate
    if ad_home.is_file() and ad_home.stat().st_size > 0:
        return str(ad_home)

    return candidate


# --- Harness-agnostic boilerplate stripping (Layer 2) -----------------------
# AutoConduck sits in front of many out-of-our-control coding-agent harnesses
# (opencode, Claude Code, Pi, MCP shims, ...) which inject their own stable
# bookkeeping into the user-role message stream (date/cwd preambles, sentinel
# blocks, etc.). We do NOT enumerate harnesses; we strip a small, curated,
# conservative family of well-known *shapes* of non-semantic boilerplate.
# Unknown/novel boilerplate is deliberately left untouched here -- defense
# against it comes from the conservative signal-gating in _raw_infer
# (Layer 3), never from an ever-growing strip dictionary.
_SYSTEM_REMINDER_RE = re.compile(r"<system-reminder\b[^>]*>.*?</system-reminder>", re.IGNORECASE | re.DOTALL)
_SYSTEM_REMINDER_UNCLOSED_RE = re.compile(r"<system-reminder\b[^>]*>.*", re.IGNORECASE | re.DOTALL)
_SYSTEM_NOTE_SENTINEL_RE = re.compile(r"<={3,}\s*SYSTEM NOTE\s*={3,}>.*?(?=\n\s*\n|\Z)", re.IGNORECASE | re.DOTALL)
_SYSTEM_NOTE_BRACKET_RE = re.compile(r"\[System Note:[^\]]*\]", re.IGNORECASE | re.DOTALL)
_TODAY_META_LINE_RE = re.compile(r"^[ \t]*Today(?:'s date)?\s*(?:is|:)\s*.*$", re.IGNORECASE | re.MULTILINE)
_CWD_META_LINE_RE = re.compile(r"^[ \t]*Current working directory\s*:\s*.*$", re.IGNORECASE | re.MULTILINE)


def _strip_harness_noise(text: str) -> tuple[str, bool]:
    """Strip a curated family of non-semantic harness/session boilerplate.

    Generalizes the old <system-reminder>-only strip to the small set of
    DOCUMENTED, stable shapes that coding-agent harnesses are known to
    inject into the user role: <system-reminder>...</system-reminder>
    (closed and unclosed), <=== SYSTEM NOTE ===> sentinel blocks,
    [System Note: ...] brackets, and leading "Today is/: ..." /
    "Current working directory: ..." meta lines. This must never touch the
    actual question/content -- it only removes whole recognized blocks or
    whole meta lines anchored at line-start.

    Returns (cleaned_text, noise_removed) so callers can treat evidence
    derived purely from stripped noise as invalid (see _raw_infer).
    """
    if not text:
        return text, False
    original = text
    cleaned = text
    if "<system-reminder" in cleaned.lower():
        cleaned = _SYSTEM_REMINDER_RE.sub(" ", cleaned)
        cleaned = _SYSTEM_REMINDER_UNCLOSED_RE.sub(" ", cleaned)
    cleaned = _SYSTEM_NOTE_SENTINEL_RE.sub(" ", cleaned)
    cleaned = _SYSTEM_NOTE_BRACKET_RE.sub(" ", cleaned)
    cleaned = _TODAY_META_LINE_RE.sub(" ", cleaned)
    cleaned = _CWD_META_LINE_RE.sub(" ", cleaned)
    return cleaned, cleaned != original


class ExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="allow")
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    task_type: Literal[
        "chat", "explain", "recon", "single_edit", "multi_edit", "debug", "refactor", "full_workflow", "git_ops",
        "routine", "read_answer", "knowledge_query", "research",
    ] = "chat"
    complexity_score: int = Field(ge=1, le=10, default=5)
    suggested_sla: CapabilitySLA = Field(default_factory=lambda: CapabilitySLA(min_context=16000, requires_tools=True, max_cost=1.5))
    rationale: str = ""
    fallback_used: bool = False
    schema_version: str = "0.4"

    @field_validator("task_type", mode="before")
    @classmethod
    def _sanitize_task_type_field(cls, v: Any) -> str:
        return sanitize_task_type(v)

    @property
    def summary(self) -> str:
        return self.rationale or f"Task execution plan ({self.task_type})"

    # Legacy attribute fallback for Phase-1B consumers (orchestrator/tests) not yet stripped.
    # Provides defaults for removed fields so old code does not raise AttributeError.
    def __getattr__(self, name: str) -> Any:
        # Check extra first (pydantic extra=allow)
        try:
            extra = object.__getattribute__(self, "__pydantic_extra__")
            if extra is not None and name in extra:
                return extra[name]
        except AttributeError:
            pass
        _legacy_defaults: dict[str, Any] = {
            "route": "fast_direct",
            "needs_rag": False,
            "rag_queries": [],
            "subtasks": [],
            "phases": [],
            "synthesizer_sla": CapabilitySLA(requires_reasoning=True),
            "plan_id": "",
            "revision": 0,
            "session_status": "active",
            "ledger": [],
            "terminal_decision": None,
        }
        if name in _legacy_defaults:
            return _legacy_defaults[name]
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")


class SLMPlanner:
    """Intelligent task decomposition and routing planner."""

    def __init__(self, model_path: str = "", circuit_breaker_ms: float = 5000.0) -> None:
        self.model_path = model_path
        self.circuit_breaker_ms = circuit_breaker_ms
        self._llm = None

    def _extract_last_user_text(self, messages: list[dict[str, Any]]) -> tuple[str, bool]:
        """Extract the user's CURRENT utterance for classification (Layer 1).

        Design decision: classify on the LAST user/human message only, never
        the cumulative concatenation of the whole user-role history. Harnesses
        we do not control (opencode, Claude Code, Pi, MCP shims, ...) commonly
        re-send a stable boilerplate preamble in messages[0] (or every turn) --
        concatenating the whole stream lets that preamble's keywords leak into
        classification regardless of curated stripping. Restricting to the
        latest message removes that entire poisoning vector for ANY harness,
        with no per-harness enumeration.

        Why this is safe: TurnGuard (server/turn_guard.py) already intercepts
        tool-loop turns before the planner is ever invoked (dispatcher.py), so
        `_raw_infer` only ever runs on fresh, non-tool-loop dispatch decisions.
        A legitimate multi-turn continuation ("now also add rate limiting to
        the session handler we discussed") that references earlier context
        without repeating the code-domain signal in its own text will,
        worst case, under-trigger the DAG and route fast_direct -- the work
        still gets done correctly, just without decomposition. Given the
        stated cost asymmetry (a wrongly-triggered dynamic_dag fanout is far
        more expensive than a direct dispatch), under-triggering on stale
        context is the correct conservative failure direction; we deliberately
        do NOT widen this to a bounded trailing window, since any window > 1
        message reintroduces the same boilerplate-repetition poisoning vector
        this layer exists to remove.

        Returns (cleaned_text, noise_removed) so callers can record
        provenance in the plan rationale and avoid treating stripped-noise
        artifacts as classification evidence.
        """
        last_text = ""
        for m in reversed(messages):
            if not isinstance(m, dict):
                continue
            if m.get("role") not in ("user", "human"):
                continue
            c = m.get("content")
            if isinstance(c, str):
                last_text = c
            elif isinstance(c, list):
                parts = []
                for part in c:
                    if isinstance(part, dict) and part.get("type") == "text":
                        parts.append(part.get("text", ""))
                    elif isinstance(part, str):
                        parts.append(part)
                last_text = " ".join(parts)
            break
        cleaned, noise_removed = _strip_harness_noise(last_text.strip())
        return cleaned.strip(), noise_removed

    def _extract_user_text(self, messages: list[dict[str, Any]]) -> str:
        """Backward-compatible wrapper returning only the cleaned text."""
        text, _ = self._extract_last_user_text(messages)
        return text

    def _create_fallback_plan(self, messages: list[dict[str, Any]], reason: str = "") -> ExecutionPlan:
        """Create a safe fallback execution plan with deterministic baseline classification."""
        user_text = self._extract_user_text(messages) if messages else ""
        task_type, complexity = _infer_deterministic_task_type(user_text)
        return ExecutionPlan(
            confidence=0.5,
            task_type=task_type,
            complexity_score=complexity,
            suggested_sla=CapabilitySLA(min_context=16000, requires_tools=True, max_cost=1.5),
            rationale=reason or "Fallback plan due to SLM circuit breaker or parsing exception",
            fallback_used=True,
        )

    def _ensure_llm_loaded(self, config: Any = None) -> None:
        """Ensure the underlying SLM runtime model is loaded and warmed up."""
        if self._llm is not None:
            return
            
        global _GLOBAL_LLM_CACHE
        with _GLOBAL_LLM_CACHE_LOCK:
            if _GLOBAL_LLM_CACHE is not None:
                self._llm = _GLOBAL_LLM_CACHE
                return

            model_path = resolve_slm_path(self.model_path, config)
            if not model_path:
                return

            resolved_path = Path(model_path)
            if not resolved_path.is_file():
                logger.debug("SLM model file not found at %s; using fallback.", model_path)
                return

            lower_path = model_path.lower()
            if lower_path.endswith(".onnx") or is_onnx_genai_available() or is_onnx_available():
                try:
                    self._llm = get_onnx_model(model_path)
                    _GLOBAL_LLM_CACHE = self._llm
                except Exception as exc:
                    logger.warning("Failed to initialize ONNX SLM from %s: %s", model_path, exc)
            else:
                try:
                    self._llm = get_onnx_model(model_path)
                    _GLOBAL_LLM_CACHE = self._llm
                except Exception as exc:
                    logger.warning("Failed to initialize SLM from %s: %s", model_path, exc)

            # Perform single-token warmup forward pass to pre-compile execution kernels
            if self._llm is not None and not getattr(self._llm, "_is_fallback", False):
                try:
                    if hasattr(self._llm, "create_completion"):
                        self._llm.create_completion("{}", max_tokens=1)
                except Exception:
                    pass

    def _raw_infer(self, messages: list[dict[str, Any]], config: Any = None) -> str | dict[str, Any]:
        """Classify the request and produce an ExecutionPlan dict using the SLM."""
        text, noise_removed = self._extract_last_user_text(messages)
        if not text:
            return self._create_fallback_plan(messages, reason="Empty or system-only messages").model_dump()

        # 1. Ensure SLM is loaded
        self._ensure_llm_loaded(config)

        # 2. Check dependencies / fallback
        if self._llm is None or getattr(self._llm, "_is_fallback", False):
            logger.debug("SLM model unavailable or using fallback; routing via fallback plan.")
            return self._create_fallback_plan(messages, reason="SLM model unavailable or fallback").model_dump()

        # 3. Bound instruction length to prevent CPU prefill latency spikes
        bounded_text = text[:800] if len(text) > 800 else text

        # 4. Define schema
        class TaskClassification(BaseModel):
            task_type: Literal["chat", "explain", "recon", "single_edit", "multi_edit", "debug", "refactor", "full_workflow", "git_ops", "routine", "read_answer", "knowledge_query", "research"] = Field(default="chat", description="Task category")
            confidence: Any = Field(default=0.5, description="Confidence in the task_type decision, from 0 to 1")
            complexity_score: int = Field(default=1, ge=1, le=10, description="1=trivial typo/chat, 10=massive architectural overhaul")
            rationale: str = Field(default="SLM direct routing", description="Brief explanation of the routing decision")

            @field_validator("task_type", mode="before")
            @classmethod
            def _validate_task_type(cls, value: Any) -> str:
                return sanitize_task_type(value)

        # 5. Generate structured output with tight token budget (<500ms on CPU)
        from autoconduck._compat.outlines_fallback import generate_structured_json
        prompt = (
            f"Classify the following software engineering instruction for automated routing:\n\n"
            f"Instruction: {bounded_text}\n\n"
            f"task_type MUST be one of: chat, explain, recon, single_edit, multi_edit, debug, refactor, full_workflow, git_ops, routine, read_answer, knowledge_query, research.\n"
            f"confidence is a float from 0 to 1 reflecting certainty in the task_type decision.\n"
            f"Output valid JSON with fields: task_type, complexity_score (1-10), rationale, confidence."
        )

        result = generate_structured_json(self._llm, prompt, TaskClassification, max_tokens=48)
        if not isinstance(result, TaskClassification):
            logger.debug("SLM produced non-TaskClassification result; using fallback plan.")
            return self._create_fallback_plan(messages, reason="SLM structured output validation failed").model_dump()

        return {
            "confidence": normalize_confidence(result.confidence),
            "task_type": result.task_type,
            "complexity_score": result.complexity_score,
            "suggested_sla": CapabilitySLA(min_context=16000, requires_tools=True, max_cost=1.5),
            "rationale": f"SLM (score {result.complexity_score}): {result.rationale} " + ("(harness noise stripped)" if noise_removed else ""),
            "fallback_used": False,
        }

    def plan_sync(self, messages: list[dict[str, Any]], config: Any = None) -> ExecutionPlan:
        """Generate an ExecutionPlan synchronously with circuit breaker / fallback protection.

        Sync SLM inference is bounded by slm_circuit_breaker_timeout_ms via a reused
        single-thread ThreadPoolExecutor. On timeout/exception a fallback plan is
        returned. Note: the ONNX inference thread is abandoned on timeout (cannot be
        killed) — route proceeds fail-soft.
        """
        # Determine timeout (ms -> sec). Fallback to instance default if config missing.
        timeout_ms = (
            float(getattr(getattr(config, "selection", None), "slm_circuit_breaker_timeout_ms", self.circuit_breaker_ms))
            if config is not None and hasattr(config, "selection")
            else float(self.circuit_breaker_ms)
        )
        timeout_sec = timeout_ms / 1000.0

        # Concurrency protection: if a previous abandoned inference is still occupying the executor/CPU,
        # fail-soft immediately rather than queuing and causing cascading timeouts.
        global _INFER_BUSY
        with _INFER_BUSY_LOCK:
            if _INFER_BUSY:
                logger.debug("SLM inference currently busy/recovering; degrading to deterministic fallback.")
                return self._create_fallback_plan(messages, reason="SLM inference busy")
            _INFER_BUSY = True

        try:
            executor = _get_slm_executor()
            fut = executor.submit(self._raw_infer, messages, config)
            try:
                res = fut.result(timeout=timeout_sec)
            except Exception as exc:
                # Distinguish timeout for rationale
                is_timeout = "TimeoutError" in type(exc).__name__ or "timeout" in str(exc).lower() or isinstance(exc, TimeoutError)
                from concurrent.futures import TimeoutError as _FETimeout

                if isinstance(exc, _FETimeout):
                    is_timeout = True
                if is_timeout:
                    logger.warning("SLM plan_sync exceeded %sms circuit breaker; degrading to fallback.", timeout_ms)
                    global _SLM_EXECUTOR
                    with _SLM_EXECUTOR_LOCK:
                        if _SLM_EXECUTOR is not None:
                            _SLM_EXECUTOR.shutdown(wait=False)
                        _SLM_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="slm-infer")
                    return self._create_fallback_plan(messages, reason=f"Circuit breaker timeout (> {timeout_ms:g}ms)")
                logger.warning("SLM sync planner error: %s; degrading to fallback.", exc)
                return self._create_fallback_plan(messages, reason=f"Sync planning error: {exc}")
            finally:
                with _INFER_BUSY_LOCK:
                    _INFER_BUSY = False

            if isinstance(res, ExecutionPlan):
                return res
            if isinstance(res, str):
                try:
                    data = json.loads(res)
                except Exception:
                    return self._create_fallback_plan(messages, reason="Unparseable non-JSON output")
            elif isinstance(res, dict):
                data = res
            else:
                return self._create_fallback_plan(messages, reason="Invalid SLM output type")

            if not isinstance(data, dict):
                return self._create_fallback_plan(messages, reason="Missing plan structure")

            data = dict(data)
            try:
                raw_confidence = data.get("confidence")
                if raw_confidence is not None and not 0 <= float(raw_confidence) <= 1:
                    return self._create_fallback_plan(messages, reason="Confidence outside valid range")
            except (TypeError, ValueError, OverflowError):
                return self._create_fallback_plan(messages, reason="Invalid confidence")
            data["confidence"] = normalize_confidence(data.get("confidence"))
            return ExecutionPlan.model_validate(data)
        except Exception as exc:
            logger.warning("SLM sync planner error: %s; degrading to fallback.", exc)
            return self._create_fallback_plan(messages, reason=f"Sync planning error: {exc}")

    async def plan(self, messages: list[dict[str, Any]], config: Any = None) -> ExecutionPlan:
        """Generate an ExecutionPlan with circuit breaker protection."""
        timeout_ms = (
            float(getattr(config.selection, "slm_circuit_breaker_timeout_ms", self.circuit_breaker_ms))
            if config is not None and hasattr(config, "selection")
            else self.circuit_breaker_ms
        )
        timeout_sec = timeout_ms / 1000.0

        import inspect

        try:
            # Execute inference with timeout
            if inspect.iscoroutinefunction(self._raw_infer):
                res = await asyncio.wait_for(self._raw_infer(messages, config), timeout=timeout_sec)
            else:
                res = await asyncio.wait_for(
                    asyncio.to_thread(self._raw_infer, messages, config),
                    timeout=timeout_sec,
                )

            if isinstance(res, ExecutionPlan):
                return res

            if isinstance(res, str):
                try:
                    data = json.loads(res)
                except Exception:
                    return self._create_fallback_plan(messages, reason="Unparseable non-JSON output")
            elif isinstance(res, dict):
                data = res
            else:
                return self._create_fallback_plan(messages, reason="Invalid SLM output type")

            if not isinstance(data, dict):
                return self._create_fallback_plan(messages, reason="Missing plan structure")

            data = dict(data)
            try:
                raw_confidence = data.get("confidence")
                if raw_confidence is not None and not 0 <= float(raw_confidence) <= 1:
                    return self._create_fallback_plan(messages, reason="Confidence outside valid range")
            except (TypeError, ValueError, OverflowError):
                return self._create_fallback_plan(messages, reason="Invalid confidence")
            data["confidence"] = normalize_confidence(data.get("confidence"))
            return ExecutionPlan.model_validate(data)

        except asyncio.TimeoutError:
            logger.warning("SLM planner exceeded %sms circuit breaker timeout; degrading to fallback.", timeout_ms)
            return self._create_fallback_plan(messages, reason=f"Circuit breaker timeout (> {timeout_ms:g}ms)")
        except Exception as exc:
            logger.warning("SLM planner encountered error: %s; degrading to fallback.", exc)
            return self._create_fallback_plan(messages, reason=f"Inference error: {exc}")
