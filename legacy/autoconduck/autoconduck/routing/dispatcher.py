from dataclasses import dataclass, replace
from typing import Literal, Any
import re
from . import pricing
from autoconduck.routing.model_pool import CapabilitySLA
from autoconduck.routing.slm_planner import SLMPlanner
from autoconduck.server.turn_guard import TurnGuard, TurnAction


def _user_messages(messages: list) -> list:
    return [
        message
        for message in messages
        if not isinstance(message, dict) or message.get("role", "user") == "user"
    ]


@dataclass(frozen=True)
class RoutingDecision:
    path: Literal["fast"]
    confidence_band: Literal["fast"]
    confidence: float
    complexity: float
    reason: str
    model: str | None = None
    route: str = "fast_direct"
    plan: Any = None
    tier: str | None = None
    candidates_considered: int = 0
    candidates_excluded_by: dict[str, int] | None = None
    binding_constraint: str | None = None
    min_capability_score_applied: float = 0.0
    spend_cap_engaged: bool = False
    fallback_reason: str | None = None
    capability_fit_applied: float | None = None
    binding_capability_dim: str | None = None
    benchmark_profile: str | None = None
    benchmark_score: float | None = None
    benchmark_coverage_state: str = "not_requested"
    benchmark_snapshot_age_hours: float | None = None


TASK_BASE_FLOORS: dict[str, float] = {
    "chat": 0.0,
    "routine": 0.0,
    "git_ops": 0.0,
    "explain": 0.15,
    "recon": 0.15,
    "read_answer": 0.15,
    "single_edit": 0.20,
    "knowledge_query": 0.20,
    "multi_edit": 0.30,
    "debug": 0.35,
    "refactor": 0.40,
    "research": 0.40,
    "full_workflow": 0.45,
}


def route(
    messages: list,
    history: Any = None,
    pseudo_model: str = "autoconduck",
    tiebreaker: Any = None,
    config: Any = None,
    session_id: str | None = None,
) -> RoutingDecision:
    if config is None:
        from ..config import get_config
        config = get_config()

    from ..config import resolve_orchestrator_model

    # Step 1: Turn Guard 0ms Classification (<2ms overhead)
    guard = TurnGuard()
    guard_res = guard.classify_turn(messages)

    plan = None
    selection_info = None
    if guard_res.target_action == TurnAction.ESCALATE_SLM:
        # Deterministic trigger: apply immediate escalation bias in SessionBiasStore
        if session_id:
            try:
                from autoconduck.plugin.bias import get_bias_store
                plugins_cfg = getattr(config, "plugins", None)
                bump = float(getattr(plugins_cfg, "escalation_floor_bump", 0.15)) if plugins_cfg else 0.15
                ttl = int(getattr(plugins_cfg, "escalation_ttl_turns", 10)) if plugins_cfg else 10
                get_bias_store().apply_escalation(session_id, bump, ttl)
            except Exception:
                pass

        # escalation = fresh classification + floor-tightened selection (no slow path)
        planner = SLMPlanner()
        plan = planner.plan_sync(messages, config)
        path = "fast"
        route_name = "fast_direct"
        confidence_band = "fast"
        confidence = plan.confidence
        complexity = 0.2
        tier = "capability_sla"
        reason = plan.rationale or f"escalation_reclassified_{plan.task_type}"
        selection_info = _select_planned(plan.suggested_sla, plan, config, pseudo_model, _tier_from_pseudo(pseudo_model), session_id, messages)
        model = selection_info.model or resolve_orchestrator_model(config)

    elif guard_res.target_action in (TurnAction.DIRECT_ACTIVE_TIER, TurnAction.SUGGEST_REPLAN):
        path = "fast"
        route_name = "fast_direct"
        confidence_band = "fast"
        confidence = 1.0
        complexity = 0.2
        last_tool = (guard_res.last_tool_name or "").lower()
        is_routine_tool = any(
            t in last_tool
            for t in ["read", "glob", "list", "grep", "bash", "status", "diff", "command", "file", "view", "tool"]
        )
        reason = f"tool_loop_bypass: {guard_res.last_tool_name or 'tool'}"

        # Inherit session capability floor if available
        inherited_floor = 0.0
        inherited_task_type = None
        if session_id:
            try:
                from autoconduck.plugin.bias import get_bias_store
                inherited_floor, inherited_task_type = get_bias_store().get_session_floor(session_id)
            except Exception:
                pass

        sla = CapabilitySLA(
            min_context=16000,
            requires_tools=True,
            max_cost=1.0 if is_routine_tool else 1.5,
            min_capability_score=inherited_floor,
            task_type=inherited_task_type,
        )
        selection_info = pricing.select_for_sla_detailed(sla, config=config, pseudo_model=pseudo_model)
        model = selection_info.model or resolve_orchestrator_model(config)
        tier = "capability_sla"

    else:
        # Step 2: Embedded SLM Task Architect (<100ms circuit breaker)
        planner = SLMPlanner()
        plan = planner.plan_sync(messages, config)
        path = "fast"
        route_name = "fast_direct"
        confidence_band = "fast"
        confidence = plan.confidence
        complexity = 0.2
        tier = "capability_sla"
        reason = plan.rationale or f"fast_direct_{plan.task_type}"
        selection_info = _select_planned(plan.suggested_sla, plan, config, pseudo_model, _tier_from_pseudo(pseudo_model), session_id, messages)
        model = selection_info.model or resolve_orchestrator_model(config)

    if model:
        try:
            from ..stats import record_selection
            record_selection(
                complexity,
                0.5,
                model,
                config,
            )
        except Exception:
            pass

    return RoutingDecision(
        path=path,
        confidence_band=confidence_band,
        confidence=confidence,
        complexity=complexity,
        reason=reason,
        model=model,
        route=route_name,
        plan=plan,
        tier=tier,
        candidates_considered=selection_info.candidates_considered if selection_info else 0,
        candidates_excluded_by=selection_info.candidates_excluded_by if selection_info else None,
        binding_constraint=selection_info.binding_constraint if selection_info else None,
        min_capability_score_applied=selection_info.min_capability_score_applied if selection_info else 0.0,
        spend_cap_engaged=selection_info.spend_cap_engaged if selection_info else False,
        fallback_reason=selection_info.fallback_reason if selection_info else None,
        capability_fit_applied=selection_info.capability_fit_applied if selection_info else None,
        binding_capability_dim=selection_info.binding_capability_dim if selection_info else None,
        benchmark_profile=selection_info.benchmark_profile if selection_info else None,
        benchmark_score=selection_info.benchmark_score if selection_info else None,
        benchmark_coverage_state=selection_info.benchmark_coverage_state if selection_info else "not_requested",
        benchmark_snapshot_age_hours=selection_info.benchmark_snapshot_age_hours if selection_info else None,
    )


