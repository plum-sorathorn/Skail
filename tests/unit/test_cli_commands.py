from __future__ import annotations

from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

from skail.cli import commands
from skail.config.loader import ResolvedConfig
from skail.config.models import ProviderConfig, SkailConfig
from skail.providers.catalog_sources import (
    CatalogEntry,
    CatalogSource,
    load_catalog_snapshot,
    save_catalog_cache,
)


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


def test_models_refresh_discovers_and_persists_catalog_without_printing_credential(
    monkeypatch, tmp_path: Path
) -> None:
    from skail.providers.llmgateway import LLMGatewayAdapter

    entry = CatalogEntry(
        provider="llmgateway",
        model="refreshed/model",
        source=CatalogSource.DISCOVERED,
        as_of=datetime(2026, 9, 22, tzinfo=UTC),
        trusted=True,
        provenance="llmgateway:/v1/models?exclude_deprecated=true",
        fields={
            "input_usd_per_million": "0.10",
            "output_usd_per_million": "0.20",
            "supports_tools": True,
            "supports_structured_output": True,
        },
    )

    async def discover(_: LLMGatewayAdapter) -> tuple[CatalogEntry, ...]:
        return (entry,)

    cache_path = tmp_path / "catalog.json"
    rendered: list[str] = []
    monkeypatch.setattr(LLMGatewayAdapter, "discover_models", discover)
    monkeypatch.setattr(
        commands, "catalog_cache_path", lambda provider="llmgateway": cache_path
    )
    monkeypatch.setattr(commands, "render_print_stdout", rendered.append)
    monkeypatch.setenv("LLMGATEWAY_API_KEY", "test-token-never-print")
    resolved = ResolvedConfig(
        config=SkailConfig(
            providers={
                "llmgateway": ProviderConfig(
                    type="openai-compatible",
                    base_url="https://api.llmgateway.io/v1",
                    models=("refreshed/model",),
                )
            }
        ),
        provenance={},
        warnings=(),
    )

    assert commands.handle_models(
        Namespace(models_action="refresh"), resolved_config=resolved
    ) == 0

    snapshot = load_catalog_snapshot(cache_path, provider="llmgateway")
    assert snapshot is not None
    assert tuple(entry.model for entry in snapshot.entries) == ("refreshed/model",)
    assert any("Refreshed LLM Gateway catalog: 1 models" in line for line in rendered)
    assert all("test-token-never-print" not in line for line in rendered)


def test_models_refresh_rejects_empty_provider_catalog_without_overwriting_cache(
    monkeypatch, tmp_path: Path
) -> None:
    from skail.providers.llmgateway import LLMGatewayAdapter

    cached_entry = CatalogEntry(
        provider="llmgateway",
        model="cached/model",
        source=CatalogSource.DISCOVERED,
        as_of=datetime(2026, 9, 21, tzinfo=UTC),
        trusted=True,
        fields={
            "input_usd_per_million": "0.10",
            "output_usd_per_million": "0.20",
        },
    )
    cache_path = tmp_path / "catalog.json"
    save_catalog_cache(cache_path, (cached_entry,), provider="llmgateway")

    async def discover(_: LLMGatewayAdapter) -> tuple[CatalogEntry, ...]:
        return ()

    rendered: list[str] = []
    monkeypatch.setattr(LLMGatewayAdapter, "discover_models", discover)
    monkeypatch.setattr(
        commands, "catalog_cache_path", lambda provider="llmgateway": cache_path
    )
    monkeypatch.setattr(commands, "render_print_stderr", rendered.append)
    monkeypatch.setenv("LLMGATEWAY_API_KEY", "test-token")
    resolved = ResolvedConfig(
        config=SkailConfig(
            providers={
                "llmgateway": ProviderConfig(
                    type="openai-compatible",
                    base_url="https://api.llmgateway.io/v1",
                    models=("cached/model",),
                )
            }
        ),
        provenance={},
        warnings=(),
    )

    assert commands.handle_models(
        Namespace(models_action="refresh"), resolved_config=resolved
    ) == 1

    snapshot = load_catalog_snapshot(cache_path, provider="llmgateway")
    assert snapshot is not None
    assert tuple(entry.model for entry in snapshot.entries) == ("cached/model",)
    assert any("no accessible models" in line for line in rendered)


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


def test_auth_status_reports_onboarding_keyring_credential(monkeypatch) -> None:
    class StoredCredential:
        def get(self, provider: str, reference: str) -> str | None:
            if (provider, reference) == ("llmgateway", "LLMGATEWAY_API_KEY"):
                return "stored-secret"
            return None

        def set(self, provider: str, reference: str, value: str) -> None:
            raise AssertionError("status must not write credentials")

        def delete(self, provider: str, reference: str) -> None:
            raise AssertionError("status must not delete credentials")

    rendered: list[str] = []
    monkeypatch.delenv("LLMGATEWAY_API_KEY", raising=False)
    monkeypatch.setattr(commands, "render_print_stdout", rendered.append)

    assert commands.handle_auth(
        Namespace(auth_action="status"), credential_store=StoredCredential()
    ) == 0
    assert any("LLMGATEWAY_API_KEY" in line and "CONFIGURED" in line for line in rendered)
    assert all("stored-secret" not in line for line in rendered)
