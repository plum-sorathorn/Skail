from __future__ import annotations

import itertools

import pytest

from rudder.domain.routing import RoutingMode
from rudder.routing.requirements import (
    RISK_FLOORS,
    ROLE_FLOORS,
    RequirementBuilder,
    TaskRisk,
)


@pytest.mark.parametrize(
    ("role", "expected"),
    tuple(ROLE_FLOORS.items()),
)
def test_auto_uses_each_approved_role_floor(role: str, expected: float) -> None:
    requirements = RequirementBuilder().build(role=role, risk=TaskRisk.TRIVIAL)
    assert requirements.capability_floor == expected


@pytest.mark.parametrize(
    ("risk", "expected"),
    tuple(RISK_FLOORS.items()),
)
def test_auto_uses_each_approved_risk_floor(risk: TaskRisk, expected: float) -> None:
    requirements = RequirementBuilder().build(role="explorer", risk=risk)
    assert requirements.capability_floor == max(ROLE_FLOORS["explorer"], expected)


def test_mode_escalation_and_caps_match_the_approved_formula() -> None:
    builder = RequirementBuilder()
    assert (
        builder.build(
            role="implementer",
            risk=TaskRisk.BOUNDED,
            mode=RoutingMode.ECONOMY,
            role_hard_min=0.45,
        ).capability_floor
        == 0.45
    )
    assert (
        builder.build(
            role="reviewer",
            risk=TaskRisk.COMPLEX,
            mode=RoutingMode.QUALITY,
        ).capability_floor
        == 0.75
    )
    assert (
        builder.build(
            role="lead",
            risk=TaskRisk.HIGH,
            mode=RoutingMode.QUALITY,
        ).capability_floor
        == 0.85
    )
    assert (
        builder.build(
            role="lead",
            risk=TaskRisk.HIGH,
            escalated=True,
        ).capability_floor
        == 0.85
    )
    assert (
        builder.build(
            role="lead",
            risk=TaskRisk.HIGH,
            mode=RoutingMode.QUALITY,
            escalated=True,
        ).capability_floor
        == 0.90
    )
    assert (
        builder.build(
            role="lead",
            risk=TaskRisk.HIGH,
            mode=RoutingMode.MANUAL,
        ).capability_floor
        is None
    )


def test_hints_can_only_strengthen_enforced_requirements() -> None:
    requirements = RequirementBuilder().build(
        role="implementer",
        risk=TaskRisk.ROUTINE,
        role_hard_min=0.48,
        required_tools=True,
        required_structured_output=True,
        required_context_tokens=20_000,
        required_output_tokens=2_000,
        required_modalities=frozenset({"text", "image"}),
        hinted_floor=0.10,
        hinted_context_tokens=10,
        hinted_output_tokens=20,
        hinted_modalities=frozenset({"text"}),
    )
    assert requirements.capability_floor == 0.50
    assert requirements.tools_required is True
    assert requirements.structured_output_required is True
    assert requirements.minimum_context_tokens == 20_000
    assert requirements.minimum_output_tokens == 2_000
    assert requirements.modalities == ("image", "text")


def test_assignment_derivation_preserves_validated_hard_requirements_on_retry() -> None:
    builder = RequirementBuilder()
    initial = builder.build(
        role="implementer",
        risk=TaskRisk.ROUTINE,
        role_hard_min=0.50,
        required_tools=True,
        required_structured_output=True,
        required_context_tokens=32_000,
        required_output_tokens=4_000,
        required_modalities=frozenset({"text", "image"}),
    )

    retry = builder.for_assignment(
        initial,
        role="implementer",
        risk=TaskRisk.ROUTINE,
        mode=RoutingMode.AUTO,
        role_hard_min=0.50,
        escalated=True,
        excluded_models=frozenset({("provider", "failed")}),
    )

    assert retry.tools_required is True
    assert retry.structured_output_required is True
    assert retry.minimum_context_tokens == 32_000
    assert retry.minimum_output_tokens == 4_000
    assert retry.modalities == ("image", "text")
    assert retry.excluded_models == frozenset({("provider", "failed")})


def test_all_floor_combinations_are_bounded_and_deterministic() -> None:
    builder = RequirementBuilder()
    for role, risk, mode, escalated in itertools.product(
        ROLE_FLOORS, TaskRisk, tuple(RoutingMode), (False, True)
    ):
        first = builder.build(role=role, risk=risk, mode=mode, escalated=escalated)
        second = builder.build(role=role, risk=risk, mode=mode, escalated=escalated)
        assert first == second
        if first.capability_floor is not None:
            assert 0 <= first.capability_floor <= (0.90 if escalated else 0.85)
