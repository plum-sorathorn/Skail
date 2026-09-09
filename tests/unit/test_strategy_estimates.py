from datetime import UTC, datetime
from decimal import Decimal

from rudder.domain.strategy_estimates import (
    ObservationAuthority,
    OutcomeObservation,
    RouteEstimate,
    ShadowStrategyDecision,
    Strategy,
    StrategyObservationScope,
    observation_snapshot,
    shadow_strategy_decision,
    strategy_route_estimates,
    summarize_observations,
)


def _observation(
    observation_id: str,
    *,
    strategy: Strategy = Strategy.ONE_WORKER,
    succeeded: bool,
    cost: str,
    provider_revision: str = "provider-v1",
    harness_revision: str = "harness-v1",
    authority: ObservationAuthority = ObservationAuthority.LOCAL,
) -> OutcomeObservation:
    return OutcomeObservation(
        observation_id=observation_id,
        work_family="python-edit",
        strategy=strategy,
        provider_revision=provider_revision,
        harness_revision=harness_revision,
        authority=authority,
        succeeded=succeeded,
        observed_cost_usd=Decimal(cost),
        latency_ms=100,
        recorded_at=datetime(2026, 9, 9, tzinfo=UTC),
    )


def test_summary_retains_failed_work_cost_for_matching_evidence_cell() -> None:
    scope = StrategyObservationScope(
        work_family="python-edit",
        provider_revision="provider-v1",
        harness_revision="harness-v1",
        authority=ObservationAuthority.LOCAL,
    )

    summary = summarize_observations(
        (
            _observation("success", succeeded=True, cost="0.10"),
            _observation("failure", succeeded=False, cost="0.20"),
        ),
        scope,
        strategy=Strategy.ONE_WORKER,
    )

    assert summary.sample_count == 2
    assert summary.success_count == 1
    assert summary.failure_count == 1
    assert summary.observed_cost_usd == Decimal("0.30")
    assert summary.expected_cost_per_completed_usd == Decimal("0.30")


def test_summary_does_not_pool_different_evidence_revisions_or_authority() -> None:
    scope = StrategyObservationScope(
        work_family="python-edit",
        provider_revision="provider-v1",
        harness_revision="harness-v1",
        authority=ObservationAuthority.LOCAL,
    )

    summary = summarize_observations(
        (
            _observation("matching", succeeded=True, cost="0.10"),
            _observation("provider", succeeded=True, cost="9.00", provider_revision="provider-v2"),
            _observation("harness", succeeded=True, cost="9.00", harness_revision="harness-v2"),
            _observation(
                "authority",
                succeeded=True,
                cost="9.00",
                authority=ObservationAuthority.PAIRED_SYNTHETIC,
            ),
        ),
        scope,
        strategy=Strategy.ONE_WORKER,
    )

    assert summary.sample_count == 1
    assert summary.observed_cost_usd == Decimal("0.10")


def test_empty_evidence_cell_is_explicitly_unknown() -> None:
    summary = summarize_observations(
        (),
        StrategyObservationScope(
            work_family="python-edit",
            provider_revision="provider-v1",
            harness_revision="harness-v1",
            authority=ObservationAuthority.LOCAL,
        ),
        strategy=Strategy.ONE_WORKER,
    )

    assert summary.sample_count == 0
    assert summary.success_rate is None
    assert summary.expected_cost_per_completed_usd is None


def test_route_estimate_carries_evidence_authority_uncertainty_and_reasons() -> None:
    scope = StrategyObservationScope(
        work_family="python-edit",
        provider_revision="provider-v1",
        harness_revision="harness-v1",
        authority=ObservationAuthority.LOCAL,
    )
    summary = summarize_observations((), scope, strategy=Strategy.ONE_WORKER)

    estimate = RouteEstimate(
        evidence_revision="observations-v1",
        authority=ObservationAuthority.LOCAL,
        compatible=True,
        expected_total_spend_usd=None,
        cost_uncertainty_usd=None,
        success_evidence=summary,
        expected_latency_ms=None,
        strategy=Strategy.ONE_WORKER,
        reasons=("cold_start",),
    )

    assert estimate.reasons == ("cold_start",)
    assert estimate.success_evidence.sample_count == 0


def test_shadow_strategy_prefers_reliable_completed_work_cost_over_cheap_failures() -> None:
    scope = StrategyObservationScope(
        work_family="python-edit",
        provider_revision="provider-v1",
        harness_revision="harness-v1",
        authority=ObservationAuthority.LOCAL,
    )
    snapshot = observation_snapshot(
        scope,
        (
            _observation("direct-success", strategy=Strategy.DIRECT, succeeded=True, cost="0.10"),
            _observation(
                "direct-failure-1", strategy=Strategy.DIRECT, succeeded=False, cost="0.50"
            ),
            _observation(
                "direct-failure-2", strategy=Strategy.DIRECT, succeeded=False, cost="0.50"
            ),
            _observation("worker-success-1", succeeded=True, cost="0.40"),
            _observation("worker-success-2", succeeded=True, cost="0.40"),
        ),
    )

    decision = shadow_strategy_decision(snapshot, active_strategy=Strategy.DIRECT)

    assert isinstance(decision, ShadowStrategyDecision)
    assert decision.recommended_strategy is Strategy.ONE_WORKER
    assert decision.reasons == ("shadow_candidate_has_lower_reliable_completed_work_cost",)


def test_shadow_strategy_keeps_active_strategy_when_evidence_is_insufficient() -> None:
    scope = StrategyObservationScope(
        work_family="python-edit",
        provider_revision="provider-v1",
        harness_revision="harness-v1",
        authority=ObservationAuthority.LOCAL,
    )
    snapshot = observation_snapshot(
        scope,
        (
            _observation("direct", strategy=Strategy.DIRECT, succeeded=True, cost="0.10"),
            _observation("worker", succeeded=True, cost="0.01"),
        ),
    )

    decision = shadow_strategy_decision(snapshot, active_strategy=Strategy.DIRECT)

    assert decision.recommended_strategy is Strategy.DIRECT
    assert decision.reasons == ("active_strategy_retained_due_to_insufficient_evidence",)


def test_strategy_estimate_does_not_mix_uncertainty_from_another_evidence_cell() -> None:
    scope = StrategyObservationScope(
        work_family="python-edit",
        provider_revision="provider-v1",
        harness_revision="harness-v1",
        authority=ObservationAuthority.LOCAL,
    )
    snapshot = observation_snapshot(
        scope,
        (
            _observation("direct-1", strategy=Strategy.DIRECT, succeeded=True, cost="0.10"),
            _observation("direct-2", strategy=Strategy.DIRECT, succeeded=True, cost="0.10"),
            _observation(
                "other-cell",
                strategy=Strategy.DIRECT,
                succeeded=True,
                cost="9.00",
                provider_revision="provider-v2",
            ),
        ),
    )

    direct = strategy_route_estimates(snapshot)[0]

    assert direct.cost_uncertainty_usd == Decimal("0.00")
