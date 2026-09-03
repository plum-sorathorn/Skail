from __future__ import annotations

import httpx
import pytest
from fakes.provider import ProviderHTTPFixtureTransport
from rudder.providers.base import ModelOptions, ModelProfile, ProviderSupportLevel
from rudder.providers.openai_compatible import OpenAICompatibleAdapter

from rudder.config.models import ProviderConfig


def _config() -> ProviderConfig:
    return ProviderConfig(
        type="openai-compatible",
        base_url="https://models.example.invalid/v1",
        api_key_env="EXAMPLE_PROVIDER_API_KEY",
        models=("local/test-model",),
    )


def _profile() -> ModelProfile:
    return ModelProfile(
        provider="local-example",
        model="local/test-model",
        support_level=ProviderSupportLevel.MANUAL,
    )


def test_generic_openai_compatible_requires_an_explicit_base_url() -> None:
    config = ProviderConfig(
        type="openai-compatible",
        api_key_env="EXAMPLE_PROVIDER_API_KEY",
        models=("local/test-model",),
    )

    with pytest.raises(ValueError, match="base_url"):
        OpenAICompatibleAdapter(
            "local-example",
            config,
            api_key="fixture-credential",
        )


def test_generic_openai_compatible_requires_explicit_model_declarations() -> None:
    config = ProviderConfig(
        type="openai-compatible",
        base_url="https://models.example.invalid/v1",
        api_key_env="EXAMPLE_PROVIDER_API_KEY",
    )

    with pytest.raises(ValueError, match="model"):
        OpenAICompatibleAdapter(
            "local-example",
            config,
            api_key="fixture-credential",
        )


def test_generic_openai_compatible_defaults_to_manual_non_auto_support() -> None:
    adapter = OpenAICompatibleAdapter(
        "local-example",
        _config(),
        api_key="fixture-credential",
    )

    assert adapter.name == "local-example"
    assert adapter.support_level is ProviderSupportLevel.MANUAL
    assert adapter.auto_routing_eligible is False


@pytest.mark.asyncio
async def test_generic_openai_compatible_uses_only_normalized_response_fields() -> None:
    transport = ProviderHTTPFixtureTransport(provider="generic")
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = OpenAICompatibleAdapter(
            "local-example",
            _config(),
            api_key="fixture-credential",
            http_async_client=client,
        )
        model = adapter.create_model(_profile(), ModelOptions())

        response = await model.ainvoke("Report status")

    assert response.content == "generic response"
    assert "reasoning_content" not in response.additional_kwargs
    assert transport.last_request.path == "/v1/chat/completions"
    assert transport.last_request.json is not None
    assert transport.last_request.json["model"] == "local/test-model"


@pytest.mark.asyncio
async def test_generic_openai_compatible_rejects_provider_mismatch_before_http() -> None:
    transport = ProviderHTTPFixtureTransport(provider="generic")
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = OpenAICompatibleAdapter(
            "local-example",
            _config(),
            api_key="fixture-credential",
            http_async_client=client,
        )
        wrong_provider = ModelProfile(
            provider="different-provider",
            model="local/test-model",
            support_level=ProviderSupportLevel.MANUAL,
        )

        with pytest.raises(ValueError, match="provider"):
            adapter.create_model(wrong_provider, ModelOptions())

    assert transport.requests == []


@pytest.mark.asyncio
async def test_generic_openai_compatible_rejects_undeclared_model_before_http() -> None:
    transport = ProviderHTTPFixtureTransport(provider="generic")
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = OpenAICompatibleAdapter(
            "local-example",
            _config(),
            api_key="fixture-credential",
            http_async_client=client,
        )
        undeclared = ModelProfile(
            provider="local-example",
            model="local/not-declared",
            support_level=ProviderSupportLevel.MANUAL,
        )

        with pytest.raises(ValueError, match="declared|model"):
            adapter.create_model(undeclared, ModelOptions())

    assert transport.requests == []
