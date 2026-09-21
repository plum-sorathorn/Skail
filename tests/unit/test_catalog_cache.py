from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from skail.providers.catalog_sources import (
    CatalogEntry,
    CatalogSource,
    load_catalog_cache,
    load_catalog_snapshot,
    save_catalog_cache,
)


def _entry(model: str = "model-a") -> CatalogEntry:
    return CatalogEntry(
        provider="llmgateway",
        model=model,
        source=CatalogSource.DISCOVERED,
        as_of=datetime(2026, 9, 20, 23, 0, tzinfo=UTC),
        trusted=True,
        provenance="llmgateway:/v1/models?exclude_deprecated=true",
        fields={
            "input_usd_per_million": Decimal("1.25"),
            "output_usd_per_million": Decimal("2.50"),
        },
    )


def test_catalog_snapshot_round_trips_provider_metadata_and_decimal_prices(
    tmp_path: Path,
) -> None:
    path = tmp_path / "catalog.json"

    save_catalog_cache(
        path,
        (_entry(),),
        provider="llmgateway",
        endpoint="https://api.llmgateway.io/v1/models",
        query={"exclude_deprecated": True},
        retrieved_at=datetime(2026, 9, 20, 23, 41, tzinfo=UTC),
    )

    snapshot = load_catalog_snapshot(path, provider="llmgateway")

    assert snapshot is not None
    assert snapshot.schema_version == 2
    assert snapshot.endpoint == "https://api.llmgateway.io/v1/models"
    assert snapshot.query == {"exclude_deprecated": True}
    assert snapshot.retrieved_at.tzinfo is not None
    assert snapshot.entries[0].fields["input_usd_per_million"] == Decimal("1.25")
    assert load_catalog_cache(path, provider="llmgateway") == snapshot.entries
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["entries"][0]["fields"]["input_usd_per_million"] == "1.25"


def test_catalog_snapshot_rejects_malformed_entries_as_a_whole(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "provider": "llmgateway",
                "endpoint": "https://api.llmgateway.io/v1/models",
                "query": {"exclude_deprecated": True},
                "retrieved_at": "2026-09-20T23:41:00Z",
                "entries": [
                    _entry().model_dump(mode="json"),
                    {"provider": "llmgateway", "model": "missing-fields"},
                ],
            }
        ),
        encoding="utf-8",
    )

    assert load_catalog_snapshot(path, provider="llmgateway") is None
    assert load_catalog_cache(path, provider="llmgateway") == ()


def test_catalog_snapshot_rejects_naive_retrieval_time(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "provider": "llmgateway",
                "endpoint": "https://api.llmgateway.io/v1/models",
                "query": {"exclude_deprecated": True},
                "retrieved_at": "2026-09-20T23:41:00",
                "entries": [_entry().model_dump(mode="json")],
            }
        ),
        encoding="utf-8",
    )

    assert load_catalog_snapshot(path, provider="llmgateway") is None


def test_catalog_save_does_not_silently_truncate_entries(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="maximum catalog entry count"):
        save_catalog_cache(
            tmp_path / "catalog.json",
            (_entry("model-a"), _entry("model-b")),
            max_entries=1,
        )
