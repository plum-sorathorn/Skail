from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

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


class CredentialStoreUnavailable(RuntimeError):
    pass


class CredentialStore(Protocol):
    def get(self, provider: str, reference: str) -> str | None: ...

    def set(self, provider: str, reference: str, value: str) -> None: ...


class KeyringCredentialStore:
    """OS credential-store adapter; absence of keyring support is fail-closed."""

    service_name = "skail-harness"

    def get(self, provider: str, reference: str) -> str | None:
        try:
            import keyring
        except ImportError as error:
            raise CredentialStoreUnavailable("OS credential storage is unavailable") from error
        try:
            return keyring.get_password(self.service_name, f"{provider}:{reference}")
        except Exception as error:
            raise CredentialStoreUnavailable("OS credential storage is unavailable") from error

    def set(self, provider: str, reference: str, value: str) -> None:
        try:
            import keyring
        except ImportError as error:
            raise CredentialStoreUnavailable("OS credential storage is unavailable") from error
        try:
            keyring.set_password(self.service_name, f"{provider}:{reference}", value)
        except Exception as error:
            raise CredentialStoreUnavailable("OS credential storage is unavailable") from error


class EnvironmentCredentialResolver:
    def __init__(
        self,
        redaction: RedactionRegistry,
        *,
        environment: Mapping[str, str] | None = None,
        credential_store: CredentialStore | None = None,
    ) -> None:
        self.redaction = redaction
        self.environment = environment if environment is not None else os.environ
        self.credential_store = credential_store or KeyringCredentialStore()

    def resolve(
        self,
        provider: str,
        reference: str | None,
        *,
        interactive: Callable[[], str] | None = None,
    ) -> ResolvedCredential:
        if not reference:
            raise ProviderConfigurationError(provider, "api_key_env reference is required")
        value = self.environment.get(reference)
        if not value:
            try:
                value = self.credential_store.get(provider, reference)
            except CredentialStoreUnavailable as error:
                if interactive is not None:
                    raise ProviderConfigurationError(
                        provider,
                        "secure credential storage is unavailable; "
                        f"set {reference} in the environment",
                    ) from error
        if not value and interactive is not None:
            value = interactive()
            try:
                self.credential_store.set(provider, reference, value)
            except CredentialStoreUnavailable as error:
                raise ProviderConfigurationError(
                    provider,
                    f"secure credential storage is unavailable; set {reference} in the environment",
                ) from error
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
