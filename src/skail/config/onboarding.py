from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from skail.config.paths import user_data_dir

ONBOARDING_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class OnboardingReceipt:
    schema_version: int = ONBOARDING_SCHEMA_VERSION
    completed: bool = False
    provider: str = "llmgateway"
    selected_model: str = "auto"
    enabled_models: tuple[str, ...] = ()
    theme: str = "system"


def onboarding_path(*, root: Path | None = None) -> Path:
    return user_data_dir(root) / "onboarding.json"


def load_onboarding_receipt(
    *, path: Path | None = None, root: Path | None = None
) -> OnboardingReceipt:
    target = path or onboarding_path(root=root)
    if not target.exists():
        return OnboardingReceipt()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        if payload.get("schema_version") != ONBOARDING_SCHEMA_VERSION:
            raise ValueError("unsupported onboarding schema")
        enabled = payload.get("enabled_models", [])
        if not isinstance(enabled, list) or not all(isinstance(item, str) for item in enabled):
            raise ValueError("enabled_models must be a string list")
        return OnboardingReceipt(
            schema_version=ONBOARDING_SCHEMA_VERSION,
            completed=bool(payload.get("completed", False)),
            provider=_required_string(payload, "provider"),
            selected_model=_required_string(payload, "selected_model"),
            enabled_models=tuple(enabled),
            theme=_required_string(payload, "theme"),
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load onboarding receipt: {error}") from error


def save_onboarding_receipt(
    receipt: OnboardingReceipt,
    *,
    path: Path | None = None,
    root: Path | None = None,
) -> Path:
    target = path or onboarding_path(root=root)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(receipt)
    payload["enabled_models"] = list(receipt.enabled_models)
    _atomic_write(target, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return target


def _required_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _atomic_write(path: Path, content: str) -> None:
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f"{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
