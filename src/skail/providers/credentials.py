from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256

from skail.providers.errors import ProviderConfigurationError
from skail.runtime.redaction import RedactionRegistry


@dataclass(frozen=True, repr=False)
class ResolvedCredential:
    reference: str
    _value: str
    fingerprint: str

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"ResolvedCredential(reference={self.reference!r}, value='[REDACTED]')"


class EnvironmentCredentialResolver:
    def __init__(
        self,
        redaction: RedactionRegistry,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.redaction = redaction
        self.environment = environment if environment is not None else os.environ

    def resolve(self, provider: str, reference: str | None) -> ResolvedCredential:
        if not reference:
            raise ProviderConfigurationError(provider, "api_key_env reference is required")
        value = self.environment.get(reference)
        if not value:
            raise ProviderConfigurationError(
                provider, f"credential environment variable {reference} is not set"
            )
        self.redaction.register(value)
        fingerprint = sha256(value.encode("utf-8")).hexdigest()
        return ResolvedCredential(
            reference=reference,
            _value=value,
            fingerprint=fingerprint,
        )
