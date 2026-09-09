from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Strategy(StrEnum):
    DIRECT = "direct"
    ONE_WORKER = "one_worker"
    PARALLEL = "parallel"


class ObservationAuthority(StrEnum):
    LOCAL = "local"
    PAIRED_SYNTHETIC = "paired_synthetic"
    PAIRED_LIVE = "paired_live"


class StrategyObservationScope(BaseModel):
    """The evidence cell used for a route estimate; cells are never implicitly pooled."""

    model_config = ConfigDict(frozen=True)

    work_family: str = Field(min_length=1)
    provider_revision: str = Field(min_length=1)
    harness_revision: str = Field(min_length=1)
    authority: ObservationAuthority


class OutcomeObservation(StrategyObservationScope):
    """One immutable, independently verified execution outcome."""

    observation_id: str = Field(min_length=1)
    strategy: Strategy
    succeeded: bool
    observed_cost_usd: Decimal = Field(ge=0)
    latency_ms: int = Field(ge=0)
    recorded_at: datetime


class StrategyObservationSummary(BaseModel):
    """Deterministic descriptive summary for one strategy in one evidence cell."""

    model_config = ConfigDict(frozen=True)

    scope: StrategyObservationScope
    strategy: Strategy
    sample_count: int = Field(ge=0)
    success_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    observed_cost_usd: Decimal = Field(ge=0)
    success_rate: Decimal | None
    expected_cost_per_completed_usd: Decimal | None
    median_latency_ms: Decimal | None


class StrategyObservationSnapshot(BaseModel):
    """A bounded, deterministic view of one persisted observation cell."""

    model_config = ConfigDict(frozen=True)

    scope: StrategyObservationScope
    observations: tuple[OutcomeObservation, ...]
    evidence_revision: str = Field(min_length=1)


def observation_snapshot(
    scope: StrategyObservationScope,
    observations: tuple[OutcomeObservation, ...],
) -> StrategyObservationSnapshot:
    payload = [observation.model_dump(mode="json") for observation in observations]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return StrategyObservationSnapshot(
        scope=scope,
        observations=observations,
        evidence_revision=hashlib.sha256(encoded.encode()).hexdigest(),
    )


class RouteEstimate(BaseModel):
    """A deterministic route candidate explanation, independent of policy promotion."""

    model_config = ConfigDict(frozen=True)

    evidence_revision: str = Field(min_length=1)
    authority: ObservationAuthority
    compatible: bool
    expected_total_spend_usd: Decimal | None = Field(default=None, ge=0)
    cost_uncertainty_usd: Decimal | None = Field(default=None, ge=0)
    success_evidence: StrategyObservationSummary
    expected_latency_ms: Decimal | None = Field(default=None, ge=0)
    strategy: Strategy
    reasons: tuple[str, ...]


def summarize_observations(
    observations: tuple[OutcomeObservation, ...],
    scope: StrategyObservationScope,
    *,
    strategy: Strategy,
) -> StrategyObservationSummary:
    """Summarize exactly one versioned strategy cell without treating failures as free."""
    matching = tuple(
        observation
        for observation in observations
        if observation.strategy is strategy
        and observation.work_family == scope.work_family
        and observation.provider_revision == scope.provider_revision
        and observation.harness_revision == scope.harness_revision
        and observation.authority is scope.authority
    )
    sample_count = len(matching)
    success_count = sum(observation.succeeded for observation in matching)
    failure_count = sample_count - success_count
    observed_cost = sum((observation.observed_cost_usd for observation in matching), Decimal("0"))
    latencies = sorted(observation.latency_ms for observation in matching)
    median_latency: Decimal | None = None
    if latencies:
        middle = sample_count // 2
        median_latency = Decimal(latencies[middle])
        if sample_count % 2 == 0:
            median_latency = (Decimal(latencies[middle - 1]) + median_latency) / 2
    return StrategyObservationSummary(
        scope=scope,
        strategy=strategy,
        sample_count=sample_count,
        success_count=success_count,
        failure_count=failure_count,
        observed_cost_usd=observed_cost,
        success_rate=(None if sample_count == 0 else Decimal(success_count) / sample_count),
        expected_cost_per_completed_usd=(
            None if success_count == 0 else observed_cost / success_count
        ),
        median_latency_ms=median_latency,
    )
