from datetime import datetime, timedelta, timezone

import pytest

from autoconduck import stats
from autoconduck.stats import aggregate_scopes


def _record(event_id, session_id, minutes_ago, *, model="openai/qwen", pseudo="autoconduck"):
    return {
        "event_id": event_id,
        "session_id": session_id,
        "ts": (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(),
        "upstream_model": model,
        "pseudo_model": pseudo,
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cost": 0.01,
    }


def test_aggregate_scopes_deduplicates_versioned_events_and_preserves_legacy_rows():
    now = datetime.now(timezone.utc)
    records = [
        _record("event-1", "session-a", 5),
        _record("event-1", "session-a", 5),
        _record("event-2", "session-b", 90, model="openai/other", pseudo="autoconduck-budget"),
        {
            "ts": "not-a-timestamp",
            "model": "legacy/model",
            "pseudo_model": "legacy-pseudo",
            "prompt_tokens": 2,
            "completion_tokens": 1,
            "cost": 0.0,
        },
    ]
    records[0]["cache_read_tokens"] = 4
    records[0]["cache_write_tokens"] = 2

    scoped = aggregate_scopes(records, session_id="session-a", now=now)

    assert scoped["all_time"]["totals"]["calls"] == 3
    assert scoped["session"]["id"] == "session-a"
    assert scoped["session"]["usage"]["calls"] == 1
    assert scoped["windows"]["15m"]["totals"]["calls"] == 1
    assert scoped["all_time"]["models"]["openai/qwen"]["calls"] == 1
    assert scoped["all_time"]["pseudo_models"]["autoconduck"]["calls"] == 1
    assert scoped["all_time"]["totals"]["cache_read_tokens"] == 4
    assert scoped["all_time"]["totals"]["cache_write_tokens"] == 2
    assert scoped["windows"]["15m"]["totals"]["calls"] == 1


def test_record_persists_versioned_session_and_selection_contract(monkeypatch, tmp_path):
    target = tmp_path / "stats.jsonl"
    monkeypatch.setattr(stats, "stats_path", lambda: target)

    stats.record(
        "FAST",
        "autoconduck",
        "openai/qwen",
        10,
        5,
        event_id="event-1",
        session_id="session-a",
        upstream_model="openai/qwen",
        latency_ms=12.5,
        cache_read_tokens=3,
        selection={"binding_constraint": "capability"},
    )
    stats.flush_stats()

    row = stats.load_records()[0]
    assert row["stats_version"] == 2
    assert row["event_id"] == "event-1"
    assert row["session_id"] == "session-a"
    assert row["upstream_model"] == "openai/qwen"
    assert row["cache_read_tokens"] == 3
    assert row["selection"] == {"binding_constraint": "capability"}


@pytest.mark.asyncio
async def test_stats_handler_combines_session_and_window_without_removing_legacy_fields(monkeypatch):
    from autoconduck.server import server_meta

    records = [
        _record("event-1", "session-a", 5),
        _record("event-2", "session-b", 5, model="openai/other"),
        _record("event-3", "session-a", 90, model="openai/older"),
    ]
    monkeypatch.setattr(server_meta, "load_records", lambda: records)

    by_session = await server_meta.handle_stats([], session_id="session-a")
    by_window = await server_meta.handle_stats([], window="15m")
    combined = await server_meta.handle_stats([], session_id="session-a", window="15m")

    assert by_session["usage"]["calls"] == 2
    assert by_window["usage"]["calls"] == 2
    assert combined["usage"]["calls"] == 1
    assert by_session["all_time"]["totals"]["calls"] == 3
    assert set(by_session["windows"]) == {"15m", "1h", "1d", "7d", "30d"}


@pytest.mark.asyncio
async def test_stats_handler_rejects_unknown_window(monkeypatch):
    from fastapi import HTTPException
    from autoconduck.server import server_meta

    monkeypatch.setattr(server_meta, "load_records", lambda: [])

    with pytest.raises(HTTPException, match="Unsupported stats window") as exc_info:
        await server_meta.handle_stats([], window="forever")

    assert exc_info.value.status_code == 422
