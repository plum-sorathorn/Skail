from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import tomli_w

from skail.config.paths import user_config_path


def save_user_provider_models(
    provider: str,
    models: list[str],
    config_path: Path | None = None,
) -> Path:
    """Persist enabled models for a provider into the user's config.toml."""
    target_path = config_path or user_config_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    data: dict[str, Any] = {}
    if target_path.exists():
        try:
            import tomllib

            with target_path.open("rb") as handle:
                data = tomllib.load(handle)
        except (OSError, ValueError) as exc:
            raise ValueError(f"cannot read user config {target_path}") from exc

    providers = data.setdefault("providers", {})
    if not isinstance(providers, dict):
        providers = {}
        data["providers"] = providers

    provider_entry = providers.setdefault(provider, {})
    if not isinstance(provider_entry, dict):
        provider_entry = {}
        providers[provider] = provider_entry

    clean_models = [
        m.split(":", 1)[1] if ":" in m and m.split(":", 1)[0] == provider else m
        for m in models
    ]
    provider_entry["models"] = clean_models
    if "type" not in provider_entry:
        provider_entry["type"] = (
            "openai-compatible"
            if provider in {"llmgateway", "devpass", "openai"}
            else provider
        )
    if provider == "llmgateway" and "base_url" not in provider_entry:
        provider_entry["base_url"] = "https://api.llmgateway.io/v1"

    raw_toml = tomli_w.dumps(data)
    _atomic_write_text(target_path, raw_toml)
    return target_path


def save_user_routing_model(model: str, config_path: Path | None = None) -> Path:
    """Persist the explicit future lead model without replacing other config."""
    target_path = config_path or user_config_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if target_path.exists():
        try:
            import tomllib

            with target_path.open("rb") as handle:
                data = tomllib.load(handle)
        except (OSError, ValueError) as exc:
            raise ValueError(f"cannot read user config {target_path}") from exc
    routing = data.setdefault("routing", {})
    if not isinstance(routing, dict):
        raise ValueError("user config routing section must be a table")
    routing["lead_model"] = model
    raw_toml = tomli_w.dumps(data)
    _atomic_write_text(target_path, raw_toml)
    return target_path


def _atomic_write_text(path: Path, content: str) -> None:
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f"{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                Path(temporary_path).unlink()
            except OSError:
                pass


__all__ = ["save_user_provider_models", "save_user_routing_model"]
