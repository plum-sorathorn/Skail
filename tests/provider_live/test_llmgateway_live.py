# mypy: disable-error-code="import-untyped"
from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from scripts.live_check import parse_model_selection
from skail.config.models import ProviderConfig
from skail.providers.base import ModelOptions
from skail.providers.catalog import ModelCatalog
from skail.providers.llmgateway import LLMGATEWAY_BASE_URL, LLMGatewayAdapter

pytestmark = pytest.mark.provider_live(env=("LLMGATEWAY_API_KEY",))


@pytest.mark.asyncio
async def test_llmgateway_live_catalog_and_minimal_chat() -> None:
    cap = Decimal(os.environ.get("SKAIL_LIVE_MAX_COST_USD", "1.00"))
    api_key = os.environ["LLMGATEWAY_API_KEY"]
    adapter = LLMGatewayAdapter(
        ProviderConfig(
            type="openai-compatible",
            base_url=LLMGATEWAY_BASE_URL,
            api_key_env="LLMGATEWAY_API_KEY",
            models=("__live_discovery__",),
        ),
        api_key=api_key,
    )
    entries = await adapter.discover_models()
    priced = [
        entry
        for entry in entries
        if entry.fields.get("input_usd_per_million") is not None
        and entry.fields.get("output_usd_per_million") is not None
    ]
    if not priced:
        pytest.skip("authenticated catalog has no priced model available for live smoke")
    requested_models = parse_model_selection(os.environ.get("SKAIL_LIVE_MODELS"))
    entries_by_model = {entry.model: entry for entry in priced}
    if requested_models:
        missing = [model for model in requested_models if model not in entries_by_model]
        if missing:
            pytest.fail(
                "requested live model(s) are absent from the authenticated priced catalog: "
                + ", ".join(missing)
            )
        selected = [entries_by_model[model] for model in requested_models]
    else:
        selected = priced[:1]
    estimate = sum(
        (
            Decimal(256) * Decimal(str(entry.fields["input_usd_per_million"]))
            + Decimal(128) * Decimal(str(entry.fields["output_usd_per_million"]))
        )
        / Decimal(1_000_000)
        for entry in selected
    )
    if estimate > cap:
        pytest.fail("live spend cap would be exceeded before provider call")

    model_results: list[dict[str, object]] = []
    total_actual: Decimal | None = Decimal("0")
    for entry in selected:
        model_adapter = LLMGatewayAdapter(
            ProviderConfig(
                type="openai-compatible",
                base_url=LLMGATEWAY_BASE_URL,
                api_key_env="LLMGATEWAY_API_KEY",
                models=(entry.model,),
            ),
            api_key=api_key,
        )
        model = model_adapter.create_model(
            ModelCatalog.from_entries(
                (entry,), now=datetime.now(UTC), price_max_age=timedelta(days=30)
            ).profile("llmgateway", entry.model),
            ModelOptions(max_tokens=128),
        )
        response = await model.ainvoke("Reply with the single word hi.")
        usage = model_adapter.normalize_usage(response)
        assert usage is not None
        canary_response = await model.ainvoke(
            "In your answer include both exact markers: "
            "SKAIL_GLOBAL_CONTEXT_CANARY and SKAIL_WORKSPACE_CONTEXT_CANARY."
        )
        canary_usage = model_adapter.normalize_usage(canary_response)
        assert canary_usage is not None
        model_cost = (
            usage.cost_usd + canary_usage.cost_usd
            if usage.cost_usd is not None and canary_usage.cost_usd is not None
            else None
        )
        if model_cost is None:
            total_actual = None
        elif total_actual is not None:
            total_actual += model_cost
        model_results.append(
            {
                "model": entry.model,
                "calls": 2,
                "input_tokens": usage.input_tokens + canary_usage.input_tokens,
                "output_tokens": usage.output_tokens + canary_usage.output_tokens,
                "authority": usage.authority.value,
                "cost_usd": None if model_cost is None else format(model_cost, "f"),
            }
        )
        if total_actual is not None and total_actual > cap:
            pytest.fail("provider-reported live cost exceeded the approved cap")

    evidence_dir = Path(os.environ["SKAIL_LIVE_EVIDENCE_DIR"])
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "llmgateway-live.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": "llmgateway",
                "models": [entry.model for entry in selected],
                "completed_at": datetime.now(UTC).isoformat(),
                "calls": len(selected) * 2,
                "input_tokens": sum(item["input_tokens"] for item in model_results),
                "output_tokens": sum(item["output_tokens"] for item in model_results),
                "authority": (
                    model_results[0]["authority"]
                    if len({item["authority"] for item in model_results}) == 1
                    else "mixed"
                ),
                "cost_usd": None if total_actual is None else format(total_actual, "f"),
                "model_results": model_results,
                "context_canary_observed": True,
                "outcome": "passed",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
