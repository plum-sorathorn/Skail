from argparse import Namespace
from decimal import Decimal
from pathlib import Path

import skail.cli.commands as commands
from skail.cli.main import _apply_run_config, _build_runtime_models, _parse_agent_models
from skail.config.loader import ResolvedConfig
from skail.config.models import ProviderConfig, SkailConfig
from skail.providers.catalog_sources import CatalogEntry, CatalogSource
from skail.runtime.redaction import RedactionRegistry


def _args(**updates: object) -> Namespace:
    values = {
        "routing_mode": None,
        "lead_model": None,
        "default_model": None,
        "budget": None,
        "max_agents": None,
        "delegation": None,
        "workspace_mode": None,
        "agent_models": [],
    }
    values.update(updates)
    return Namespace(**values)


def test_effective_config_populates_unspecified_runtime_flags() -> None:
    args = _args()
    config = SkailConfig.model_validate(
        {
            "routing": {"mode": "quality", "lead_model": "openai:gpt-test"},
            "orchestration": {
                "delegation": "ask",
                "max_agents": 2,
                "workspace_mode": "shared",
            },
            "budget": {"run_usd": "1.25"},
        }
    )

    _apply_run_config(args, config)

    assert args.routing_mode == "quality"
    assert args.lead_model == "openai:gpt-test"
    assert args.budget == Decimal("1.25")
    assert args.budget_warning_percent == 80
    assert args.max_agents == 2
    assert args.delegation == "ask"


def test_explicit_cli_values_override_config_and_agent_pins_are_validated() -> None:
    args = _args(routing_mode="economy", max_agents=1, budget="0.50")

    _apply_run_config(args, SkailConfig())

    assert args.routing_mode == "economy"
    assert args.max_agents == 1
    assert args.budget == "0.50"
    assert _parse_agent_models(["tester=openai:gpt-test"]) == {
        "tester": "openai:gpt-test"
    }


def test_runtime_model_construction_uses_configured_provider_and_credential_reference(
    monkeypatch,
) -> None:
    from skail.providers.llmgateway import LLMGatewayAdapter

    async def no_discovered_models(_: LLMGatewayAdapter) -> tuple[CatalogEntry, ...]:
        return ()

    monkeypatch.setattr(LLMGatewayAdapter, "discover_models", no_discovered_models)
    args = _args(lead_model="llmgateway:test/model")
    args.fake_provider = False
    config = SkailConfig(
        providers={
            "llmgateway": ProviderConfig(
                type="openai-compatible",
                base_url="https://api.llmgateway.io/v1",
                api_key_env="CUSTOM_GATEWAY_TOKEN",
                models=("test/model",),
            )
        },
        catalog={
            "entries": [
                {
                    "provider": "llmgateway",
                    "model": "test/model",
                    "source": "user",
                    "trusted": True,
                    "as_of": "2026-09-04T00:00:00Z",
                    "fields": {
                        "input_usd_per_million": "1.25",
                        "output_usd_per_million": "2.50",
                        "capability": {
                            "coding": 0.8,
                            "reasoning": 0.8,
                            "tool_reliability": 0.8,
                            "latency": 0.8,
                        },
                    },
                }
            ]
        },
    )
    _apply_run_config(args, config)
    monkeypatch.setenv("CUSTOM_GATEWAY_TOKEN", "configured-canary-token")

    runtime_models = _build_runtime_models(
        args,
        RedactionRegistry(),
    )
    models, lead_model, child_model = runtime_models

    assert lead_model == "llmgateway:test/model"
    assert child_model == "llmgateway:test/model"
    assert "llmgateway:test/model" in models
    assert runtime_models.providers["llmgateway"].name == "llmgateway"


