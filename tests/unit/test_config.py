from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import BaseModel

from rudder.config import (
    ConfigValidationError,
    LiteralSecretError,
    ProjectConfigSecurityError,
    load_config,
    merge_config_layers,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "config"
pytestmark = pytest.mark.unit


def test_defaults_are_typed_and_match_the_stable_product_contract() -> None:
    resolved = load_config()

    assert isinstance(resolved.config, BaseModel)
    assert resolved.config.routing.mode == "auto"
    assert resolved.config.routing.lead_model == "auto"
    assert resolved.config.orchestration.max_agents == 3
    assert resolved.config.orchestration.max_depth == 1
    assert resolved.config.orchestration.background_agents is False
    assert resolved.config.orchestration.workspace_mode == "shared"
    assert resolved.config.budget.run_usd is None
    assert resolved.config.budget.warning_percent == 80
    assert resolved.config.safety.project_trust == "ask"


def test_config_precedence_is_cli_then_trusted_project_then_user_then_defaults() -> None:
    resolved = load_config(
        user_path=FIXTURES / "user.toml",
        project_path=FIXTURES / "project.toml",
        project_trusted=True,
        cli_overrides={
            "routing.mode": "auto",
            "orchestration.max_agents": 3,
        },
    )

    assert resolved.config.routing.mode == "auto"
    assert resolved.config.routing.lead_model == "project/lead"
    assert resolved.config.routing.allow_unmeasured_models is False
    assert resolved.config.orchestration.max_agents == 3
    assert resolved.config.orchestration.delegation == "ask"
    assert resolved.config.orchestration.max_depth == 1
    assert resolved.config.budget.run_usd == Decimal("3.50")
    assert resolved.config.budget.warning_percent == 70
    assert resolved.provenance_for("routing.mode").source == "cli"
    assert resolved.provenance_for("routing.lead_model").source == "project"
    assert resolved.provenance_for("routing.allow_unmeasured_models").source == "user"
    assert resolved.provenance_for("safety.write_policy").source == "default"


def test_untrusted_project_config_never_enters_the_effective_config() -> None:
    resolved = load_config(
        user_path=FIXTURES / "user.toml",
        project_path=FIXTURES / "project.toml",
        project_trusted=False,
    )

    assert resolved.config.routing.lead_model == "user/lead"
    assert resolved.config.orchestration.max_agents == 2
    assert resolved.config.budget.warning_percent == 80
    assert resolved.provenance_for("routing.lead_model").source == "user"


def test_recursive_tables_merge_while_lists_replace() -> None:
    merged = merge_config_layers(
        {
            "routing": {"mode": "auto", "fallback_models": ["alpha", "beta"]},
            "providers": {"gateway": {"type": "openai-compatible"}},
        },
        {
            "routing": {"fallback_models": ["gamma"]},
            "providers": {"gateway": {"base_url": "https://example.invalid/v1"}},
        },
    )

    assert merged == {
        "routing": {"mode": "auto", "fallback_models": ["gamma"]},
        "providers": {
            "gateway": {
                "type": "openai-compatible",
                "base_url": "https://example.invalid/v1",
            }
        },
    }


def test_cli_can_explicitly_unset_a_nullable_value() -> None:
    resolved = load_config(
        user_path=FIXTURES / "user.toml",
        cli_unset={"providers.llmgateway.api_key_env"},
    )

    assert resolved.config.providers["llmgateway"].api_key_env is None
    assert resolved.provenance_for("providers.llmgateway.api_key_env").source == "cli"


def test_provenance_reports_sources_without_paths_or_resolved_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canary = "canary-value-that-must-not-be-rendered"
    monkeypatch.setenv("LLMGATEWAY_API_KEY", canary)
    user_path = tmp_path / "private-user-name" / "config.toml"
    user_path.parent.mkdir()
    user_path.write_text((FIXTURES / "user.toml").read_text(encoding="utf-8"), encoding="utf-8")

    resolved = load_config(user_path=user_path)
    provenance = resolved.provenance_for("providers.llmgateway.api_key_env")
    rendered = repr(provenance)

    assert provenance.source == "user"
    assert str(tmp_path) not in rendered
    assert "private-user-name" not in rendered
    assert canary not in rendered


def test_unknown_user_key_is_ignored_with_a_warning() -> None:
    with pytest.warns(UserWarning, match="routing.future_toggle"):
        resolved = load_config(user_path=FIXTURES / "user_unknown.toml")

    assert any("routing.future_toggle" in warning for warning in resolved.warnings)


def test_security_sensitive_unknown_project_key_fails_closed() -> None:
    with pytest.raises(ProjectConfigSecurityError, match="safety.bypass_workspace_boundary"):
        load_config(
            project_path=FIXTURES / "project_security_unknown.toml",
            project_trusted=True,
        )


def test_trusted_project_cannot_weaken_user_safety_policy(tmp_path: Path) -> None:
    user = tmp_path / "user.toml"
    project = tmp_path / "project.toml"
    user.write_text(
        '[safety]\nwrite_policy = "deny"\ncommand_policy = "deny"\n',
        encoding="utf-8",
    )
    project.write_text(
        '[safety]\nwrite_policy = "allow-workspace"\ncommand_policy = "ask-dangerous"\n',
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigSecurityError, match="cannot weaken"):
        load_config(user_path=user, project_path=project, project_trusted=True)


def test_llm_gateway_accepts_only_its_exact_canonical_v1_url() -> None:
    resolved = load_config(user_path=FIXTURES / "user.toml")

    assert resolved.config.providers["llmgateway"].base_url == "https://api.llmgateway.io/v1"


@pytest.mark.parametrize(
    "base_url",
    [
        "http://api.llmgateway.io/v1",
        "https://api.llmgateway.io",
        "https://api.llmgateway.io/v1/",
        "https://api.llmgateway.io/v1/chat/completions",
        "https://example.com/v1",
    ],
)
def test_llm_gateway_rejects_noncanonical_urls(tmp_path: Path, base_url: str) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[providers.llmgateway]",
                'type = "openai-compatible"',
                f'base_url = "{base_url}"',
                'api_key_env = "LLMGATEWAY_API_KEY"',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigValidationError, match="https://api.llmgateway.io/v1"):
        load_config(user_path=config_path)


def test_provider_config_rejects_literal_secrets_without_echoing_them() -> None:
    literal = "fixture-literal-must-be-rejected"

    with pytest.raises(LiteralSecretError) as caught:
        load_config(user_path=FIXTURES / "literal_secret.toml")

    assert literal not in str(caught.value)
