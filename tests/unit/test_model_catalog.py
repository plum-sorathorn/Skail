from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from rudder.providers.catalog import CatalogConflictError, ModelCatalog
from rudder.providers.catalog_sources import CatalogEntry, CatalogSource
from rudder.providers.models import CapabilityVector, EvidenceRecord, ModelProfile

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "catalog"
NOW = datetime(2026, 9, 2, tzinfo=UTC)
PRICE_MAX_AGE = timedelta(days=30)


def _entries(name: str) -> tuple[CatalogEntry, ...]:
    raw = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(raw, list)
    return tuple(CatalogEntry.model_validate(item) for item in raw)


def _catalog(entries: tuple[CatalogEntry, ...]) -> ModelCatalog:
    return ModelCatalog.from_entries(
        entries,
        now=NOW,
        price_max_age=PRICE_MAX_AGE,
    )


def test_model_profile_preserves_exact_prices_capability_and_field_evidence() -> None:
    profile = _catalog(_entries("merge_sources.json")).profile("fixture", "code-pro")

    assert isinstance(profile, ModelProfile)
    assert profile.input_usd_per_million == Decimal("0.90")
    assert profile.output_usd_per_million == Decimal("4.75")
    assert profile.capability == CapabilityVector(
        coding=0.81,
        reasoning=0.76,
        tool_reliability=0.84,
        latency=0.69,
    )
    assert isinstance(profile.evidence, EvidenceRecord)
    assert profile.catalog_updated_at == datetime(2026, 8, 25, tzinfo=UTC)


def test_catalog_merge_uses_field_precedence_and_retains_winning_provenance() -> None:
    profile = _catalog(_entries("merge_sources.json")).profile("fixture", "code-pro")

    assert profile.context_tokens == 32768
    assert profile.supports_tools is True
    assert profile.supports_structured_output is True
    assert profile.supports_reasoning is True

    assert profile.evidence is not None
    context = profile.evidence.fields["context_tokens"]
    tools = profile.evidence.fields["supports_tools"]
    structured = profile.evidence.fields["supports_structured_output"]
    reasoning = profile.evidence.fields["supports_reasoning"]

    assert (context.source, context.as_of) == (
        CatalogSource.DISCOVERED,
        datetime(2026, 8, 1, tzinfo=UTC),
    )
    assert (tools.source, tools.as_of) == (
        CatalogSource.MAINTAINED,
        datetime(2026, 8, 10, tzinfo=UTC),
    )
    assert (structured.source, structured.as_of) == (
        CatalogSource.EVALUATED,
        datetime(2026, 8, 20, tzinfo=UTC),
    )
    assert (reasoning.source, reasoning.as_of) == (
        CatalogSource.USER,
        datetime(2026, 8, 25, tzinfo=UTC),
    )
    assert context.trusted is False
    assert tools.trusted is True
    assert structured.trusted is True
    assert reasoning.trusted is True


def test_unknown_capability_is_not_inferred_from_model_name_price_or_context() -> None:
    profile = _catalog(_entries("eligibility.json")).profile(
        "fixture", "expensive-ultra-code-9000"
    )

    assert profile.capability is None
    assert profile.manual_selectable is True
    assert profile.auto_eligible is False


def test_stale_price_disqualifies_only_hard_budget_auto_routes() -> None:
    catalog = _catalog(_entries("eligibility.json"))
    profile = catalog.profile("fixture", "stale-price")

    assert profile.auto_eligible is True
    assert catalog.is_auto_eligible(profile, hard_budget=False) is True
    assert catalog.is_auto_eligible(profile, hard_budget=True) is False
    assert profile.manual_selectable is True


def test_missing_price_is_never_automatically_routable() -> None:
    catalog = _catalog(_entries("eligibility.json"))
    profile = catalog.profile("fixture", "missing-price")

    assert profile.auto_eligible is False
    assert catalog.is_auto_eligible(profile, hard_budget=False) is False
    assert catalog.is_auto_eligible(profile, hard_budget=True) is False
    assert profile.manual_selectable is True


def test_fresh_measured_model_is_eligible_for_hard_budget_auto_route() -> None:
    catalog = _catalog(_entries("eligibility.json"))
    profile = catalog.profile("fixture", "fresh-measured")

    assert catalog.is_auto_eligible(profile, hard_budget=True) is True


