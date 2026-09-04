#!/usr/bin/env python
from __future__ import annotations

import gc
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
    ToolPayload,
)
from rudder.domain.ids import new_run_id, new_session_id
from rudder.sessions.journal import Journal
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


def main() -> None:
    print("=== Rudder Performance Benchmarks ===")

    print("\n1. Event Persistence Throughput (1,000 events):")
    res_persist = benchmark_event_persistence(1000)
    for k, v in res_persist.items():
        print(f"  {k}: {v}")

    print("\n2. TUI Projection Responsiveness (1,000 events with 3 child agents):")
    res_tui = benchmark_tui_projection(1000)
    for k, v in res_tui.items():
        print(f"  {k}: {v}")

    print("\n3. Context Assembly & Budget Enforcement (100 items):")
    res_ctx = benchmark_context_assembly(100)
    for k, v in res_ctx.items():
        print(f"  {k}: {v}")

    print("\nAll benchmarks finished cleanly.")


if __name__ == "__main__":
    main()
