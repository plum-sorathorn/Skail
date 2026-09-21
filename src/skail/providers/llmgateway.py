from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

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
        response = await self.request(
            "GET",
            "/models",
            params={"exclude_deprecated": "true"},
        )
        response.raise_for_status()
        raw = response.json()
        if not isinstance(raw, Mapping) or not isinstance(raw.get("data"), list):
            raise ValueError("LLM Gateway models response has no data list")
        entries: list[CatalogEntry] = []
        for model in raw.get("data", []):
            if not isinstance(model, Mapping) or not isinstance(model.get("id"), str):
                continue
            pricing = model.get("pricing")
            pricing_map = pricing if isinstance(pricing, Mapping) else {}
            architecture = model.get("architecture")
            architecture_map = architecture if isinstance(architecture, Mapping) else {}
            parameters = {
                str(value)
                for value in model.get("supported_parameters", [])
                if isinstance(value, str)
            }
            provider_mappings = [
                mapping
                for mapping in model.get("providers", [])
                if isinstance(mapping, Mapping)
            ]
            mapping_tools = [mapping.get("tools") for mapping in provider_mappings]
            mapping_reasoning = [mapping.get("reasoning") for mapping in provider_mappings]
            input_modalities = architecture_map.get("input_modalities")
            output_modalities = architecture_map.get("output_modalities")
            fields = {
                "input_usd_per_million": _price_per_million(pricing_map, "prompt"),
                "output_usd_per_million": _price_per_million(pricing_map, "completion"),
                "cached_input_usd_per_million": _price_per_million(
                    pricing_map, "input_cache_read"
                ),
                "context_tokens": _positive_int(model.get("context_length")),
                "max_output_tokens": _positive_int(model.get("max_output")),
                "supports_tools": _capability_flag(
                    model.get("tools"),
                    mapping_tools,
                    true_when="tools" in parameters,
                ),
                "supports_structured_output": (
                    bool(model["structured_outputs"])
                    if "structured_outputs" in model
                    else bool(model["json_output"]) if "json_output" in model else None
                ),
                "supports_reasoning": _capability_flag(
                    model.get("reasoning"),
                    mapping_reasoning,
                    true_when=(
                        "reasoning_effort" in parameters or "reasoning" in parameters
                    ),
                ),
                "input_modalities": (
                    list(input_modalities)
                    if isinstance(input_modalities, list)
                    else ["text"]
                ),
                "output_modalities": (
                    list(output_modalities)
                    if isinstance(output_modalities, list)
                    else ["text"]
                ),
                "created": model.get("created"),
                "stability": model.get("stability"),
                "provider_mappings": provider_mappings,
            }
            entries.append(
                CatalogEntry(
                    provider=self.name,
                    model=model["id"],
                    source=CatalogSource.DISCOVERED,
                    as_of=datetime.now(UTC),
                    trusted=True,
                    provenance="llmgateway:/v1/models?exclude_deprecated=true",
                    fields=fields,
                )
            )
        return tuple(entries)


def _capability_flag(
    top_level: Any,
    mappings: list[Any],
    *,
    true_when: bool,
) -> bool | None:
    if isinstance(top_level, bool):
        return top_level
    if any(value is True for value in mappings):
        return True
    if mappings and all(value is False for value in mappings):
        return False
    return True if true_when else None


def _price_per_million(pricing: Mapping[str, Any], field: str) -> Decimal | None:
    value = pricing.get(field)
    if value is None or isinstance(value, bool):
        return None
    try:
        price = Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return None
    if not price.is_finite() or price < 0:
        return None
    return price * Decimal("1000000")


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        integer = int(value)
    except (TypeError, ValueError):
        return None
    return integer if integer > 0 else None
