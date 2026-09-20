from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from skail.providers.catalog_sources import CatalogSource


class ProviderSupportLevel(StrEnum):
    NATIVE = "native"
    OPENAI_COMPATIBLE = "openai-compatible"
    MANUAL = "manual"
    UNVERIFIED = "unverified"


class CapabilityVector(BaseModel):
    model_config = ConfigDict(frozen=True)
    coding: float = Field(ge=0, le=1)
    reasoning: float = Field(ge=0, le=1)
    tool_reliability: float = Field(ge=0, le=1)
    latency: float = Field(ge=0, le=1)


class FieldEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)
    source: CatalogSource
    as_of: datetime
    trusted: bool
    provenance: str = ""


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    fields: dict[str, FieldEvidence]


class ModelProfile(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider: str
    model: str
    support_level: ProviderSupportLevel = ProviderSupportLevel.UNVERIFIED
    input_usd_per_million: Decimal | None = None
    output_usd_per_million: Decimal | None = None
    cached_input_usd_per_million: Decimal | None = None
    context_tokens: int | None = None
    max_output_tokens: int | None = None
    supports_tools: bool | None = None
    supports_structured_output: bool | None = None
    supports_reasoning: bool | None = None
    input_modalities: tuple[str, ...] = ("text",)
    aliases: tuple[str, ...] = ()
    capability: CapabilityVector | None = None
    evidence: EvidenceRecord | None = None
    catalog_updated_at: datetime | None = None
    manual_selectable: bool = True
    auto_eligible: bool = False
