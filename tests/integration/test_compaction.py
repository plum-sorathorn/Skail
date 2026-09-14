from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from skail.sessions.compaction import (
    CompactionResult,
    CompactionService,
    SessionCompactionInput,
)
from skail.sessions.journal import Journal

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def _seed_compaction_journal(journal: Journal, session_id: str) -> None:
    journal.migrate()
    journal.create_session(session_id=session_id, title="Compaction Session", created_at=NOW)
    journal.create_run(
        run_id="run-c1",
        session_id=session_id,
        status="running",
        budget_limit_usd=Decimal("10.00"),
        created_at=NOW,
    )
    # Tasks
    journal.create_task(
        task_id="task-1",
        run_id="run-c1",
        description="Fix the parser",
        status="succeeded",
        idempotency_key="k:task-1",
        created_at=NOW,
    )
    journal.create_task(
        task_id="task-2",
        run_id="run-c1",
        description="Run test suite",
        status="running",
        idempotency_key="k:task-2",
        created_at=NOW,
    )
    # Usage
    journal.record_usage(
        usage_id="use-1",
        run_id="run-c1",
        task_id="task-1",
        amount_usd=Decimal("0.42"),
        authoritative=True,
        idempotency_key="k:use-1",
        created_at=NOW,
    )
    # Reservations
    journal.create_reservation(
        reservation_id="res-1",
        run_id="run-c1",
        task_id="task-2",
        amount_usd=Decimal("1.50"),
        status="active",
        idempotency_key="k:res-1",
        created_at=NOW,
    )
    # Approvals
    journal.create_approval(
        approval_id="app-1",
        run_id="run-c1",
        task_id="task-2",
        status="pending",
        question="Approve executing pytest?",
        idempotency_key="k:app-1",
        created_at=NOW,
    )


def test_compaction_preserves_all_required_fields_and_records_source_coverage(
    tmp_path: Path,
) -> None:
    journal = Journal(tmp_path / "journal.sqlite")
    _seed_compaction_journal(journal, "session-c1")

    service = CompactionService(journal=journal, max_context_tokens=1500)

    compaction_input = SessionCompactionInput(
        session_id="session-c1",
        objective="Refactor parser to handle quoted strings",
        constraints=("Do not add external dependencies", "Preserve Windows path handling"),
        terminal_result_summaries={"task-1": "Fixed string unquoting in ast.py"},
        changed_paths=("src/skail/parser.py", "tests/unit/test_parser.py"),
        verification="tests/unit/test_parser.py passed (12/12)",
        verbose_events=(
            {
                "event_id": "ev-1",
                "type": "tool.completed",
                "detail": "Ran git diff with 400 lines of output...",
            },
            {
                "event_id": "ev-2",
                "type": "tool.completed",
                "detail": "Ran pytest with 300 lines of test logs...",
            },
        ),
    )

    result: CompactionResult = service.compact(compaction_input)

    assert result.ok is True
    packet = result.context_packet

    # 1. Preserves ADR 0005 invariants
    assert packet.version == 1
    assert packet.task_id == "session-c1"
    component_labels = {c.label for c in packet.components}
    assert "objective" in component_labels
    assert "constraints" in component_labels
    assert "tasks" in component_labels
    assert "results" in component_labels
    assert "changes_and_verification" in component_labels
    assert "model_and_budget" in component_labels
    assert "approvals_and_questions" in component_labels
    assert "references" in component_labels

    # Check content of components
    obj_comp = next(c for c in packet.components if c.label == "objective")
    assert "Refactor parser" in obj_comp.content

    con_comp = next(c for c in packet.components if c.label == "constraints")
    assert "external dependencies" in con_comp.content

    tasks_comp = next(c for c in packet.components if c.label == "tasks")
    assert "task-2" in tasks_comp.content

    results_comp = next(c for c in packet.components if c.label == "results")
    assert "Fixed string unquoting" in results_comp.content

    changes_comp = next(c for c in packet.components if c.label == "changes_and_verification")
    assert "src/skail/parser.py" in changes_comp.content
    assert "12/12" in changes_comp.content

    budget_comp = next(c for c in packet.components if c.label == "model_and_budget")
    assert "0.42" in budget_comp.content
    assert "1.50" in budget_comp.content

    app_comp = next(c for c in packet.components if c.label == "approvals_and_questions")
    assert "Approve executing pytest?" in app_comp.content

    # 2. Source coverage is recorded
    assert result.source_coverage.covered_events_count == 2
    assert "ev-1" in result.source_coverage.covered_event_ids
    assert "ev-2" in result.source_coverage.covered_event_ids

    # 3. Dropped detail is retrievable via event/artifact references
    ref_comp = next(c for c in packet.components if c.label == "references")
    assert "ev-1" in ref_comp.content
    assert "ev-2" in ref_comp.content


def test_compaction_never_rewrites_usage_records(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.sqlite")
    _seed_compaction_journal(journal, "session-c2")

    snapshot_before = journal.get_session_snapshot("session-c2")
    usage_before = snapshot_before.usage_records
    assert len(usage_before) == 1
    assert usage_before[0].amount_usd == Decimal("0.42")

    service = CompactionService(journal=journal)
    compaction_input = SessionCompactionInput(
        session_id="session-c2",
        objective="Just test usage preservation",
    )
    result = service.compact(compaction_input)
    assert result.ok is True

    snapshot_after = journal.get_session_snapshot("session-c2")
    usage_after = snapshot_after.usage_records
    assert len(usage_after) == 1
    assert usage_after[0].amount_usd == Decimal("0.42")
    assert usage_after[0].usage_id == usage_before[0].usage_id


def test_compaction_preserves_failure_evidence_and_unresolved_questions(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.sqlite")
    _seed_compaction_journal(journal, "session-c4")

    result = CompactionService(journal=journal).compact(
        SessionCompactionInput(
            session_id="session-c4",
            objective="Recover the parser failure",
            failure_evidence={"task-1": "pytest failed: quoted string regression"},
            unresolved_questions=("Should the legacy escape syntax remain supported?",),
        )
    )

    by_label = {component.label: component for component in result.context_packet.components}
    assert "quoted string regression" in by_label["failure_evidence"].content
    assert "legacy escape syntax" in by_label["approvals_and_questions"].content


def test_compaction_bounds_packet_and_persists_selected_context(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.sqlite")
    _seed_compaction_journal(journal, "session-c3")
    service = CompactionService(journal=journal, max_context_tokens=25)

    result = service.compact(
        SessionCompactionInput(
            session_id="session-c3",
            objective="Keep this objective while dropping verbose detail " * 10,
            verbose_events=({"event_id": "ev-1", "type": "tool.completed"},),
        )
    )

    assert result.context_packet.estimated_tokens <= 25
    assert result.context_packet.omissions
    snapshot = journal.get_session_snapshot("session-c3")
    assert len(snapshot.context_packets) == 1
    assert snapshot.context_packets[0].payload["estimated_tokens"] <= 25
