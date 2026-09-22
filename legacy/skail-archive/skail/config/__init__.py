"""Skail configuration module."""

from skail.config.models import (
    ClaudeCodeSettings,
    Config,
    ModelEntry,
    PiSettings,
    PluginConfig,
    SelectionConfig,
)
from skail.config.paths import (
    backups_dir,
    config_path,
    home_dir,
    logs_path,
    run_dir,
)
from skail.config.resolver import (
    _configured_model_sources,
    _normalize_model_entries,
    _repair_base_url_scheme,
    normalize_api_base,
    orchestrator_litellm_params,
    provider_for,
    qualify_model,
    resolve_api_key,
    resolve_orchestrator_model,
    select_model_by_tier,
)
from skail.config.manager import (
    backup_config,
    get_config,
    load_config,
    save_config,
)

__all__ = [
    "ClaudeCodeSettings",
    "Config",
    "ModelEntry",
    "PiSettings",
    "PluginConfig",
    "SelectionConfig",
    "backups_dir",
    "config_path",
    "home_dir",
    "logs_path",
    "run_dir",
    "_configured_model_sources",
    "_normalize_model_entries",
    "_repair_base_url_scheme",
    "normalize_api_base",
    "orchestrator_litellm_params",
    "provider_for",
    "qualify_model",
    "resolve_api_key",
    "resolve_orchestrator_model",
    "select_model_by_tier",
    "backup_config",
    "get_config",
    "load_config",
    "save_config",
]
