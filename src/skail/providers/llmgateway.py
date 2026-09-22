from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx

from skail.config.models import ProviderConfig
from skail.providers.catalog_sources import CatalogEntry, CatalogSource
from skail.providers.models import ProviderSupportLevel
from skail.providers.openai_compatible import OpenAICompatibleAdapter

LLMGATEWAY_BASE_URL = "https://api.llmgateway.io/v1"


class LLMGatewayAdapter(OpenAICompatibleAdapter):
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
            raise ValueError(f"LLM Gateway base_url must be {LLMGATEWAY_BASE_URL}")
        super().__init__(
            "llmgateway", config, api_key=api_key, http_async_client=http_async_client
        )

    async def discover_models(self) -> tuple[CatalogEntry, ...]:
        response = await self.request("GET", "/models")
        response.raise_for_status()
        raw = response.json()
        entries = []
        for model in raw.get("data", []):
            pricing = model.get("pricing", {})
            parameters = set(model.get("supported_parameters", []))
            fields = {
                "input_usd_per_million": Decimal(str(pricing["prompt"])) * 1_000_000,
                "output_usd_per_million": Decimal(str(pricing["completion"])) * 1_000_000,
                "context_tokens": model.get("context_length"),
                "max_output_tokens": model.get("max_output"),
                "supports_tools": "tools" in parameters,
                "supports_structured_output": bool(model.get("structured_outputs")),
                "supports_reasoning": "reasoning_effort" in parameters,
                "input_modalities": ["text"],
            }
            entries.append(
                CatalogEntry(
                    provider=self.name,
                    model=model["id"],
                    source=CatalogSource.DISCOVERED,
                    as_of=datetime.now(UTC),
                    trusted=False,
                    fields=fields,
                )
            )
        return tuple(entries)
