from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from skail.domain.routing import RoutingMode
from skail.providers.models import ModelProfile
from skail.routing.requirements import RoutingRequirements


class RouteCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile: ModelProfile
    estimated_cost_usd: Decimal | None
    estimate_assumptions: tuple[str, ...] = ()
    configured: bool = True
    healthy: bool = True
    enabled: bool = True


class RouteSelection(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate: RouteCandidate
    capability_fit: float | None
    included_count: int = Field(ge=1)
    excluded_counts: dict[str, int]
    binding_constraint: str | None
    ranking_reasons: tuple[str, ...]


class RouteFailure(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: Literal["route.no_qualified_model"] = "route.no_qualified_model"
    excluded_counts: dict[str, int]
    binding_constraint: str | None


def _capability_fit(profile: ModelProfile) -> float | None:
    if profile.capability is None:
        return None
    return min(profile.capability.coding, profile.capability.reasoning)


def _exclusion_reason(
    candidate: RouteCandidate,
    requirements: RoutingRequirements,
    *,
    available_budget_usd: Decimal | None,
    manual_model: tuple[str, str] | None,
) -> str | None:
    profile = candidate.profile
    key = (profile.provider, profile.model)
    if requirements.mode is RoutingMode.MANUAL and key != manual_model:
        return "manual_model_mismatch"
    if key in requirements.excluded_models:
        return "model_excluded"
    if not candidate.configured:
        return "provider_unconfigured"
    if not candidate.healthy:
        return "provider_unhealthy"
    if not candidate.enabled:
        return "model_disabled"
    if requirements.mode is not RoutingMode.MANUAL and not profile.auto_eligible:
        return "auto_ineligible"
    if requirements.tools_required and profile.supports_tools is not True:
        return "tools_unsupported"
    if requirements.structured_output_required and profile.supports_structured_output is not True:
        return "structured_output_unsupported"
    if (
        profile.context_tokens is None
        or profile.context_tokens < requirements.minimum_context_tokens
    ):
        return "context_too_small"
    if (
        profile.max_output_tokens is None
        or profile.max_output_tokens < requirements.minimum_output_tokens
    ):
        return "output_too_small"
    if not frozenset(requirements.modalities).issubset(frozenset(profile.input_modalities)):
        return "modality_unsupported"
    fit = _capability_fit(profile)
    if requirements.capability_floor is not None and (
        fit is None or fit < requirements.capability_floor
    ):
        return "capability_floor"
    if candidate.estimated_cost_usd is None and (
        requirements.mode is not RoutingMode.MANUAL or available_budget_usd is not None
    ):
        return "price_unavailable"
    if (
        available_budget_usd is not None
        and candidate.estimated_cost_usd is not None
        and candidate.estimated_cost_usd > available_budget_usd
    ):
        return "budget_unaffordable"
    return None


def select_model(
    candidates: tuple[RouteCandidate, ...],
    requirements: RoutingRequirements,
    *,
    available_budget_usd: Decimal | None = None,
    manual_model: tuple[str, str] | None = None,
) -> RouteSelection | RouteFailure:
    if requirements.mode is RoutingMode.MANUAL and manual_model is None:
        raise ValueError("manual routing requires an exact provider/model pin")
    included: list[RouteCandidate] = []
    excluded: Counter[str] = Counter()
    for candidate in sorted(
        candidates, key=lambda item: (item.profile.provider, item.profile.model)
    ):
        reason = _exclusion_reason(
            candidate,
            requirements,
            available_budget_usd=available_budget_usd,
            manual_model=manual_model,
        )
        if reason is None:
            included.append(candidate)
        else:
            excluded[reason] += 1
    counts = dict(sorted(excluded.items()))
    binding = min(counts, key=lambda reason: (-counts[reason], reason)) if counts else None
    if not included:
        return RouteFailure(excluded_counts=counts, binding_constraint=binding)

    def rank(candidate: RouteCandidate) -> tuple[object, ...]:
        profile = candidate.profile
        stable = (profile.provider, profile.model)
        if requirements.mode is RoutingMode.MANUAL:
            return stable
        fit = _capability_fit(profile)
        assert fit is not None
        assert candidate.estimated_cost_usd is not None
        capability = profile.capability
        assert capability is not None
        if requirements.mode is RoutingMode.QUALITY:
            return (-fit, -capability.tool_reliability, candidate.estimated_cost_usd, *stable)
        return (
            candidate.estimated_cost_usd,
            -fit,
            -capability.tool_reliability,
            capability.latency,
            *stable,
        )

    chosen = min(included, key=rank)
    ranking = (
        "capability_fit,tool_reliability,cost,stable_key"
        if requirements.mode is RoutingMode.QUALITY
        else "cost,capability_fit,tool_reliability,latency,stable_key"
    )
    return RouteSelection(
        candidate=chosen,
        capability_fit=_capability_fit(chosen.profile),
        included_count=len(included),
        excluded_counts=counts,
        binding_constraint=binding,
        ranking_reasons=(ranking,),
    )
