from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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


def save_catalog_cache(
    path: Path,
    entries: tuple[CatalogEntry, ...],
    *,
    max_entries: int = 5000,
) -> None:
    """Persist a bounded, provenance-bearing provider catalog cache."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "retrieved_at": datetime.now().isoformat(),
        "entries": [
            entry.model_dump(mode="json")
            for entry in sorted(entries, key=lambda item: (item.provider, item.model))[
                :max_entries
            ]
        ],
    }
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def load_catalog_cache(path: Path, *, max_entries: int = 5000) -> tuple[CatalogEntry, ...]:
    """Load a provider catalog cache without turning malformed data into evidence."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_entries = payload.get("entries", [])
        if payload.get("schema_version") != 1 or not isinstance(raw_entries, list):
            return ()
        entries: list[CatalogEntry] = []
        for raw in raw_entries[:max_entries]:
            try:
                entries.append(CatalogEntry.model_validate(raw))
            except (TypeError, ValueError):
                continue
        return tuple(entries)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return ()


__all__ = ["CatalogEntry", "CatalogSource", "load_catalog_cache", "save_catalog_cache"]