def test_runtime_bootstrap_uses_configured_catalog_without_production_defaults(
    monkeypatch,
) -> None:
    from skail.providers.llmgateway import LLMGatewayAdapter

    async def no_discovered_models(_: LLMGatewayAdapter) -> tuple[CatalogEntry, ...]:
        return ()

    monkeypatch.setattr(LLMGatewayAdapter, "discover_models", no_discovered_models)
    args = _args(lead_model="llmgateway:test/model")
    args.fake_provider = False
    catalog_entry = CatalogEntry(
        provider="llmgateway",
        model="test/model",
        source=CatalogSource.USER,
        trusted=True,
        as_of="2026-09-04T00:00:00Z",
        fields={
            "input_usd_per_million": "1.25",
            "output_usd_per_million": "2.50",
            "context_tokens": 32768,
            "supports_tools": True,
            "capability": {
                "coding": 0.8,
                "reasoning": 0.8,
                "tool_reliability": 0.8,
                "latency": 0.8,
            },
        },
    )
    config = SkailConfig(
        providers={
            "llmgateway": ProviderConfig(
                type="openai-compatible",
                base_url="https://api.llmgateway.io/v1",
                api_key_env="CUSTOM_GATEWAY_TOKEN",
                models=("test/model",),
            )
        },
        catalog={"entries": [catalog_entry]},
    )
    _apply_run_config(args, config)
    monkeypatch.setenv("CUSTOM_GATEWAY_TOKEN", "configured-canary-token")

    runtime_models = _build_runtime_models(args, RedactionRegistry())

    profile = runtime_models.catalog.profile("llmgateway", "test/model")
    assert profile.input_usd_per_million == Decimal("1.25")
    assert profile.context_tokens == 32768
    assert tuple(runtime_models.models) == ("llmgateway:test/model",)


def test_runtime_bootstrap_registers_every_discovered_gateway_model(
    monkeypatch, tmp_path: Path
) -> None:
    from skail.providers.llmgateway import LLMGatewayAdapter

    entries = tuple(
        CatalogEntry(
            provider="llmgateway",
            model=model,
            source=CatalogSource.DISCOVERED,
            trusted=False,
            as_of="2026-09-20T00:00:00Z",
            provenance="llmgateway:/v1/models?exclude_deprecated=true",
            fields={
                "input_usd_per_million": "1.00",
                "output_usd_per_million": "2.00",
                "context_tokens": 32768,
                "max_output_tokens": 4096,
                "supports_tools": True,
            },
        )
        for model in ("discovered/one", "discovered/two")
    )

    async def discover(_: LLMGatewayAdapter) -> tuple[CatalogEntry, ...]:
        return entries

    monkeypatch.setattr(LLMGatewayAdapter, "discover_models", discover)
    args = _args(lead_model="llmgateway:discovered/one")
    args.fake_provider = False
    args.catalog_cache_path = tmp_path / "catalog.json"
    args.provider_configs = {
        "llmgateway": ProviderConfig(
            type="openai-compatible",
            base_url="https://api.llmgateway.io/v1",
            api_key_env="CUSTOM_GATEWAY_TOKEN",
            models=(),
        )
    }
    args.effective_config = SkailConfig(providers=args.provider_configs)
    monkeypatch.setenv("CUSTOM_GATEWAY_TOKEN", "configured-canary-token")

    runtime_models = _build_runtime_models(args, RedactionRegistry())

    assert set(runtime_models.models) == {
        "llmgateway:discovered/one",
        "llmgateway:discovered/two",
    }
    assert len(runtime_models.candidates) == 2
    assert runtime_models.catalog is not None
    assert (
        runtime_models.catalog.profile("llmgateway", "discovered/two").catalog_updated_at
        is not None
    )


def test_config_inspection_uses_the_already_resolved_effective_config(monkeypatch) -> None:
    resolved = ResolvedConfig(config=SkailConfig(), provenance={}, warnings=())
    rendered: list[str] = []
    def unexpected_load(**_: object) -> object:
        raise AssertionError("config was resolved twice")

    monkeypatch.setattr(commands, "load_config", unexpected_load)
    monkeypatch.setattr(commands, "render_print_stdout", rendered.append)

    assert (
        commands.handle_config(
            Namespace(config_action="show"),
            Path("."),
            resolved_config=resolved,
        )
        == 0
    )
    assert '"routing"' in rendered[0]
