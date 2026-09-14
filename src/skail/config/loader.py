from __future__ import annotations

import tomllib
import warnings as warning_module
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from skail.config.models import SkailConfig


class ConfigValidationError(ValueError):
    pass


class ProjectConfigSecurityError(ConfigValidationError):
    pass


class LiteralSecretError(ConfigValidationError):
    pass


@dataclass(frozen=True)
class Provenance:
    source: str
    value: Any


@dataclass(frozen=True)
class ResolvedConfig:
    config: SkailConfig
    provenance: dict[str, Provenance]
    warnings: tuple[str, ...]

    def provenance_for(self, dotted_key: str) -> Provenance:
        return self.provenance[dotted_key]


def merge_config_layers(*mappings: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for mapping in mappings:
        merged = _merge(merged, mapping)
    return merged


def load_config(
    *,
    user_path: Path | None = None,
    project_path: Path | None = None,
    project_trusted: bool = False,
    cli_overrides: dict[str, Any] | None = None,
    cli_unset: tuple[str, ...] = (),
) -> ResolvedConfig:
    warning_messages: list[str] = []
    layers: list[tuple[str, dict[str, Any]]] = [("default", SkailConfig().model_dump())]
    if user_path is not None and user_path.exists():
        user = _read_toml(user_path)
        _reject_literal_secrets(user)
        user = _sanitize(user, project=False, warnings=warning_messages)
        layers.append(("user", user))
    if project_path is not None and project_path.exists():
        if project_trusted:
            project = _read_toml(project_path)
            _reject_literal_secrets(project)
            project = _sanitize(project, project=True, warnings=warning_messages)
            _enforce_project_safety(merge_config_layers(*(layer for _, layer in layers)), project)
            layers.append(("project", project))
        else:
            warning_messages.append("ignored untrusted project configuration")
    if cli_overrides:
        layers.append(("cli", _expand_dotted(cli_overrides)))
    if cli_unset:
        unset_values: dict[str, Any] = {}
        for key in cli_unset:
            _set_dotted(unset_values, key, None)
        layers.append(("cli", unset_values))

    merged: dict[str, Any] = {}
    provenance: dict[str, Provenance] = {}
    for source, layer in layers:
        merged = _merge(merged, layer)
        for key, value in _flatten(layer).items():
            provenance[key] = Provenance(source=source, value=_redact_provenance(key, value))
    try:
        config = SkailConfig.model_validate(merged)
    except ValidationError as exc:
        raise ConfigValidationError(str(exc)) from exc
    for message in warning_messages:
        warning_module.warn(message, UserWarning, stacklevel=2)
    return ResolvedConfig(config=config, provenance=provenance, warnings=tuple(warning_messages))


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigValidationError(f"cannot load config {path}: {exc}") from exc


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _expand_dotted(values: dict[str, Any]) -> dict[str, Any]:
    expanded: dict[str, Any] = {}
    for key, value in values.items():
        if "." in key:
            _set_dotted(expanded, key, value)
        else:
            expanded[key] = value
    return expanded


def _set_dotted(target: dict[str, Any], key: str, value: Any) -> None:
    parts = key.split(".")
    cursor = target
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = value


def _flatten(value: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, item in value.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict):
            flattened.update(_flatten(item, dotted))
        else:
            flattened[dotted] = item
    return flattened


_TOP_LEVEL_FIELDS = frozenset(SkailConfig.model_fields)
_SECTION_FIELDS = {
    name: frozenset(field.annotation.model_fields)  # type: ignore[union-attr]
    for name, field in SkailConfig.model_fields.items()
    if name != "providers" and hasattr(field.annotation, "model_fields")
}
_PROVIDER_FIELDS = frozenset({"type", "base_url", "api_key_env", "models"})
_SECURITY_SECTIONS = frozenset({"providers", "safety", "tools", "mcp", "agents", "catalog"})


def _sanitize(value: dict[str, Any], *, project: bool, warnings: list[str]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, item in value.items():
        if key not in _TOP_LEVEL_FIELDS:
            _unknown(key, project=project, security=key in _SECURITY_SECTIONS, warnings=warnings)
            continue
        if key == "providers" and isinstance(item, dict):
            providers: dict[str, Any] = {}
            for provider, provider_value in item.items():
                if not isinstance(provider_value, dict):
                    providers[provider] = provider_value
                    continue
                providers[provider] = _sanitize_fields(
                    provider_value,
                    _PROVIDER_FIELDS,
                    prefix=f"providers.{provider}",
                    project=project,
                    security=True,
                    warnings=warnings,
                )
            clean[key] = providers
        elif key in _SECTION_FIELDS and isinstance(item, dict):
            clean[key] = _sanitize_fields(
                item,
                _SECTION_FIELDS[key],
                prefix=key,
                project=project,
                security=key in _SECURITY_SECTIONS,
                warnings=warnings,
            )
        else:
            clean[key] = item
    return clean


def _sanitize_fields(
    value: dict[str, Any],
    allowed: frozenset[str],
    *,
    prefix: str,
    project: bool,
    security: bool,
    warnings: list[str],
) -> dict[str, Any]:
    clean = {}
    for key, item in value.items():
        if key not in allowed:
            _unknown(f"{prefix}.{key}", project=project, security=security, warnings=warnings)
        else:
            clean[key] = item
    return clean


def _unknown(key: str, *, project: bool, security: bool, warnings: list[str]) -> None:
    if project and security:
        raise ProjectConfigSecurityError(f"unknown security-sensitive project key: {key}")
    warnings.append(f"ignored unknown config key: {key}")


_SECRET_KEYS = frozenset({"api_key", "token", "password", "secret", "authorization"})


def _reject_literal_secrets(value: Any, path: str = "") -> None:
    if not isinstance(value, dict):
        return
    for key, item in value.items():
        dotted = f"{path}.{key}" if path else key
        if key.lower() in _SECRET_KEYS and item not in (None, ""):
            raise LiteralSecretError(f"literal secret is prohibited at {dotted}")
        _reject_literal_secrets(item, dotted)


def _redact_provenance(key: str, value: Any) -> Any:
    if any(part.lower() in _SECRET_KEYS for part in key.split(".")):
        return "[REDACTED]"
    return value


def _enforce_project_safety(baseline: dict[str, Any], project: dict[str, Any]) -> None:
    project_safety = project.get("safety")
    if not isinstance(project_safety, dict):
        return
    if "project_trust" in project_safety:
        raise ProjectConfigSecurityError("project config cannot set safety.project_trust")
    baseline_safety = baseline.get("safety", {})
    ranks = {
        "write_policy": {"allow-workspace": 0, "ask": 1, "deny": 2},
        "command_policy": {"ask-dangerous": 0, "ask": 1, "deny": 2},
    }
    for key, policy_ranks in ranks.items():
        proposed = project_safety.get(key)
        current = baseline_safety.get(key)
        if proposed is None or current is None:
            continue
        if policy_ranks.get(proposed, -1) < policy_ranks.get(current, -1):
            raise ProjectConfigSecurityError(
                f"project config cannot weaken safety.{key} from {current} to {proposed}"
            )
