from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CatalogSource(StrEnum):
    DISCOVERED = "discovered"
    MAINTAINED = "maintained"
    EVALUATED = "evaluated"
    USER = "user"


class CatalogEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider: str
    model: str
    source: CatalogSource
    as_of: datetime
    trusted: bool
    provenance: str = ""
    fields: dict[str, Any] = Field(default_factory=dict)

    @field_validator("fields", mode="before")
    @classmethod
    def restore_decimal_price_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        restored = dict(value)
        for name in (
            "input_usd_per_million",
            "output_usd_per_million",
            "cached_input_usd_per_million",
        ):
            price = restored.get(name)
            if isinstance(price, str):
                try:
                    restored[name] = Decimal(price)
                except (ArithmeticError, ValueError):
                    pass
        return restored


class CatalogCacheSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 2
    provider: str = Field(min_length=1)
    endpoint: str = Field(min_length=1)
    query: dict[str, bool] = Field(default_factory=dict)
    retrieved_at: datetime
    entries: tuple[CatalogEntry, ...]

    @field_validator("retrieved_at")
    @classmethod
    def require_aware_retrieved_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("catalog retrieved_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_snapshot(self) -> CatalogCacheSnapshot:
        if self.schema_version != 2:
            raise ValueError("unsupported catalog cache schema version")
        if any(
            entry.as_of.tzinfo is None or entry.as_of.utcoffset() is None
            for entry in self.entries
        ):
            raise ValueError("catalog entry timestamps must include a timezone")
        if any(entry.provider != self.provider for entry in self.entries):
            raise ValueError("catalog cache contains entries for another provider")
        return self


def save_catalog_cache(
    path: Path,
    entries: tuple[CatalogEntry, ...],
    *,
    provider: str | None = None,
    endpoint: str | None = None,
    query: dict[str, bool] | None = None,
    retrieved_at: datetime | None = None,
    max_entries: int = 5000,
) -> None:
    """Persist a validated, provenance-bearing provider catalog cache atomically."""
    if len(entries) > max_entries:
        raise ValueError(f"maximum catalog entry count is {max_entries}")
    selected_provider = provider or (entries[0].provider if entries else "unknown")
    selected_endpoint = endpoint or (
        "https://api.llmgateway.io/v1/models"
        if selected_provider == "llmgateway"
        else "unknown"
    )
    selected_retrieved_at = retrieved_at or datetime.now(UTC)
    snapshot = CatalogCacheSnapshot(
        provider=selected_provider,
        endpoint=selected_endpoint,
        query=query or {},
        retrieved_at=selected_retrieved_at,
        entries=tuple(sorted(entries, key=lambda item: (item.provider, item.model))),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = snapshot.model_dump(mode="json")
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
            json.dump(payload, handle, sort_keys=True)
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


def load_catalog_snapshot(
    path: Path,
    *,
    provider: str | None = None,
    endpoint: str | None = None,
    max_entries: int = 5000,
) -> CatalogCacheSnapshot | None:
    """Load a complete catalog snapshot without turning malformed data into evidence."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        if payload.get("schema_version") == 1:
            raw_entries = payload.get("entries")
            if not isinstance(raw_entries, list) or len(raw_entries) > max_entries:
                return None
            inferred_provider = provider or (
                str(raw_entries[0].get("provider"))
                if raw_entries and isinstance(raw_entries[0], dict)
                else None
            )
            if not inferred_provider:
                return None
            retrieved_at = _parse_timestamp(payload.get("retrieved_at"))
            if retrieved_at is None:
                return None
            payload = {
                "schema_version": 2,
                "provider": inferred_provider,
                "endpoint": endpoint
                or (
                    "https://api.llmgateway.io/v1/models"
                    if inferred_provider == "llmgateway"
                    else "unknown"
                ),
                "query": {"exclude_deprecated": True}
                if inferred_provider == "llmgateway"
                else {},
                "retrieved_at": retrieved_at,
                "entries": raw_entries,
            }
        if payload.get("schema_version") != 2:
            return None
        snapshot = CatalogCacheSnapshot.model_validate(payload)
        if provider is not None and snapshot.provider != provider:
            return None
        if endpoint is not None and snapshot.endpoint != endpoint:
            return None
        if len(snapshot.entries) > max_entries:
            return None
        return snapshot
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def load_catalog_cache(
    path: Path,
    *,
    provider: str | None = None,
    max_entries: int = 5000,
) -> tuple[CatalogEntry, ...]:
    """Load catalog entries while preserving the legacy tuple-returning API."""
    snapshot = load_catalog_snapshot(path, provider=provider, max_entries=max_entries)
    return () if snapshot is None else snapshot.entries


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


__all__ = [
    "CatalogCacheSnapshot",
    "CatalogEntry",
    "CatalogSource",
    "load_catalog_cache",
    "load_catalog_snapshot",
    "save_catalog_cache",
]
