from __future__ import annotations

from benchmarks.bench_runner import (
    benchmark_context_assembly,
    benchmark_event_persistence,
    benchmark_tui_projection,
)


def test_performance_benchmarks_smoke() -> None:
    # Verify benchmark routines execute cleanly and return positive bounded metrics
    persist_res = benchmark_event_persistence(iterations=20)
    assert persist_res["iterations"] == 20.0
    assert persist_res["append_seconds"] > 0
    assert persist_res["read_seconds"] >= 0
    assert persist_res["bytes_per_event"] > 0

    tui_res = benchmark_tui_projection(event_count=50)
    assert tui_res["event_count"] == 50.0
    assert tui_res["projection_seconds"] >= 0
    assert tui_res["events_per_sec"] > 0

    ctx_res = benchmark_context_assembly(item_count=20)
    assert ctx_res["candidate_items"] == 20.0
    assert ctx_res["selected_components"] > 0
    assert ctx_res["duration_seconds"] >= 0
