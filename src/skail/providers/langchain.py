from __future__ import annotations

from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

from skail.config.models import ProviderConfig
from skail.domain.usage import NormalizedUsage, UsageAuthority
from skail.providers.base import ModelOptions
from skail.providers.catalog_sources import CatalogEntry
from skail.providers.errors import (
    ProviderConfigurationError,
    ProviderDependencyError,
    ProviderError,
    ProviderErrorKind,
)
from skail.providers.models import ModelProfile, ProviderSupportLevel
from skail.providers.registry import LangChainProviderRegistry

Initializer = Callable[..., Any]


class LangChainModelFactory:
    def __init__(
        self,
        registry: LangChainProviderRegistry,
        *,
        initializer: Initializer | None = None,
    ) -> None:
        self.registry = registry
        self._initializer = initializer

    def create(
        self,
        *,
        provider: str,
        model: str,
        options: Mapping[str, object],
    ) -> Any:
        registration = self.registry.registration(provider)
        unsupported = set(options) - registration.allowed_options
        if unsupported:
            names = ", ".join(sorted(unsupported))
            raise ProviderConfigurationError(provider, f"unsupported options: {names}")
        if not self.registry.is_installed(registration):
            raise ProviderDependencyError(provider, registration.package, registration.extra)
        initializer = self._initializer or _load_initializer()
        return initializer(model, model_provider=provider, **dict(options))


class LangChainUsageAdapter:
    """Normalize generic LangChain usage without claiming provider-authoritative cost."""

    support_level = ProviderSupportLevel.NATIVE

    def __init__(self, name: str) -> None:
        self.name = name

    def validate_config(self, config: ProviderConfig) -> None:
        del config

    def create_model(self, model: ModelProfile, options: ModelOptions) -> BaseChatModel:
        del model, options
        raise NotImplementedError("model construction is owned by LangChainModelFactory")

    async def discover_models(self) -> tuple[CatalogEntry, ...]:
        return ()

    def normalize_usage(self, response: object) -> NormalizedUsage | None:
        if not isinstance(response, BaseMessage):
            return None
        metadata = getattr(response, "usage_metadata", None)
        if not isinstance(metadata, dict):
            return None
        return NormalizedUsage(
            input_tokens=int(metadata.get("input_tokens", 0)),
            output_tokens=int(metadata.get("output_tokens", 0)),
            cost_usd=Decimal("0"),
            authority=UsageAuthority.ESTIMATED_ACTUAL,
        )

    def classify_error(self, error: Exception) -> ProviderError:
        return ProviderError(
            kind=ProviderErrorKind.PROTOCOL,
            summary=str(error),
            provider=self.name,
            retry_safe=False,
        )


def _load_initializer() -> Initializer:
    from langchain.chat_models import init_chat_model

    return init_chat_model
