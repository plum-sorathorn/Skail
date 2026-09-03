from __future__ import annotations

import httpx

from rudder.config.models import ProviderConfig
from rudder.providers.errors import ProviderError, ProviderErrorKind
from rudder.providers.llmgateway import LLMGATEWAY_BASE_URL
from rudder.providers.models import ProviderSupportLevel
from rudder.providers.openai_compatible import OpenAICompatibleAdapter


class DevPassAdapter(OpenAICompatibleAdapter):
    support_level = ProviderSupportLevel.OPENAI_COMPATIBLE
    auto_routing_eligible = True

    def __init__(
        self,
        config: ProviderConfig,
        *,
        api_key: str,
        http_async_client: httpx.AsyncClient | None = None,
    ) -> None:
        if config.base_url != LLMGATEWAY_BASE_URL:
            raise ValueError(f"DevPass base_url must be {LLMGATEWAY_BASE_URL}")
        super().__init__("devpass", config, api_key=api_key, http_async_client=http_async_client)

    def classify_error(self, error: Exception) -> ProviderError:
        normalized = super().classify_error(error)
        if isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 403:
            return ProviderError(
                kind=ProviderErrorKind.INVALID_MODEL,
                summary="model is unavailable on the DevPass plan",
                provider=self.name,
                retry_safe=False,
                provider_code=normalized.provider_code,
            )
        return normalized
