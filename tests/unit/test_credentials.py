from __future__ import annotations

import pytest

from skail.providers.credentials import (
    CredentialStoreUnavailable,
    EnvironmentCredentialResolver,
)
from skail.providers.errors import ProviderConfigurationError
from skail.providers.factory import ModelFactory, ModelFactoryKey
from skail.runtime.redaction import RedactionRegistry


def test_environment_credential_is_registered_without_repr_leakage() -> None:
    canary = "skail-provider-canary"
    redaction = RedactionRegistry()
    resolver = EnvironmentCredentialResolver(
        redaction, environment={"FIXTURE_API_KEY": canary}
    )

    credential = resolver.resolve("fixture", "FIXTURE_API_KEY")

    assert credential.reveal() == canary
    assert canary not in repr(credential)
    assert redaction.scrub_text(f"failure: {canary}") == "failure: [REDACTED]"


def test_missing_environment_credential_is_actionable_and_secret_free() -> None:
    resolver = EnvironmentCredentialResolver(RedactionRegistry(), environment={})

    with pytest.raises(ProviderConfigurationError) as caught:
        resolver.resolve("fixture", "FIXTURE_API_KEY")

    assert "FIXTURE_API_KEY" in str(caught.value)
    assert "not set" in str(caught.value)


class _CredentialStore:
    def __init__(self, value: str | None = None) -> None:
        self.value = value
        self.saved: str | None = None

    def get(self, provider: str, reference: str) -> str | None:
        del provider, reference
        return self.value

    def set(self, provider: str, reference: str, value: str) -> None:
        del provider, reference
        self.saved = value


def test_environment_credential_wins_over_os_store() -> None:
    store = _CredentialStore("stored-secret")
    resolver = EnvironmentCredentialResolver(
        RedactionRegistry(),
        environment={"FIXTURE_API_KEY": "environment-secret"},
        credential_store=store,
    )

    assert resolver.resolve("fixture", "FIXTURE_API_KEY").reveal() == "environment-secret"
    assert store.saved is None


def test_os_store_credential_is_used_when_environment_is_missing() -> None:
    store = _CredentialStore("stored-secret")
    resolver = EnvironmentCredentialResolver(
        RedactionRegistry(), environment={}, credential_store=store
    )

    assert resolver.resolve("fixture", "FIXTURE_API_KEY").reveal() == "stored-secret"


def test_interactive_credential_requires_secure_store() -> None:
    class UnavailableStore(_CredentialStore):
        def get(self, provider: str, reference: str) -> str | None:
            raise CredentialStoreUnavailable("unavailable")

        def set(self, provider: str, reference: str, value: str) -> None:
            raise CredentialStoreUnavailable("unavailable")

    resolver = EnvironmentCredentialResolver(
        RedactionRegistry(), environment={}, credential_store=UnavailableStore()
    )

    with pytest.raises(ProviderConfigurationError, match="secure credential storage"):
        resolver.resolve("fixture", "FIXTURE_API_KEY", interactive=lambda: "secret")


def test_credential_rotation_changes_the_safe_factory_key() -> None:
    environment = {"FIXTURE_API_KEY": "first-secret"}
    resolver = EnvironmentCredentialResolver(RedactionRegistry(), environment=environment)
    first = resolver.resolve("fixture", "FIXTURE_API_KEY")
    environment["FIXTURE_API_KEY"] = "second-secret"
    second = resolver.resolve("fixture", "FIXTURE_API_KEY")
    first_key = ModelFactoryKey(
        provider="fixture",
        model="model",
        base_url=None,
        credential_reference=first.reference,
        credential_fingerprint=first.fingerprint,
    )
    second_key = ModelFactoryKey(
        provider="fixture",
        model="model",
        base_url=None,
        credential_reference=second.reference,
        credential_fingerprint=second.fingerprint,
    )
    factory = ModelFactory()

    assert first_key != second_key
    assert factory.get_or_create(first_key, object) is not factory.get_or_create(
        second_key, object
    )
    assert "first-secret" not in repr(first_key)
    assert "second-secret" not in repr(second_key)


def test_factory_key_rejects_secret_bearing_options() -> None:
    with pytest.raises(ValueError, match="secret option"):
        ModelFactoryKey(
            provider="fixture",
            model="model",
            base_url=None,
            credential_reference="FIXTURE_API_KEY",
            options=(("api_key", "must-not-enter-cache-key"),),
        )
