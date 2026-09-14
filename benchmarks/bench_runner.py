#!/usr/bin/env python
from __future__ import annotations

import argparse
import asyncio
import gc
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

# Add project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rudder.agents.context import ContextAssembler, ContextComponent
from rudder.domain.events import (
    EventEnvelope,
    LifecyclePayload,
    ModelPayload,
    SecretRedactor,
    TaskPayload,
    ToolPayload,
)
from rudder.domain.ids import new_run_id, new_session_id
from rudder.runtime.scheduler import ChildScheduler
from rudder.runtime.workspaces import WorkspaceManager
from rudder.sessions.journal import Journal
from rudder.tui.app import RudderApp
from rudder.tui.projection import TuiProjection


def benchmark_event_persistence(iterations: int = 1000) -> dict[str, float]:
    """Measure SQLite append and query throughput for event stream."""
    tmp_dir = tempfile.mkdtemp(prefix="rudder-bench-journal-")
    try:
        db_path = Path(tmp_dir) / "journal.sqlite"
        journal = Journal(db_path)
        journal.migrate()

        session_id = str(new_session_id())
        run_id = str(new_run_id())
        now = datetime.now(UTC)
        journal.create_session(session_id=session_id, title="Bench", created_at=now)
        journal.create_run(
            run_id=run_id,
            session_id=session_id,
            status="running",
            budget_limit_usd=Decimal("10.00"),
            created_at=now,
        )

        events = [
            EventEnvelope(
                event_id=str(uuid4()),
                session_id=session_id,
                run_id=run_id,
                sequence=i + 1,
                occurred_at=now,
                type="session.started",
                payload=LifecyclePayload(status="started"),
            )
            for i in range(iterations)
        ]

        t0 = time.perf_counter()
        for ev in events:
            journal.append_event(event=ev)
        append_time = time.perf_counter() - t0

        t1 = time.perf_counter()
        _ = journal.get_session_snapshot(session_id).events
        read_time = time.perf_counter() - t1

        db_size = db_path.stat().st_size

        del journal
        gc.collect()

        return {
            "iterations": float(iterations),
            "append_seconds": round(append_time, 4),
            "appends_per_sec": round(iterations / max(append_time, 0.001), 1),
            "read_seconds": round(read_time, 4),
            "db_bytes": float(db_size),
            "bytes_per_event": round(db_size / max(iterations, 1), 1),
        }
    finally:
        import shutil
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def benchmark_tui_projection(event_count: int = 1000) -> dict[str, float]:
    """Measure TUI state reconstruction responsiveness under 3 simulated child agents."""
    now = datetime.now(UTC)
    session_id = str(new_session_id())
    run_id = str(new_run_id())

    # Build event stream with 3 concurrent child agents
    events: list[EventEnvelope] = []
    child_ids = [str(uuid4()), str(uuid4()), str(uuid4())]

    for i in range(event_count):
        child_id = child_ids[i % 3]
        if i % 4 != 0:
            ev = EventEnvelope(
                event_id=str(uuid4()),
                session_id=session_id,
                run_id=run_id,
                task_id=child_id,
                sequence=i + 1,
                occurred_at=now,
                type="model.delta",
                payload=ModelPayload(model="lead-model", delta=f"token-{i}"),
            )
        else:
            ev = EventEnvelope(
                event_id=str(uuid4()),
                session_id=session_id,
                run_id=run_id,
                task_id=child_id,
                sequence=i + 1,
                occurred_at=now,
                type="tool.completed",
                payload=ToolPayload(tool="read_file", status="completed"),
            )
        events.append(ev)

    t0 = time.perf_counter()
    projection = TuiProjection()
    for ev in events:
        projection.apply_event(ev)
    duration = time.perf_counter() - t0

    return {
        "event_count": float(event_count),
        "projection_seconds": round(duration, 4),
        "events_per_sec": round(event_count / max(duration, 0.0001), 1),
    }


