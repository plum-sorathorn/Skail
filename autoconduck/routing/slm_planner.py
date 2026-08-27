"""SLM Architect & 100ms Circuit Breaker.

Embedded Qwen 2.5 Coder 0.5B Instruct / Outlines constrained generation producing
strictly validated ExecutionPlan JSON objects. Enforces a 100ms circuit breaker timeout
with graceful fail-soft fallback.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
import re
import time
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator

from autoconduck._compat import (
    get_onnx_model,
    is_onnx_available,
    is_onnx_genai_available,
    is_outlines_available,
)
from autoconduck.routing.model_pool import CapabilitySLA

logger = logging.getLogger(__name__)


def normalize_confidence(value: Any) -> float:
    """Return a safe SLM confidence, defaulting conservatively to 0.5."""
    try:
        parsed = float(value)
        if parsed != parsed:
            raise ValueError("NaN confidence")
        return max(0.05, min(0.95, parsed))
    except (TypeError, ValueError, OverflowError):
        return 0.5


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


PhaseStatus = Literal["pending", "ready", "in_progress", "completed", "skipped", "replaced", "blocked"]
MutationAction = Literal["keep", "adjust", "set_status", "skip", "replace", "append", "end", "verify"]
TerminalDecision = Literal["completed", "abandoned", "superseded", "expired"]


class Phase(BaseModel):
    """Harness-facing durable phase; AutoConduck only plans and supervises it."""

    id: str
    goal: str
    dependencies: list[str] = Field(default_factory=list)
    parallel_group: str | None = None
    parallel_to: list[str] = Field(default_factory=list)
    scope: list[str] = Field(default_factory=list)
    execution_mode: Literal["harness", "autoconduck_recon"] = "harness"
    post_condition: str = ""
    verify: list[str] = Field(default_factory=list)
    status: PhaseStatus = "pending"
    evidence: list[str] = Field(default_factory=list)


class SubTaskSpec(BaseModel):
    id: str
    goal: str
    scope: list[str] = Field(default_factory=list)
    role: Literal["recon", "read", "edit", "verify", "bash", "reasoning"] = "read"
    depends_on: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    output_contract: str = ""
    read_budget: int = 5

    def to_phase(self) -> Phase:
        return Phase(
            id=self.id, goal=self.goal, dependencies=list(self.depends_on),
            scope=list(self.scope), execution_mode="autoconduck_recon" if self.role in ("recon", "read") else "harness",
            verify=list(getattr(self.output_contract, "verify", []) or []) if not isinstance(self.output_contract, str) else [],
        )


SubTask = SubTaskSpec


class ExecutionPlan(BaseModel):
    route: Literal["fast_direct", "dynamic_dag"] = "fast_direct"
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    task_type: Literal[
        "chat", "explain", "recon", "single_edit", "multi_edit", "debug", "refactor", "full_workflow", "git_ops",
        "routine", "read_answer", "knowledge_query", "research",
    ] = "chat"
    suggested_sla: CapabilitySLA = Field(default_factory=CapabilitySLA)
    needs_rag: bool = False
    rag_queries: list[str] = Field(default_factory=list)
    subtasks: list[SubTaskSpec] = Field(default_factory=list)
    synthesizer_sla: CapabilitySLA = Field(default_factory=lambda: CapabilitySLA(requires_reasoning=True))
    rationale: str = ""
    fallback_used: bool = False
    schema_version: str = "0.4"
    plan_id: str = ""
    revision: int = Field(default=0, ge=0)
    session_status: Literal["active", "terminal", "stale"] = "active"
    phases: list[Phase] = Field(default_factory=list)
    ledger: list[dict[str, Any]] = Field(default_factory=list)
    terminal_decision: TerminalDecision | None = None

    @field_validator("subtasks", mode="before")
    @classmethod
    def _sanitize_subtasks(cls, v: Any) -> list[Any]:
        """Sanitize subtask lists and ensure no self-referential cycles."""
        if not isinstance(v, list):
            return []
        sanitized = []
        for item in v:
            if isinstance(item, dict):
                task_id = str(item.get("id", ""))
                deps = [d for d in item.get("depends_on", []) if d != task_id]
                item_copy = dict(item)
                item_copy["depends_on"] = deps
                sanitized.append(item_copy)
            elif isinstance(item, SubTaskSpec):
                deps = [d for d in item.depends_on if d != item.id]
                item.depends_on = deps
                sanitized.append(item)
            else:
                sanitized.append(item)
        return sanitized

    @field_validator("phases", mode="before")
    @classmethod
    def _legacy_phases(cls, value: Any) -> list[Any]:
        return value if isinstance(value, list) else []

    @model_validator(mode="after")
    def _validate_session_plan(self) -> "ExecutionPlan":
        legacy_derived = bool(self.subtasks) and (
            not self.phases or {phase.id for phase in self.phases} == {task.id for task in self.subtasks}
        )
        if legacy_derived:
            self.phases = [task.to_phase() for task in self.subtasks]
        ids = [phase.id for phase in self.phases]
        if len(ids) != len(set(ids)):
            raise ValueError("phase IDs must be unique")
        known = set(ids)
        if legacy_derived:
            self.phases = [phase.model_copy(update={
                "dependencies": [dep for dep in phase.dependencies if dep in known],
                "parallel_to": [peer for peer in phase.parallel_to if peer in known],
            }) for phase in self.phases]
        for phase in self.phases:
            refs = set(phase.dependencies) | set(phase.parallel_to)
            if not refs <= known:
                raise ValueError("phase references an unknown phase")
            if set(phase.parallel_to) & set(phase.dependencies):
                raise ValueError("parallel phases cannot directly depend on one another")
        visiting: set[str] = set()
        visited: set[str] = set()
        graph = {p.id: p.dependencies for p in self.phases}
        def visit(node: str) -> None:
            if node in visiting:
                raise ValueError("phase dependencies must be acyclic")
            if node in visited:
                return
            visiting.add(node)
            for dep in graph[node]:
                visit(dep)
            visiting.remove(node)
            visited.add(node)
        try:
            for node in graph:
                visit(node)
        except ValueError:
            if not legacy_derived:
                raise
            # Legacy callers historically received cycle-safe subtasks. Preserve
            # that compatibility while strict explicit session phases reject cycles.
            self.phases = [phase.model_copy(update={"dependencies": []}) for phase in self.phases]
        return self

    @property
    def summary(self) -> str:
        return self.rationale or f"Task execution plan ({self.task_type})"


class EscalationVerdict(BaseModel):
    should_escalate: bool = False
    reason: str = ""
    suggested_plan: ExecutionPlan | None = None
    action: MutationAction = "keep"
    mutation: "PlanMutation | None" = None


class PlanMutation(BaseModel):
    """Small validated supervisor operation, applied with revision CAS."""

    schema_version: str = "0.4"
    plan_id: str = ""
    base_revision: int = Field(default=0, ge=0)
    action: MutationAction = "keep"
    reason: str = ""
    phase_id: str | None = None
    status: PhaseStatus | None = None
    phase: Phase | None = None
    phases: list[Phase] = Field(default_factory=list)
    terminal_decision: TerminalDecision | None = None


SessionPlanMutation = PlanMutation


def apply_plan_mutation(plan: ExecutionPlan, mutation: PlanMutation) -> ExecutionPlan:
    """Apply one mutation atomically by constructing and revalidating a new plan."""
    if mutation.plan_id and mutation.plan_id != plan.plan_id:
        raise ValueError("mutation plan ID does not match")
    if mutation.base_revision != plan.revision:
        raise ValueError("stale plan revision")
    phases = list(plan.phases or [p.to_phase() for p in plan.subtasks])
    by_id = {phase.id: phase for phase in phases}
    if mutation.action in ("adjust", "set_status") and mutation.phase_id:
        if mutation.phase_id not in by_id:
            raise ValueError("unknown mutation phase")
        by_id[mutation.phase_id] = by_id[mutation.phase_id].model_copy(update={"status": mutation.status or by_id[mutation.phase_id].status})
    elif mutation.action == "skip" and mutation.phase_id:
        if mutation.phase_id not in by_id:
            raise ValueError("unknown mutation phase")
        by_id[mutation.phase_id] = by_id[mutation.phase_id].model_copy(update={"status": "skipped", "evidence": [mutation.reason] if mutation.reason else by_id[mutation.phase_id].evidence})
    elif mutation.action == "replace":
        if not mutation.phase or mutation.phase.id not in by_id:
            raise ValueError("replacement must target an existing phase")
        by_id[mutation.phase.id] = mutation.phase
    elif mutation.action == "append":
        for phase in mutation.phases or ([mutation.phase] if mutation.phase else []):
            if phase is None or phase.id in by_id:
                raise ValueError("appended phase ID must be new")
            by_id[phase.id] = phase
    decision = mutation.terminal_decision if mutation.action == "end" else plan.terminal_decision
    return plan.model_copy(update={"phases": list(by_id.values()), "revision": plan.revision + 1,
                                   "session_status": "terminal" if decision else plan.session_status,
                                   "terminal_decision": decision,
                                   "ledger": [*plan.ledger, {"revision": plan.revision + 1, "action": mutation.action, "reason": mutation.reason}]})


def plan_completion_decision(plan: ExecutionPlan) -> TerminalDecision | None:
    phases = plan.phases or [p.to_phase() for p in plan.subtasks]
    if phases and all(p.status in ("completed", "skipped", "replaced") and (p.status != "completed" or p.evidence or not p.verify) for p in phases):
        return "completed"
    return None


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
        """Create a safe fallback execution plan."""
        return ExecutionPlan(
            route="fast_direct",
            confidence=0.5,
            task_type="chat",
            suggested_sla=CapabilitySLA(min_context=16000, requires_tools=True, max_cost=1.5),
            synthesizer_sla=CapabilitySLA(requires_reasoning=True),
            needs_rag=False,
            rag_queries=[],
            subtasks=[],
            rationale=reason or "Fallback plan due to SLM circuit breaker or parsing exception",
            fallback_used=True,
        )

    def create_escalation_plan(self, messages: list[dict[str, Any]], reason: str = "") -> ExecutionPlan:
        """Create deterministic stagnation recovery; confidence=0.95 is intentional.

        This safety escalation constant is not an SLM-derived confidence estimate.
        """
        last_tool = "tool"
        for m in reversed(messages):
            if isinstance(m, dict) and m.get("role") in ("tool", "function"):
                last_tool = str(m.get("name") or "tool")
                break

        subtasks = [
            SubTaskSpec(
                id="diagnose_failure",
                goal=f"Analyze error traceback and stagnation root-cause on {last_tool}",
                role="recon",
                depends_on=[],
            ),
            SubTaskSpec(
                id="remediate_loop",
                goal="Formulate precise code modification or alternative tool action to break failure loop",
                role="edit",
                depends_on=["diagnose_failure"],
            ),
            SubTaskSpec(
                id="verify_recovery",
                goal="Verify resolution without repeating the previous error state",
                role="verify",
                depends_on=["remediate_loop"],
            ),
        ]
        return ExecutionPlan(
            route="dynamic_dag",
            confidence=0.95,
            task_type="debug",
            suggested_sla=CapabilitySLA(
                min_context=32000,
                requires_reasoning=True,
                requires_tools=True,
                min_capability_score=0.45,
                max_cost=float("inf"),
            ),
            synthesizer_sla=CapabilitySLA(
                requires_reasoning=True,
                requires_tools=True,
                min_capability_score=0.45,
                max_cost=float("inf"),
                min_output_tokens=8192,
            ),
            needs_rag=False,
            rag_queries=[],
            subtasks=subtasks,
            rationale=reason or "Stagnation escalation recovery plan",
            fallback_used=False,
        )

    def _ensure_llm_loaded(self, config: Any = None) -> None:
        """Ensure the underlying SLM runtime model is loaded."""
        if self._llm is not None:
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
            except Exception as exc:
                logger.warning("Failed to initialize ONNX SLM from %s: %s", model_path, exc)
        else:
            try:
                self._llm = get_onnx_model(model_path)
            except Exception as exc:
                logger.warning("Failed to initialize SLM from %s: %s", model_path, exc)

    def evaluate_session_trajectory(
        self,
        messages: list[dict[str, Any]],
        current_plan: ExecutionPlan | None = None,
        session_stats: dict[str, Any] | None = None,
        config: Any = None,
    ) -> EscalationVerdict:
        """Evaluate whether an in-flight tool loop should be promoted to a Dynamic DAG plan."""
        stats = session_stats or {}
        read_count = int(stats.get("read_count", 0))
        edit_count = int(stats.get("edit_count", 0))
        replan_reason = str(stats.get("replan_reason", "Read-heavy tool loop"))
        task_type = (current_plan.task_type if current_plan else getattr(config, "task_type", None)) or "refactor"

        # Check config gating
        eligible_types = ["refactor", "full_workflow", "multi_edit", "debug"]
        if config is not None and hasattr(config, "selection"):
            eligible_types = getattr(config.selection, "replan_eligible_task_types", eligible_types)
            if not getattr(config.selection, "mid_execution_replan_enabled", True):
                return EscalationVerdict(should_escalate=False, reason="Mid-execution replanning disabled in config")

        text, noise_removed = self._extract_last_user_text(messages)

        # 1. Attempt SLM inference if model is available
        self._ensure_llm_loaded(config)
        if self._llm is not None and not getattr(self._llm, "_is_fallback", False):
            try:
                class TrajectoryEvaluation(BaseModel):
                    should_escalate_to_dag: bool = Field(
                        description="True if agent is stuck reading/exploring without writing and needs DAG task decomposition"
                    )
                    reason: str = Field(description="Brief justification for escalation or continuation")
                    task_type: Literal[
                        "refactor", "multi_edit", "single_edit", "debug", "full_workflow", "chat", "explain"
                    ] = "refactor"
                    confidence: Any = 0.5

                from autoconduck._compat.outlines_fallback import generate_structured_json

                prompt = (
                    f"Evaluate this agent session trajectory.\n"
                    f"User goal: {text[:200]}\n"
                    f"Read tool calls: {read_count}, Edit tool calls: {edit_count}\n"
                    f"Trigger context: {replan_reason}\n"
                    f"Should this session be escalated to a structured multi-agent DAG plan?\n"
                    f"Respond with JSON: {{should_escalate_to_dag: bool, reason: str, task_type: str, confidence: float}}"
                )
                result = generate_structured_json(self._llm, prompt, TrajectoryEvaluation)
                if isinstance(result, TrajectoryEvaluation):
                    if result.should_escalate_to_dag:
                        subtasks = [
                            SubTaskSpec(id="recon", goal=f"Synthesize findings from read operations: {text[:60]}", role="recon"),
                            SubTaskSpec(id="target_edits", goal="Implement code modifications according to goal", role="edit", depends_on=["recon"]),
                            SubTaskSpec(id="verify", goal="Verify changes with tests", role="verify", depends_on=["target_edits"]),
                        ]
                        plan = ExecutionPlan(
                            route="dynamic_dag",
                            confidence=normalize_confidence(result.confidence),
                            task_type=result.task_type if result.task_type in eligible_types else "refactor",
                            suggested_sla=CapabilitySLA(min_context=32000, requires_tools=True, min_capability_score=0.45),
                            synthesizer_sla=CapabilitySLA(requires_reasoning=True, requires_tools=True, min_capability_score=0.45, min_output_tokens=8192),
                            subtasks=subtasks,
                            rationale=f"Mid-execution SLM replan: {result.reason}",
                            fallback_used=False,
                        )
                        return EscalationVerdict(
                            should_escalate=True,
                            reason=f"SLM evaluated trajectory: {result.reason}",
                            suggested_plan=plan,
                        )
                    else:
                        return EscalationVerdict(
                            should_escalate=False,
                            reason=f"SLM decided against escalation: {result.reason}",
                        )
            except Exception as exc:
                logger.debug("SLM trajectory evaluation failed: %s; falling back to heuristic evaluation", exc)

        # 2. Heuristic fallback when SLM is unavailable or failed
        if read_count >= 8 and edit_count == 0:
            plan = ExecutionPlan(
                route="dynamic_dag",
                confidence=0.90,
                task_type="refactor",
                suggested_sla=CapabilitySLA(min_context=32000, requires_tools=True, min_capability_score=0.45),
                synthesizer_sla=CapabilitySLA(requires_reasoning=True, requires_tools=True, min_capability_score=0.45, min_output_tokens=8192),
                subtasks=[
                    SubTaskSpec(id="recon", goal=f"Synthesize context from {read_count} previous read calls", role="recon"),
                    SubTaskSpec(id="implement", goal="Apply code modifications", role="edit", depends_on=["recon"]),
                    SubTaskSpec(id="verify", goal="Run test suite to verify", role="verify", depends_on=["implement"]),
                ],
                rationale=f"Heuristic mid-execution replan: {replan_reason}",
                fallback_used=True,
            )
            return EscalationVerdict(
                should_escalate=True,
                reason=f"Heuristic mid-execution replan: {replan_reason}",
                suggested_plan=plan,
            )

        return EscalationVerdict(should_escalate=False, reason="Trajectory within normal parameters")

    async def evaluate_session_trajectory_async(
        self,
        messages: list[dict[str, Any]],
        current_plan: ExecutionPlan | None = None,
        session_stats: dict[str, Any] | None = None,
        config: Any = None,
    ) -> EscalationVerdict:
        """Asynchronously evaluate session trajectory with circuit breaker timeout."""
        timeout_ms = 2000.0
        if config is not None and hasattr(config, "selection"):
            timeout_ms = float(getattr(config.selection, "replan_slm_timeout_ms", 2000.0))
        timeout_sec = timeout_ms / 1000.0

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    self.evaluate_session_trajectory, messages, current_plan, session_stats, config
                ),
                timeout=timeout_sec,
            )
        except Exception as exc:
            logger.debug("Async trajectory evaluation timed out or failed: %s", exc)
            stats = session_stats or {}
            read_count = int(stats.get("read_count", 0))
            edit_count = int(stats.get("edit_count", 0))
            if read_count >= 8 and edit_count == 0:
                plan = self.create_escalation_plan(messages, reason="Mid-execution heuristic replan fallback")
                return EscalationVerdict(should_escalate=True, reason="Heuristic replan fallback", suggested_plan=plan)
            return EscalationVerdict(should_escalate=False, reason=f"Evaluation skipped: {exc}")

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

        # 3. Define schema
        class TaskClassification(BaseModel):
            complexity_score: int = Field(default=1, ge=1, le=10, description="1=trivial typo/chat, 10=massive architectural overhaul")
            requires_multi_agent_dag: bool = Field(default=False, description="True ONLY if the task requires multi-file parallel decomposition")
            task_type: Literal["chat", "explain", "recon", "single_edit", "multi_edit", "debug", "refactor", "full_workflow", "git_ops", "routine", "read_answer", "knowledge_query", "research"] = Field(default="chat", description="Task category")
            rationale: str = Field(default="SLM direct routing", description="Brief explanation of the routing decision")
            needs_rag: bool = Field(default=False, description="True if the task requires vector index or RAG lookup")
            confidence: Any = Field(default=0.5, description="Confidence in the route and task type, from 0 to 1")

        # 4. Generate structured output
        from autoconduck._compat.outlines_fallback import generate_structured_json
        prompt = (
            f"Classify the following software engineering instruction for automated routing:\n\n"
            f"Instruction: {text}\n\n"
            f"Rules:\n"
            f"- Set requires_multi_agent_dag=true for multi-file changes, architecture restructuring, or complex multi-step implementations.\n"
            f"- Set requires_multi_agent_dag=false for simple questions, repository checks, single-file edits, or conversational turns.\n"
             f"Output valid JSON with fields: complexity_score (1-10), requires_multi_agent_dag (bool), task_type, rationale, needs_rag (bool), confidence (float from 0 to 1 reflecting certainty in the route and task_type decision)."
        )
        
        result = generate_structured_json(self._llm, prompt, TaskClassification)
        if not isinstance(result, TaskClassification):
            logger.debug("SLM produced non-TaskClassification result; using fallback plan.")
            return self._create_fallback_plan(messages, reason="SLM structured output validation failed").model_dump()

        # 5. Map to ExecutionPlan
        if result.requires_multi_agent_dag:
            subtasks = [
                SubTaskSpec(id="recon", goal=f"Analyze relevant structure and files for: {text[:60]}", role="recon"),
                SubTaskSpec(id="read_targets", goal="Read target files and inspect relevant definitions", role="read", depends_on=["recon"]),
            ]
            if result.task_type in ("single_edit", "multi_edit", "refactor"):
                subtasks.append(SubTaskSpec(id="implement_changes", goal="Apply the requested modifications", role="edit", depends_on=["read_targets"]))
                subtasks.append(SubTaskSpec(id="verify_changes", goal="Run test suite", role="verify", depends_on=["implement_changes"]))
            else:
                subtasks.append(SubTaskSpec(id="synthesize_findings", goal="Reason over gathered context", role="reasoning", depends_on=["read_targets"]))

            return {
                "route": "dynamic_dag",
                "confidence": normalize_confidence(result.confidence),
                "task_type": result.task_type,
                "suggested_sla": CapabilitySLA(min_context=32000, requires_tools=True, min_capability_score=0.4),
                "needs_rag": result.needs_rag,
                "rag_queries": [f"Lookup definitions for: {text[:80]}"] if result.needs_rag else [],
                "subtasks": [t.model_dump() for t in subtasks],
                "synthesizer_sla": CapabilitySLA(requires_reasoning=True, requires_tools=True, min_capability_score=0.45, min_output_tokens=8192),
                "rationale": f"SLM (score {result.complexity_score}): {result.rationale} " + ("(harness noise stripped)" if noise_removed else ""),
                "fallback_used": False,
            }
        else:
            return {
                "route": "fast_direct",
                "confidence": normalize_confidence(result.confidence),
                "task_type": result.task_type,
                "suggested_sla": CapabilitySLA(min_context=16000, requires_tools=True, max_cost=1.5),
                "needs_rag": result.needs_rag,
                "rag_queries": [f"Lookup definitions for: {text[:80]}"] if result.needs_rag else [],
                "subtasks": [],
                "synthesizer_sla": CapabilitySLA(requires_reasoning=False, max_cost=1.0),
                "rationale": f"SLM (score {result.complexity_score}): {result.rationale} " + ("(harness noise stripped)" if noise_removed else ""),
                "fallback_used": False,
            }

    def plan_sync(self, messages: list[dict[str, Any]], config: Any = None) -> ExecutionPlan:
        """Generate an ExecutionPlan synchronously with circuit breaker / fallback protection."""
        try:
            res = self._raw_infer(messages, config)
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

            if not isinstance(data, dict) or "route" not in data:
                return self._create_fallback_plan(messages, reason="Missing plan route structure")

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

            if not isinstance(data, dict) or "route" not in data:
                return self._create_fallback_plan(messages, reason="Missing plan route structure")

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