def _tier_from_pseudo(pseudo_model: str) -> str | None:
    pm = str(pseudo_model or "")
    if pm.endswith("-budget") or pm.endswith(":budget") or pm == "budget":
        return "budget"
    if pm.endswith("-expensive") or pm.endswith(":expensive") or pm == "expensive":
        return "expensive"
    return "default"


def _select_planned(sla: CapabilitySLA, plan: Any, config: Any, pseudo_model: str, tier: str | None, session_id: str | None = None, messages: list | None = None):
    effective_pseudo = pseudo_model
    if session_id:
        try:
            from autoconduck.plugin.bias import get_bias_store
            if get_bias_store().is_child_session(session_id):
                effective_pseudo = "autoconduck-budget"
        except Exception:
            pass
    try:
        confidence = max(0.0, min(1.0, float(getattr(plan, "confidence", 1.0))))
        selection = getattr(config, "selection", None)
        base = float(getattr(sla, "min_capability_score", 0.0) or 0.0)
        task_type = getattr(plan, "task_type", None) or "chat"
        complexity_score = int(getattr(plan, "complexity_score", 1) or 1)

        # Derive base capability floor from task_type and complexity if not explicitly provided
        if base <= 0.0:
            base = TASK_BASE_FLOORS.get(task_type, 0.15)
            if complexity_score >= 7:
                base += 0.10
            elif complexity_score >= 4:
                base += 0.05

        floor = min(
            base + float(getattr(selection, "confidence_floor_k", 0.15)) * (1 - confidence),
            float(getattr(selection, "confidence_floor_max", 0.6)),
        )
        # Apply session bias (ESCALATE-driven) — may raise above confidence cap up to 0.75
        try:
            if session_id:
                from autoconduck.plugin.bias import get_bias_store

                bump = float(get_bias_store().get_bump(session_id) or 0.0)
                if bump:
                    floor = min(floor + bump, 0.75)
        except Exception:
            pass

        # Cache session floor for tool loop inheritance
        try:
            if session_id:
                from autoconduck.plugin.bias import get_bias_store

                get_bias_store().set_session_floor(session_id, floor, task_type)
        except Exception:
            pass

        ceiling = None
        if tier:
            ceilings = getattr(selection, "path_price_cap_usd_per_mtok", {})
            ceiling = ceilings.get(tier)
        domain = _domain_from_messages(messages or [], task_type)
        modified = replace(
            sla,
            min_capability_score=floor,
            max_price_usd_per_mtok=ceiling,
            task_type=task_type,
            domain=domain,
            role="implementer" if domain else None,
        )
        return pricing.select_for_sla_detailed(modified, config=config, pseudo_model=effective_pseudo)
    except Exception:
        return pricing.select_for_sla_detailed(sla, config=config, pseudo_model=effective_pseudo)


def _domain_from_messages(messages: list, task_type: str) -> str | None:
    """Deterministic domain labels; the SLM remains only a task-type signal."""
    text = " ".join(str(message.get("content", "")) for message in _user_messages(messages) if isinstance(message, dict)).lower()
    if re.search(r"\b(frontend|ui|ux|css|website)\b|react\s+component", text):
        return "frontend"
    if any(term in text for term in ("research", "web search", "browse the web")):
        return "research"
    if task_type in {"debug", "refactor", "single_edit", "multi_edit", "full_workflow"}:
        return "general_software_engineering"
    return None


def pick_fast_model(body_model: str = "autoconduck", cfg: Any = None) -> str:
    """Pick an economical fast model within the capability SLA."""
    if cfg is None:
        from ..config import get_config
        cfg = get_config()
    try:
        from ..config import resolve_orchestrator_model
        return (
            pricing.select_for_sla(
                CapabilitySLA(min_context=16000, requires_tools=True, max_cost=1.0),
                config=cfg,
                pseudo_model=body_model,
            )
            or resolve_orchestrator_model(cfg)
        )
    except Exception:
        from ..config import resolve_orchestrator_model
        return resolve_orchestrator_model(cfg)
