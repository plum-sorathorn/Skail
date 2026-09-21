from __future__ import annotations

from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

from skail.cli import commands
from skail.config.loader import ResolvedConfig
from skail.config.models import ProviderConfig, SkailConfig
from skail.providers.catalog_sources import CatalogEntry, CatalogSource, save_catalog_cache


def test_models_list_reports_local_llmgateway_catalog(
    monkeypatch, tmp_path: Path
) -> None:
    entry = CatalogEntry(
        provider="llmgateway",
        model="accessible/model",
        source=CatalogSource.DISCOVERED,
        as_of=datetime(2026, 9, 20, tzinfo=UTC),
        trusted=True,
        provenance="llmgateway:/v1/models?exclude_deprecated=true",
        fields={
            "input_usd_per_million": "1.00",
            "output_usd_per_million": "2.00",
        },
    )
    cache_path = tmp_path / "catalog.json"
    save_catalog_cache(
        cache_path,
        (entry,),
        provider="llmgateway",
        endpoint="https://api.llmgateway.io/v1/models",
        query={"exclude_deprecated": True},
    )
    rendered: list[str] = []
    monkeypatch.setattr(commands, "catalog_cache_path", lambda: cache_path)
    monkeypatch.setattr(commands, "render_print_stdout", rendered.append)
    resolved = ResolvedConfig(
        config=SkailConfig(
            providers={
                "llmgateway": ProviderConfig(
                    type="openai-compatible",
                    base_url="https://api.llmgateway.io/v1",
                    models=("accessible/model",),
                )
            }
        ),
        provenance={},
        warnings=(),
    )

    assert commands.handle_models(
        Namespace(models_action="list"), resolved_config=resolved
    ) == 0
    assert any("LLMGateway catalog: 1 models" in line for line in rendered)
    assert any("llmgateway:accessible/model" in line for line in rendered)


def test_auth_check_reports_configured_custom_environment_name(
    monkeypatch,
) -> None:
    rendered: list[str] = []
    monkeypatch.setattr(commands, "render_print_stdout", rendered.append)
    monkeypatch.setenv("CUSTOM_GATEWAY_TOKEN", "configured")
    resolved = ResolvedConfig(
        config=SkailConfig(
            providers={
                "llmgateway": ProviderConfig(
                    type="openai-compatible",
                    base_url="https://api.llmgateway.io/v1",
                    api_key_env="CUSTOM_GATEWAY_TOKEN",
                )
            }
        ),
        provenance={},
        warnings=(),
    )

    assert commands.handle_auth(
        Namespace(auth_action="check"), resolved_config=resolved
    ) == 0
    assert "CUSTOM_GATEWAY_TOKEN" in rendered[0]
