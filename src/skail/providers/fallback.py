from __future__ import annotations

from collections.abc import Callable, Mapping

from pydantic import BaseModel, ConfigDict

from skail.providers.errors import ProviderError, ProviderErrorKind


class FallbackBinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    assignment_id: str
    provider: str
    model: str
    model_key: str
    reservation_id: str


class ProviderFallbackPolicy:
    def __init__(
        self,
        equivalents: Mapping[tuple[str, str], Callable[[str, ProviderError], FallbackBinding]],
        *,
        is_persisted: Callable[[FallbackBinding], bool],
    ) -> None:
        self._equivalents = dict(equivalents)
        self._is_persisted = is_persisted

    def fallback_for(
        self,
        *,
        provider: str,
        model: str,
        assignment_id: str,
        error: ProviderError,
    ) -> FallbackBinding | None:
        if not error.retry_safe or error.kind not in {
            ProviderErrorKind.RATE_LIMIT,
            ProviderErrorKind.TRANSIENT,
        }:
            return None
        factory = self._equivalents.get((provider, model))
        if factory is None:
            return None
        binding = factory(assignment_id, error)
        if binding.model != model:
            raise ValueError("provider fallback must preserve the concrete model identity")
        if not self._is_persisted(binding):
            raise ValueError("provider fallback assignment must be persisted before use")
        return binding
