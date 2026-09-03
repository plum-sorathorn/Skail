from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, ConfigDict, Field

from rudder.config.models import ProviderConfig
from rudder.domain.usage import NormalizedUsage
from rudder.providers.catalog_sources import CatalogEntry
from rudder.providers.errors import ProviderError
from rudder.providers.models import ModelProfile, ProviderSupportLevel


class ProviderCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True)
    streaming: bool = True
    tools: bool = False
    structured_output: bool = False


class ProviderModelSpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider: str
    model: str


class ModelOptions(BaseModel):
    model_config = ConfigDict(frozen=True)
    temperature: float | None = None
    max_tokens: int | None = Field(default=None, ge=1)
    timeout: float | None = Field(default=None, gt=0)
    extra: tuple[tuple[str, str], ...] = ()


class ModelResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    text: str
    usage: NormalizedUsage | None = None


class StreamChunk(BaseModel):
    model_config = ConfigDict(frozen=True)
    text: str = ""
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_arguments: str = ""
    usage_cost_usd: Decimal | None = None


class DiscoveredModel(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider: str
    model: str
    fields: dict[str, Any] = Field(default_factory=dict)


class ProviderAdapter(Protocol):
    name: str
    support_level: ProviderSupportLevel

    def validate_config(self, config: ProviderConfig) -> None: ...

    def create_model(self, model: ModelProfile, options: ModelOptions) -> BaseChatModel: ...

    async def discover_models(self) -> tuple[CatalogEntry, ...]: ...

    def normalize_usage(self, response: object) -> NormalizedUsage | None: ...

    def classify_error(self, error: Exception) -> ProviderError: ...


__all__ = [
    "DiscoveredModel",
    "ModelOptions",
    "ModelProfile",
    "ModelResponse",
    "ProviderAdapter",
    "ProviderCapabilities",
    "ProviderModelSpec",
    "ProviderSupportLevel",
    "StreamChunk",
]
