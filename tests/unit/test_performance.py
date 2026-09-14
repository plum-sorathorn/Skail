from __future__ import annotations

import benchmarks.bench_runner as bench_runner
from benchmarks.bench_runner import (
    benchmark_context_assembly,
    benchmark_event_persistence,
    benchmark_tui_projection,
    benchmark_tui_rendered_updates,
    validate_benchmarks,
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


def test_benchmark_gate_rejects_missed_thresholds() -> None:
    failures = validate_benchmarks(
        {
            "event_persistence": {
                "appends_per_sec": 1.0,
                "read_seconds": 1.0,
                "bytes_per_event": 5000.0,
            },
            "tui_projection": {"events_per_sec": 1.0},
            "context_assembly": {"duration_seconds": 1.0},
        }
    )

    assert len(failures) == 5


async def test_rendered_tui_benchmark_uses_three_active_children() -> None:
    result = await benchmark_tui_rendered_updates(event_count=12)

    assert result["event_count"] == 12.0
    assert result["active_children"] == 3.0
    assert result["rendered_update_seconds"] >= 0
    assert result["interaction_seconds"] >= 0


def test_benchmark_runner_includes_rendered_diagnostics(monkeypatch) -> None:
    monkeypatch.setattr(bench_runner, "benchmark_event_persistence", lambda *_: {"persist": 1.0})
    monkeypatch.setattr(bench_runner, "benchmark_tui_projection", lambda *_: {"projection": 1.0})
    monkeypatch.setattr(bench_runner, "benchmark_context_assembly", lambda *_: {"context": 1.0})

    async def rendered_updates(*_: object) -> dict[str, float]:
        return {"active_children": 3.0, "rendered_update_seconds": 0.01}

    monkeypatch.setattr(bench_runner, "benchmark_tui_rendered_updates", rendered_updates)

    assert bench_runner.run_benchmarks()["tui_rendered_updates"]["active_children"] == 3.0