async def benchmark_tui_rendered_updates(event_count: int = 100) -> dict[str, float]:
    """Measure actual Textual update and interaction work with three active children."""
    now = datetime.now(UTC)
    session_id = new_session_id()
    run_id = new_run_id()
    child_ids = [str(uuid4()), str(uuid4()), str(uuid4())]
    app = RudderApp()

    async with app.run_test(size=(120, 40)) as pilot:
        for sequence, child_id in enumerate(child_ids, start=1):
            app.apply_event(
                EventEnvelope(
                    event_id=str(uuid4()),
                    session_id=session_id,
                    run_id=run_id,
                    task_id=child_id,
                    sequence=sequence,
                    occurred_at=now,
                    type="task.started",
                    payload=TaskPayload(status="started", profile="implementer"),
                )
            )
        await pilot.pause()

        started = time.perf_counter()
        for sequence in range(event_count):
            app.apply_event(
                EventEnvelope(
                    event_id=str(uuid4()),
                    session_id=session_id,
                    run_id=run_id,
                    task_id=child_ids[sequence % len(child_ids)],
                    sequence=sequence + len(child_ids) + 1,
                    occurred_at=now,
                    type="model.delta",
                    payload=ModelPayload(model="fake:fast-model", delta=f"token-{sequence}"),
                )
            )
        await pilot.pause()
        rendered_update_seconds = time.perf_counter() - started

        interaction_started = time.perf_counter()
        await pilot.press("ctrl+a")
        await pilot.pause()
        interaction_seconds = time.perf_counter() - interaction_started

    return {
        "event_count": float(event_count),
        "active_children": float(app.projection.footer_data.active_agents_count),
        "rendered_update_seconds": rendered_update_seconds,
        "rendered_updates_per_sec": event_count / max(rendered_update_seconds, 0.000001),
        "interaction_seconds": interaction_seconds,
    }


def _isolated_cli_environment(home: Path) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "USERPROFILE": str(home),
        "APPDATA": str(home / "AppData"),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
    }


def _run_cli_timed(command: list[str], environment: dict[str, str]) -> float:
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, "-m", "rudder.cli.main", *command],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    if not completed.stdout.strip():
        raise AssertionError("CLI benchmark command produced no useful output")
    return time.perf_counter() - started


def benchmark_cli_runtime() -> dict[str, float]:
    """Measure CLI parsing separately from an offline end-to-end fake-provider response."""
    with tempfile.TemporaryDirectory(prefix="rudder-bench-cli-") as directory:
        environment = _isolated_cli_environment(Path(directory))
        help_seconds = _run_cli_timed(["--help"], environment)
        first_fake_response_seconds = _run_cli_timed(
            ["--print", "offline benchmark", "--model", "fake:fast-model", "--fake-provider"],
            environment,
        )
    return {
        "help_seconds": help_seconds,
        "first_fake_response_seconds": first_fake_response_seconds,
    }


async def _run_scheduler_benchmark() -> dict[str, float]:
    scheduler = ChildScheduler(max_children=3)
    task_ids = [str(uuid4()) for _ in range(4)]
    for task_id in task_ids:
        scheduler.submit(task_id, priority=1)

    async def complete() -> str:
        await asyncio.sleep(0)
        return "completed"

    started = time.perf_counter()
    results = await scheduler.run({task_id: complete for task_id in task_ids})
    return {
        "task_count": float(len(task_ids)),
        "completed_tasks": float(sum(result == "completed" for result in results.values())),
        "dispatch_seconds": time.perf_counter() - started,
    }


def benchmark_scheduler_overhead() -> dict[str, float]:
    """Measure the bounded three-child scheduler with a queued fourth child."""
    return asyncio.run(_run_scheduler_benchmark())


def _git(workspace: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments], cwd=workspace, check=True, capture_output=True, text=True
    )


def benchmark_workspace_setup() -> dict[str, float]:
    """Measure isolated snapshot and worktree setup using a disposable local Git repository."""
    with tempfile.TemporaryDirectory(prefix="rudder-bench-workspace-") as directory:
        root = Path(directory)
        workspace = root / "workspace"
        workspace.mkdir()
        _git(workspace, "init")
        _git(workspace, "config", "user.email", "benchmark@example.invalid")
        _git(workspace, "config", "user.name", "Rudder benchmark")
        (workspace / "input.txt").write_text("benchmark\n", encoding="utf-8")
        _git(workspace, "add", "input.txt")
        _git(workspace, "commit", "-m", "benchmark input")
        manager = WorkspaceManager(root / "state")
        started = time.perf_counter()
        snapshot = manager.capture(workspace)
        isolated = manager.materialize(snapshot, "benchmark-task")
        manager.cleanup_integrated(isolated)
        setup_seconds = time.perf_counter() - started
        shutil.rmtree(root / "state", ignore_errors=True)
    return {"snapshot_files": float(len(snapshot.files)), "setup_seconds": setup_seconds}


