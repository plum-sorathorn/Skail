from argparse import Namespace
from decimal import Decimal

from rudder.cli.main import _apply_run_config, _build_runtime_models, _parse_agent_models
from rudder.config.models import ProviderConfig, RudderConfig
from rudder.runtime.redaction import RedactionRegistry


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
    config = RudderConfig.model_validate(
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

    _apply_run_config(args, RudderConfig())

    assert args.routing_mode == "economy"
    assert args.max_agents == 1
    assert args.budget == "0.50"
    assert _parse_agent_models(["tester=openai:gpt-test"]) == {
        "tester": "openai:gpt-test"
    }


def test_runtime_model_construction_uses_configured_provider_and_credential_reference(
    monkeypatch,
) -> None:
    args = _args(lead_model="llmgateway:test/model")
    args.fake_provider = False
    config = RudderConfig(
        providers={
            "llmgateway": ProviderConfig(
                type="openai-compatible",
                base_url="https://api.llmgateway.io/v1",
                api_key_env="CUSTOM_GATEWAY_TOKEN",
                models=("test/model",),
            )
        }
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
