from __future__ import annotations

from pathlib import Path
from typing import Any

from skail.config.paths import user_config_path


def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        items = ", ".join(f'"{item}"' if isinstance(item, str) else str(item) for item in value)
        return f"[{items}]"
    return f'"{value}"'


def _format_basic_toml(data: dict[str, Any]) -> str:
    lines: list[str] = []
    for k, v in data.items():
        if not isinstance(v, dict):
            lines.append(f"{k} = {_toml_scalar(v)}")

    for section, table in data.items():
        if isinstance(table, dict):
            scalars = {k: v for k, v in table.items() if not isinstance(v, dict)}
            subtables = {k: v for k, v in table.items() if isinstance(v, dict)}
            if scalars or not subtables:
                lines.append(f"\n[{section}]")
                for k, v in scalars.items():
                    lines.append(f"{k} = {_toml_scalar(v)}")
            for sub_k, sub_table in subtables.items():
                if isinstance(sub_table, dict):
                    lines.append(f"\n[{section}.{sub_k}]")
                    for k, v in sub_table.items():
                        lines.append(f"{k} = {_toml_scalar(v)}")
    return "\n".join(lines).strip() + "\n"


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
        except Exception:
            data = {}

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

    try:
        import tomli_w

        raw_toml = tomli_w.dumps(data)
    except Exception:
        raw_toml = _format_basic_toml(data)

    target_path.write_text(raw_toml, encoding="utf-8")
    return target_path


__all__ = ["save_user_provider_models"]
