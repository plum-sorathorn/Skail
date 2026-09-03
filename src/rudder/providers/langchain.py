from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from rudder.providers.errors import ProviderConfigurationError, ProviderDependencyError
from rudder.providers.registry import LangChainProviderRegistry

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


def _load_initializer() -> Initializer:
    from langchain.chat_models import init_chat_model

    return init_chat_model
