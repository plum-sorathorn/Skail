from __future__ import annotations

import itertools
from decimal import Decimal

from skail.domain.routing import RoutingMode
from skail.providers.models import CapabilityVector, ModelProfile
from skail.routing.requirements import RequirementBuilder, TaskRisk
from skail.routing.selector import (
    RouteCandidate,
    RouteFailure,
    RouteSelection,
    describe_route_failure,
    select_lead_model,
    select_model,
)


def _candidate(
    provider: str,
    model: str,
    *,
    cost: str = "0.10",
    coding: float = 0.7,
    reasoning: float = 0.7,
    reliability: float = 0.7,
    latency: float = 0.5,
    **profile_values: object,
) -> RouteCandidate:
    enabled = bool(profile_values.pop("enabled", True))
    healthy = bool(profile_values.pop("healthy", True))
    return RouteCandidate(
        profile=ModelProfile.model_validate(
            {
                "provider": provider,
                "model": model,
                "input_usd_per_million": Decimal("1"),
                "output_usd_per_million": Decimal("2"),
                "context_tokens": 32_000,
                "max_output_tokens": 4_000,
                "supports_tools": True,
                "supports_structured_output": True,
                "capability": CapabilityVector(
                    coding=coding,
                    reasoning=reasoning,
                    tool_reliability=reliability,
                    latency=latency,
                ),
                "auto_eligible": True,
                **profile_values,
            }
        ),
        estimated_cost_usd=Decimal(cost),
        enabled=enabled,
        healthy=healthy,
    )


def test_auto_and_economy_choose_lowest_cost_qualified_model() -> None:
    candidates = (
        _candidate("p", "quality", cost="0.20", coding=0.9, reasoning=0.9),
        _candidate("p", "cheap", cost="0.05", coding=0.6, reasoning=0.6),
    )
    for mode in (RoutingMode.AUTO, RoutingMode.ECONOMY):
        result = select_model(
            candidates,
            RequirementBuilder().build(role="implementer", risk=TaskRisk.ROUTINE, mode=mode),
        )
        assert isinstance(result, RouteSelection)
        assert result.candidate.profile.model == "cheap"


def test_quality_prefers_capability_then_reliability_before_cost() -> None:
    candidates = (
        _candidate("p", "cheap", cost="0.01", coding=0.7, reasoning=0.7),
        _candidate("p", "strong", cost="0.20", coding=0.9, reasoning=0.9),
    )
    result = select_model(
        candidates,
        RequirementBuilder().build(
            role="implementer", risk=TaskRisk.ROUTINE, mode=RoutingMode.QUALITY
        ),
    )
    assert isinstance(result, RouteSelection)
    assert result.candidate.profile.model == "strong"


def test_stable_provider_model_key_breaks_complete_ties_for_every_permutation() -> None:
    candidates = (_candidate("z", "m"), _candidate("a", "z"), _candidate("a", "a"))
    requirements = RequirementBuilder().build(role="explorer", risk=TaskRisk.TRIVIAL)
    selected = set()
    for ordering in itertools.permutations(candidates):
        result = select_model(ordering, requirements)
        assert isinstance(result, RouteSelection)
        selected.add((result.candidate.profile.provider, result.candidate.profile.model))
    assert selected == {("a", "a")}


def test_hard_filters_and_explanations_account_for_every_exclusion() -> None:
    requirements = RequirementBuilder().build(
        role="implementer",
        risk=TaskRisk.ROUTINE,
        required_tools=True,
        required_structured_output=True,
        required_context_tokens=20_000,
        required_output_tokens=2_000,
        required_modalities=frozenset({"text", "image"}),
        failed_model=("p", "failed"),
        excluded_models=frozenset({("p", "denied")}),
    )
    candidates = (
        _candidate("p", "failed"),
        _candidate("p", "denied"),
        _candidate("p", "disabled", enabled=False),
        _candidate("p", "unhealthy", healthy=False),
        _candidate("p", "manual-only", auto_eligible=False),
        _candidate("p", "no-tools", supports_tools=False),
        _candidate("p", "no-structured", supports_structured_output=False),
        _candidate("p", "small-context", context_tokens=1_000),
        _candidate("p", "small-output", max_output_tokens=10),
        _candidate("p", "text-only"),
        _candidate("p", "weak", coding=0.4, reasoning=0.4, input_modalities=("text", "image")),
        _candidate("p", "expensive", cost="0.50", input_modalities=("text", "image")),
    )
    result = select_model(candidates, requirements, available_budget_usd=Decimal("0.20"))
    assert isinstance(result, RouteFailure)
    assert result.code == "route.no_qualified_model"
    assert sum(result.excluded_counts.values()) == len(candidates)
    assert result.binding_constraint in result.excluded_counts


