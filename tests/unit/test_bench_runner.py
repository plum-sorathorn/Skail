from __future__ import annotations

from benchmarks.bench_runner import validate_benchmarks


def test_event_persistence_requires_documented_hundred_appends_per_second() -> None:
    failures = validate_benchmarks(
        {
            "event_persistence": {
                "appends_per_sec": 99.9,
                "read_seconds": 0.01,
                "bytes_per_event": 100.0,
            },
            "tui_projection": {"events_per_sec": 50_000.0},
            "context_assembly": {"duration_seconds": 0.001},
        }
    )

    assert failures == ["event persistence below 100 appends/sec"]
