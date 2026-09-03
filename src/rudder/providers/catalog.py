from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from rudder.providers.catalog_sources import CatalogEntry, CatalogSource
from rudder.providers.models import (
    CapabilityVector,
    EvidenceRecord,
    FieldEvidence,
    ModelProfile,
    ProviderSupportLevel,
)

_PRECEDENCE = {
    CatalogSource.DISCOVERED: 0,
    CatalogSource.MAINTAINED: 1,
    CatalogSource.EVALUATED: 2,
    CatalogSource.USER: 3,
}


class CatalogConflictError(ValueError):
    pass


class ModelCatalog:
    def __init__(
        self,
        profiles: dict[tuple[str, str], ModelProfile],
        *,
        revision: str,
        now: datetime,
        price_max_age: timedelta,
        capability_max_age: timedelta,
    ) -> None:
        self.profiles = dict(profiles)
        self.revision = revision
        self.now = now
        self.price_max_age = price_max_age
        self.capability_max_age = capability_max_age

    @classmethod
    def from_entries(
        cls,
        entries: tuple[CatalogEntry, ...],
        *,
        now: datetime,
        price_max_age: timedelta,
        capability_max_age: timedelta = timedelta(days=90),
    ) -> ModelCatalog:
        grouped: dict[tuple[str, str], list[CatalogEntry]] = {}
        for entry in entries:
            grouped.setdefault((entry.provider, entry.model), []).append(entry)
        profiles = {
            key: _merge_profile(key, values)
            for key, values in sorted(grouped.items())
        }
        canonical = [
            entry.model_dump(mode="json")
            for entry in sorted(
                entries,
                key=lambda item: json.dumps(
                    item.model_dump(mode="json"),
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ),
            )
        ]
        revision = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        return cls(
            profiles,
            revision=revision,
            now=now,
            price_max_age=price_max_age,
            capability_max_age=capability_max_age,
        )

    def profile(self, provider: str, model: str) -> ModelProfile:
        return self.profiles[(provider, model)]

    def is_auto_eligible(self, profile: ModelProfile, *, hard_budget: bool) -> bool:
        if not profile.auto_eligible:
            return False
        assert profile.evidence is not None
        capability_evidence = profile.evidence.fields.get("capability")
        if (
            capability_evidence is None
            or not capability_evidence.trusted
            or self.now - capability_evidence.as_of > self.capability_max_age
        ):
            return False
        if profile.input_usd_per_million is None or profile.output_usd_per_million is None:
            return False
        price_fields = ("input_usd_per_million", "output_usd_per_million")
        for field in price_fields:
            evidence = profile.evidence.fields.get(field)
            if evidence is None or not evidence.trusted:
                return False
            if hard_budget and self.now - evidence.as_of > self.price_max_age:
                return False
        return True


def _merge_profile(key: tuple[str, str], entries: list[CatalogEntry]) -> ModelProfile:
    fields: dict[str, Any] = {}
    evidence: dict[str, FieldEvidence] = {}
    seen: dict[tuple[CatalogSource, datetime, str], tuple[str, bool]] = {}
    for entry in entries:
        for name, value in entry.fields.items():
            evidence_key = (entry.source, entry.as_of, name)
            canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
            candidate = (canonical, entry.trusted)
            existing = seen.get(evidence_key)
            if existing is not None and existing != candidate:
                raise CatalogConflictError(
                    f"ambiguous {entry.source.value} evidence for {key[0]}:{key[1]} field {name}"
                )
            seen[evidence_key] = candidate
    for entry in sorted(
        entries,
        key=lambda item: (
            _PRECEDENCE[item.source],
            item.as_of,
            json.dumps(
                item.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ),
        ),
    ):
        for name, value in entry.fields.items():
            fields[name] = value
            evidence[name] = FieldEvidence(
                source=entry.source,
                as_of=entry.as_of,
                trusted=entry.trusted,
            )
    capability_value = fields.get("capability")
    capability = (
        CapabilityVector.model_validate(capability_value)
        if capability_value is not None
        else None
    )
    capability_evidence = evidence.get("capability")
    price_evidence = (
        evidence.get("input_usd_per_million"),
        evidence.get("output_usd_per_million"),
    )
    auto_eligible = (
        capability is not None
        and bool(capability_evidence and capability_evidence.trusted)
        and fields.get("input_usd_per_million") is not None
        and fields.get("output_usd_per_million") is not None
        and all(item is not None and item.trusted for item in price_evidence)
    )
    updated_at = max(entry.as_of for entry in entries)
    return ModelProfile(
        provider=key[0],
        model=key[1],
        support_level=ProviderSupportLevel.UNVERIFIED,
        input_usd_per_million=_decimal(fields.get("input_usd_per_million")),
        output_usd_per_million=_decimal(fields.get("output_usd_per_million")),
        cached_input_usd_per_million=_decimal(fields.get("cached_input_usd_per_million")),
        context_tokens=fields.get("context_tokens"),
        max_output_tokens=fields.get("max_output_tokens"),
        supports_tools=fields.get("supports_tools"),
        supports_structured_output=fields.get("supports_structured_output"),
        supports_reasoning=fields.get("supports_reasoning"),
        input_modalities=tuple(fields.get("input_modalities", ("text",))),
        aliases=tuple(fields.get("aliases", ())),
        capability=capability,
        evidence=EvidenceRecord(fields=evidence),
        catalog_updated_at=updated_at,
        auto_eligible=auto_eligible,
    )


def _decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))