def test_manual_uses_exact_pin_but_still_validates_hard_compatibility() -> None:
    candidates = (_candidate("p", "manual", auto_eligible=False), _candidate("p", "other"))
    requirements = RequirementBuilder().build(
        role="lead", risk=TaskRisk.HIGH, mode=RoutingMode.MANUAL, required_tools=True
    )
    result = select_model(candidates, requirements, manual_model=("p", "manual"))
    assert isinstance(result, RouteSelection)
    assert result.candidate.profile.model == "manual"
    assert result.capability_fit is not None


def test_manual_keeps_unknown_price_distinct_when_no_hard_budget_applies() -> None:
    candidate = _candidate("p", "manual", auto_eligible=False).model_copy(
        update={"estimated_cost_usd": None}
    )
    requirements = RequirementBuilder().build(
        role="lead", risk=TaskRisk.HIGH, mode=RoutingMode.MANUAL
    )
    result = select_model((candidate,), requirements, manual_model=("p", "manual"))
    assert isinstance(result, RouteSelection)
    assert result.candidate.estimated_cost_usd is None


def test_selection_explanation_records_counts_binding_and_ranking() -> None:
    result = select_model(
        (_candidate("p", "weak", coding=0.1, reasoning=0.1), _candidate("p", "chosen")),
        RequirementBuilder().build(role="implementer", risk=TaskRisk.ROUTINE),
    )
    assert isinstance(result, RouteSelection)
    assert result.included_count == 1
    assert result.excluded_counts == {"capability_floor": 1}
    assert result.binding_constraint == "capability_floor"
    assert result.ranking_reasons


def test_lead_selection_ranks_strength_after_hard_compatibility_filtering() -> None:
    requirements = RequirementBuilder().build(
        role="lead",
        risk=TaskRisk.ROUTINE,
        required_tools=True,
        required_structured_output=True,
    )
    result = select_lead_model(
        (
            _candidate("p", "cheap", cost="0.01", coding=0.65, reasoning=0.65),
            _candidate("p", "strong", cost="0.20", coding=0.95, reasoning=0.95),
        ),
        requirements,
    )

    assert isinstance(result, RouteSelection)
    assert result.candidate.profile.model == "strong"


def test_lead_selection_reports_floor_and_remediation_without_weakening_it() -> None:
    requirements = RequirementBuilder().build(
        role="lead",
        risk=TaskRisk.ROUTINE,
        required_tools=True,
        required_structured_output=True,
    )
    result = select_lead_model(
        (_candidate("p", "weak", coding=0.4, reasoning=0.4),), requirements
    )

    assert isinstance(result, RouteFailure)
    assert result.required_capability_floor == requirements.capability_floor
    assert result.best_candidates == ("p:weak",)
    assert "Required capability floor" in describe_route_failure(result)
    assert "will not silently weaken" in describe_route_failure(result)


def test_explicit_underqualified_lead_pin_is_rejected_before_provider_use() -> None:
    requirements = RequirementBuilder().build(role="lead", risk=TaskRisk.HIGH)
    result = select_lead_model(
        (_candidate("p", "pinned", coding=0.6, reasoning=0.6),),
        requirements,
        manual_model=("p", "pinned"),
    )

    assert isinstance(result, RouteFailure)
    assert result.binding_constraint == "capability_floor"