def test_user_capability_override_requires_explicit_trust_for_auto_routing() -> None:
    discovered = CatalogEntry(
        provider="fixture",
        model="override-target",
        source=CatalogSource.DISCOVERED,
        as_of=NOW,
        trusted=False,
        fields={
            "input_usd_per_million": "0.20",
            "output_usd_per_million": "0.60",
            "supports_tools": True,
            "input_modalities": ["text"],
        },
    )
    override_data: dict[str, Any] = {
        "provider": "fixture",
        "model": "override-target",
        "source": CatalogSource.USER,
        "as_of": NOW,
        "fields": {
            "input_usd_per_million": "0.20",
            "output_usd_per_million": "0.60",
            "supports_tools": True,
            "input_modalities": ["text"],
            "capability": {
                "coding": 0.80,
                "reasoning": 0.78,
                "tool_reliability": 0.82,
                "latency": 0.70,
            }
        },
    }

    untrusted = CatalogEntry.model_validate({**override_data, "trusted": False})
    trusted = CatalogEntry.model_validate({**override_data, "trusted": True})

    untrusted_profile = _catalog((discovered, untrusted)).profile(
        "fixture", "override-target"
    )
    trusted_profile = _catalog((discovered, trusted)).profile(
        "fixture", "override-target"
    )

    assert untrusted_profile.auto_eligible is False
    assert untrusted_profile.evidence is not None
    assert untrusted_profile.evidence.fields["capability"].trusted is False
    assert trusted_profile.auto_eligible is True
    assert trusted_profile.evidence is not None
    assert trusted_profile.evidence.fields["capability"].trusted is True


def test_catalog_revision_is_stable_across_input_order_and_changes_with_content() -> None:
    entries = _entries("merge_sources.json")
    forward = _catalog(entries)
    reversed_input = _catalog(tuple(reversed(entries)))
    changed = _catalog(
        entries
        + (
            CatalogEntry(
                provider="fixture",
                model="new-model",
                source=CatalogSource.DISCOVERED,
                as_of=NOW,
                trusted=False,
                fields={"context_tokens": 8192},
            ),
        )
    )

    assert forward.revision
    assert forward.revision == reversed_input.revision
    assert forward.revision != changed.revision


def test_stale_capability_is_not_automatically_routable() -> None:
    stale = CatalogEntry(
        provider="fixture",
        model="stale-capability",
        source=CatalogSource.EVALUATED,
        as_of=NOW - timedelta(days=120),
        trusted=True,
        fields={
            "input_usd_per_million": "0.10",
            "output_usd_per_million": "0.20",
            "capability": {
                "coding": 0.8,
                "reasoning": 0.8,
                "tool_reliability": 0.8,
                "latency": 0.8,
            },
        },
    )
    catalog = _catalog((stale,))

    profile = catalog.profile("fixture", "stale-capability")
    assert catalog.is_auto_eligible(profile, hard_budget=False) is False


def test_untrusted_discovered_prices_cannot_authorize_a_hard_budget_route() -> None:
    capability = CatalogEntry(
        provider="fixture",
        model="mixed-trust",
        source=CatalogSource.EVALUATED,
        as_of=NOW,
        trusted=True,
        fields={
            "capability": {
                "coding": 0.8,
                "reasoning": 0.8,
                "tool_reliability": 0.8,
                "latency": 0.8,
            }
        },
    )
    price = CatalogEntry(
        provider="fixture",
        model="mixed-trust",
        source=CatalogSource.DISCOVERED,
        as_of=NOW,
        trusted=False,
        fields={"input_usd_per_million": "0.10", "output_usd_per_million": "0.20"},
    )
    catalog = _catalog((capability, price))
    profile = catalog.profile("fixture", "mixed-trust")

    assert profile.auto_eligible is False
    assert catalog.is_auto_eligible(profile, hard_budget=False) is False
    assert catalog.is_auto_eligible(profile, hard_budget=True) is False


def test_equal_rank_conflicting_evidence_is_rejected_instead_of_order_dependent() -> None:
    common = {
        "provider": "fixture",
        "model": "ambiguous",
        "source": CatalogSource.MAINTAINED,
        "as_of": NOW,
        "trusted": True,
    }
    first = CatalogEntry(**common, fields={"supports_tools": True})
    second = CatalogEntry(**common, fields={"supports_tools": False})

    with pytest.raises(CatalogConflictError, match="ambiguous"):
        _catalog((first, second))


def test_catalog_revision_changes_when_only_trust_changes() -> None:
    common = {
        "provider": "fixture",
        "model": "trust-sensitive",
        "source": CatalogSource.USER,
        "as_of": NOW,
        "fields": {"supports_tools": True},
    }
    trusted = _catalog((CatalogEntry(**common, trusted=True),))
    untrusted = _catalog((CatalogEntry(**common, trusted=False),))

    assert trusted.revision != untrusted.revision