def benchmark_context_assembly(item_count: int = 100) -> dict[str, float]:
    """Measure context packet assembly, secret scrubbing, and token-pressure bounding."""
    redactor = SecretRedactor(secrets=("sk-super-secret-12345", "password=admin"))
    assembler = ContextAssembler(max_tokens=2000, redactor=redactor)

    references = tuple(
        ContextComponent(
            label=f"doc-{i}",
            revision="v1",
            content=f"Content for item {i} with sk-super-secret-12345 key payload data.",
            rationale="benchmark load",
            estimated_tokens=50,
        )
        for i in range(item_count)
    )

    t0 = time.perf_counter()
    packet = assembler.assemble(
        task_id="bench-task",
        objective="Stress test context assembler under token pressure",
        constraints=("no-leak", "bounded-token"),
        state="running",
        references=references,
    )
    duration = time.perf_counter() - t0

    return {
        "candidate_items": float(item_count),
        "selected_components": float(len(packet.components)),
        "omissions_count": float(len(packet.omissions)),
        "estimated_tokens": float(packet.estimated_tokens),
        "duration_seconds": round(duration, 4),
    }


def run_benchmarks() -> dict[str, dict[str, float]]:
    return {
        "event_persistence": benchmark_event_persistence(1000),
        "tui_projection": benchmark_tui_projection(1000),
        "tui_rendered_updates": asyncio.run(benchmark_tui_rendered_updates(100)),
        "context_assembly": benchmark_context_assembly(100),
        "cli_runtime": benchmark_cli_runtime(),
        "scheduler_overhead": benchmark_scheduler_overhead(),
        "workspace_setup": benchmark_workspace_setup(),
    }


def validate_benchmarks(results: dict[str, dict[str, float]]) -> list[str]:
    persistence = results["event_persistence"]
    projection = results["tui_projection"]
    context = results["context_assembly"]
    failures: list[str] = []
    if persistence["appends_per_sec"] < 100.0:
        failures.append("event persistence below 100 appends/sec")
    if persistence["read_seconds"] >= 0.1:
        failures.append("event snapshot query exceeded 100ms")
    if persistence["bytes_per_event"] >= 1024.0:
        failures.append("event storage exceeded 1KiB/event")
    if projection["events_per_sec"] < 50_000.0:
        failures.append("TUI projection below 50,000 events/sec")
    if context["duration_seconds"] >= 0.01:
        failures.append("context assembly exceeded 10ms")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Rudder performance gates")
    parser.add_argument("--json", action="store_true", help="emit machine-readable results")
    parser.add_argument("--repetitions", type=int, default=1, help="number of raw benchmark runs")
    parser.add_argument(
        "--evidence", type=Path, help="write raw benchmark evidence outside the checkout"
    )
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions must be at least 1")
    raw_runs = [run_benchmarks() for _ in range(args.repetitions)]
    results = raw_runs[-1]
    failures = [failure for run in raw_runs for failure in validate_benchmarks(run)]
    if args.evidence is not None:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        evidence = {
            "source_commit": commit,
            "python": sys.version,
            "platform": platform.platform(),
            "repetitions": args.repetitions,
            "raw_runs": raw_runs,
        }
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps({"results": results, "failures": failures}, sort_keys=True))
        return 1 if failures else 0

    print("=== Rudder Performance Benchmarks ===")

    print("\n1. Event Persistence Throughput (1,000 events):")
    res_persist = results["event_persistence"]
    for k, v in res_persist.items():
        print(f"  {k}: {v}")

    print("\n2. TUI Projection Responsiveness (1,000 events with 3 child agents):")
    res_tui = results["tui_projection"]
    for k, v in res_tui.items():
        print(f"  {k}: {v}")

    print("\n3. Context Assembly & Budget Enforcement (100 items):")
    res_ctx = results["context_assembly"]
    for k, v in res_ctx.items():
        print(f"  {k}: {v}")

    if failures:
        print("\nBenchmark gates failed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("\nAll benchmark gates passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
