from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

from skail.providers.errors import ProviderConfigurationError, ProviderDependencyError
from skail.providers.langchain import LangChainModelFactory
from skail.providers.registry import LangChainProviderRegistry, ProviderRegistration


@dataclass(frozen=True)
class ConstructedModel:
    model: str
    model_provider: str
    options: dict[str, object]


def _registration(
    name: str,
    *,
    module: str,
    package: str,
    extra: str,
    tested: bool,
    auto_eligible: bool,
    maintained_ci: bool,
    allowed_options: frozenset[str],
) -> ProviderRegistration:
    return ProviderRegistration(
        name=name,
        module=module,
        package=package,
        extra=extra,
        contract_tested=tested,
        auto_routing_eligible=auto_eligible,
        maintained_ci=maintained_ci,
        allowed_options=allowed_options,
    )


def _representative_registry(
    *,
    package_probe: Callable[[str], bool] = lambda _: True,
) -> LangChainProviderRegistry:
    return LangChainProviderRegistry(
        registrations=(
            _registration(
                "openai",
                module="langchain_openai",
                package="langchain-openai",
                extra="openai",
                tested=True,
                auto_eligible=False,
                maintained_ci=True,
                allowed_options=frozenset(
                    {"api_key", "temperature", "max_tokens", "timeout", "max_retries"}
                ),
            ),
            _registration(
                "anthropic",
                module="langchain_anthropic",
                package="langchain-anthropic",
                extra="anthropic",
                tested=True,
                auto_eligible=False,
                maintained_ci=True,
                allowed_options=frozenset(
                    {"api_key", "temperature", "max_tokens", "timeout", "max_retries"}
                ),
            ),
        ),
        package_probe=package_probe,
    )


def test_registry_reports_support_dimensions_separately() -> None:
    installed = {"langchain_openai"}
    registry = _representative_registry(package_probe=lambda module: module in installed)

    openai = registry.status("openai")
    anthropic = registry.status("anthropic")

    assert openai.installed is True
    assert openai.constructible is True
    assert openai.contract_tested is True
    assert openai.auto_routing_eligible is False
    assert openai.maintained_ci is True
    assert anthropic.installed is False
    assert anthropic.constructible is False
    assert anthropic.contract_tested is True
    assert anthropic.auto_routing_eligible is False
    assert anthropic.maintained_ci is True


def test_registry_and_factory_do_not_import_or_construct_until_create() -> None:
    probes: list[str] = []
    constructions: list[tuple[str, str, dict[str, object]]] = []

    def probe(module: str) -> bool:
        probes.append(module)
        return True

    def initialize(
        model: str,
        *,
        model_provider: str,
        **options: object,
    ) -> ConstructedModel:
        constructions.append((model, model_provider, dict(options)))
        return ConstructedModel(model, model_provider, dict(options))

    registry = _representative_registry(package_probe=probe)
    factory = LangChainModelFactory(registry, initializer=initialize)

    assert probes == []
    assert constructions == []

    model = factory.create(
        provider="openai",
        model="gpt-fixture",
        options={"temperature": 0, "max_retries": 0},
    )

    assert probes == ["langchain_openai"]
    assert constructions == [
        ("gpt-fixture", "openai", {"temperature": 0, "max_retries": 0})
    ]
    assert model.model_provider == "openai"


@pytest.mark.parametrize(
    ("provider", "model"),
    [("openai", "gpt-fixture"), ("anthropic", "claude-fixture")],
)
def test_two_representative_integrations_construct_with_explicit_provider_identity(
    provider: str,
    model: str,
) -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []

    def initialize(
        model: str,
        *,
        model_provider: str,
        **options: object,
    ) -> ConstructedModel:
        calls.append((model, model_provider, dict(options)))
        return ConstructedModel(model, model_provider, dict(options))

    factory = LangChainModelFactory(_representative_registry(), initializer=initialize)

    created = factory.create(
        provider=provider,
        model=model,
        options={"temperature": 0.2, "max_tokens": 256},
    )

    assert created == ConstructedModel(
        model=model,
        model_provider=provider,
        options={"temperature": 0.2, "max_tokens": 256},
    )
    assert calls == [(model, provider, {"temperature": 0.2, "max_tokens": 256})]


def test_missing_optional_package_returns_an_actionable_extra_install_hint() -> None:
    registry = _representative_registry(package_probe=lambda _: False)
    factory = LangChainModelFactory(registry, initializer=lambda *args, **kwargs: object())

    with pytest.raises(ProviderDependencyError) as raised:
        factory.create(provider="anthropic", model="claude-fixture", options={})

    assert raised.value.provider == "anthropic"
    assert raised.value.package == "langchain-anthropic"
    assert raised.value.install_hint == 'python -m pip install "skail-harness[anthropic]"'
    assert "langchain-anthropic" in str(raised.value)


def test_unsupported_options_fail_before_package_probe_or_constructor() -> None:
    probes: list[str] = []
    constructions: list[object] = []

    def probe(module: str) -> bool:
        probes.append(module)
        return True

    def initialize(*args: Any, **kwargs: Any) -> object:
        constructions.append((args, kwargs))
        return object()

    factory = LangChainModelFactory(
        _representative_registry(package_probe=probe),
        initializer=initialize,
    )

    with pytest.raises(ProviderConfigurationError, match="unsupported") as raised:
        factory.create(
            provider="anthropic",
            model="claude-fixture",
            options={"base_url": "https://wrong.example.invalid/v1"},
        )

    assert raised.value.provider == "anthropic"
    assert probes == []
    assert constructions == []


def test_unknown_provider_fails_before_constructor() -> None:
    constructions: list[object] = []

    def initialize(*args: Any, **kwargs: Any) -> object:
        constructions.append((args, kwargs))
        return object()

    factory = LangChainModelFactory(_representative_registry(), initializer=initialize)

    with pytest.raises(ProviderConfigurationError, match="provider"):
        factory.create(provider="not-registered", model="fixture", options={})

    assert constructions == []


def test_default_initializer_constructs_installed_openai_integration() -> None:
    registry = LangChainProviderRegistry(
        registrations=(
            _registration(
                "openai",
                module="langchain_openai",
                package="langchain-openai",
                extra="openai",
                tested=True,
                auto_eligible=False,
                maintained_ci=True,
                allowed_options=frozenset({"api_key", "max_retries"}),
            ),
        )
    )

    model = LangChainModelFactory(registry).create(
        provider="openai",
        model="gpt-fixture",
        options={"api_key": "offline-fixture-key", "max_retries": 0},
    )

    assert type(model).__module__.startswith("langchain_openai")
