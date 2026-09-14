from __future__ import annotations

import httpx
import pytest
from fakes.provider import ProviderHTTPFixtureTransport

from skail.config.models import ProviderConfig
from skail.providers.base import ModelOptions, ModelProfile, ProviderSupportLevel
from skail.providers.devpass import DevPassAdapter
from skail.providers.errors import ProviderErrorKind
from skail.providers.llmgateway import LLMGATEWAY_BASE_URL, LLMGatewayAdapter


def _devpass_config() -> ProviderConfig:
    return ProviderConfig(
        type="openai-compatible",
        base_url=LLMGATEWAY_BASE_URL,
        api_key_env="LLMGATEWAY_API_KEY",
        models=("claude-opus-5",),
    )


def _devpass_profile() -> ModelProfile:
    return ModelProfile(
        provider="devpass",
        model="claude-opus-5",
        support_level=ProviderSupportLevel.OPENAI_COMPATIBLE,
    )


def test_devpass_and_llmgateway_keep_distinct_provider_identities() -> None:
    devpass = DevPassAdapter(_devpass_config(), api_key="fixture-credential")
    gateway = LLMGatewayAdapter(
        ProviderConfig(
            type="openai-compatible",
            base_url=LLMGATEWAY_BASE_URL,
            api_key_env="LLMGATEWAY_API_KEY",
            models=("anthropic/claude-opus-5",),
        ),
        api_key="fixture-credential",
    )

    assert devpass.name == "devpass"
    assert gateway.name == "llmgateway"
    assert devpass.name != gateway.name
    assert devpass.support_level is ProviderSupportLevel.OPENAI_COMPATIBLE
    assert devpass.base_url == gateway.base_url == LLMGATEWAY_BASE_URL


@pytest.mark.asyncio
async def test_devpass_sends_its_explicit_canonical_plan_model_unchanged() -> None:
    transport = ProviderHTTPFixtureTransport(provider="devpass")
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = DevPassAdapter(
            _devpass_config(),
            api_key="fixture-credential",
            http_async_client=client,
        )
        model = adapter.create_model(_devpass_profile(), ModelOptions())

        response = await model.ainvoke("Report status")

    assert response.content == "devpass response"
    assert transport.last_request.path == "/v1/chat/completions"
    assert transport.last_request.json is not None
    assert transport.last_request.json["model"] == "claude-opus-5"
    assert transport.last_request.headers["authorization"] == "Bearer fixture-credential"


def test_devpass_classifies_a_plan_rejection_as_invalid_model() -> None:
    adapter = DevPassAdapter(_devpass_config(), api_key="fixture-credential")
    request = httpx.Request("POST", f"{LLMGATEWAY_BASE_URL}/chat/completions")
    response = httpx.Response(
        403,
        request=request,
        json={
            "error": {
                "message": "model is not available on this plan",
                "type": "permission_error",
                "code": "permission_denied",
            }
        },
    )
    failure = httpx.HTTPStatusError("provider failed", request=request, response=response)

    normalized = adapter.classify_error(failure)

    assert normalized.kind is ProviderErrorKind.INVALID_MODEL
    assert normalized.provider == "devpass"
    assert normalized.retry_safe is False
