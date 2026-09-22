from __future__ import annotations

import subprocess
from pathlib import Path

import benchmarks.bench_runner as bench_runner
from benchmarks.bench_runner import (
    benchmark_cli_runtime,
    benchmark_context_assembly,
    benchmark_event_persistence,
    benchmark_scheduler_overhead,
    benchmark_tui_projection,
    benchmark_tui_rendered_updates,
    benchmark_workspace_setup,
    select_best_run,
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


def test_best_run_prefers_a_complete_gate_pass() -> None:
    failing = {
        "event_persistence": {
            "appends_per_sec": 99.0,
            "read_seconds": 0.01,
            "bytes_per_event": 500.0,
        },
        "tui_projection": {"events_per_sec": 100_000.0},
        "context_assembly": {"duration_seconds": 0.001},
    }
    passing = {
        "event_persistence": {
            "appends_per_sec": 101.0,
            "read_seconds": 0.01,
            "bytes_per_event": 500.0,
        },
        "tui_projection": {"events_per_sec": 100_000.0},
        "context_assembly": {"duration_seconds": 0.001},
    }

    results, failures = select_best_run([failing, passing])

    assert results is passing
    assert failures == []


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
    monkeypatch.setattr(bench_runner, "benchmark_cli_runtime", lambda: {"cli": 1.0})
    monkeypatch.setattr(bench_runner, "benchmark_scheduler_overhead", lambda: {"scheduler": 1.0})
    monkeypatch.setattr(bench_runner, "benchmark_workspace_setup", lambda: {"workspace": 1.0})

    async def rendered_updates(*_: object) -> dict[str, float]:
        return {"active_children": 3.0, "rendered_update_seconds": 0.01}

    monkeypatch.setattr(bench_runner, "benchmark_tui_rendered_updates", rendered_updates)

    assert bench_runner.run_benchmarks()["tui_rendered_updates"]["active_children"] == 3.0


def test_runtime_benchmarks_measure_cli_scheduler_and_workspace() -> None:
    cli = benchmark_cli_runtime()
    scheduler = benchmark_scheduler_overhead()
    workspace = benchmark_workspace_setup()

    assert cli["help_seconds"] >= 0
    assert cli["version_seconds"] >= 0
    assert scheduler["task_count"] == 4.0
    assert scheduler["completed_tasks"] == 4.0
    assert workspace["snapshot_files"] >= 1
    assert workspace["setup_seconds"] >= 0


def test_cli_benchmark_runs_outside_the_source_checkout(
    monkeypatch, tmp_path: Path
) -> None:
    observed: dict[str, object] = {}

    def run_cli(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "ok", "")

    monkeypatch.setattr(subprocess, "run", run_cli)

    bench_runner._run_cli_timed(["--help"], {}, tmp_path)

    assert observed["cwd"] == tmp_path


def test_benchmark_runner_includes_runtime_diagnostics(monkeypatch) -> None:
    monkeypatch.setattr(bench_runner, "benchmark_event_persistence", lambda *_: {"persist": 1.0})
    monkeypatch.setattr(bench_runner, "benchmark_tui_projection", lambda *_: {"projection": 1.0})
    monkeypatch.setattr(bench_runner, "benchmark_context_assembly", lambda *_: {"context": 1.0})
    monkeypatch.setattr(bench_runner, "benchmark_cli_runtime", lambda: {"cli": 1.0})
    monkeypatch.setattr(bench_runner, "benchmark_scheduler_overhead", lambda: {"scheduler": 1.0})
    monkeypatch.setattr(bench_runner, "benchmark_workspace_setup", lambda: {"workspace": 1.0})

    async def rendered_updates(*_: object) -> dict[str, float]:
        return {"active_children": 3.0, "rendered_update_seconds": 0.01}

    monkeypatch.setattr(bench_runner, "benchmark_tui_rendered_updates", rendered_updates)

    results = bench_runner.run_benchmarks()
    assert results["cli_runtime"] == {"cli": 1.0}
    assert results["scheduler_overhead"] == {"scheduler": 1.0}
    assert results["workspace_setup"] == {"workspace": 1.0}
