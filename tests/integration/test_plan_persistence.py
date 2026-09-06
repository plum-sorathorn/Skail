from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from rudder.domain.events import SecretRedactor
from rudder.domain.ids import new_run_id, new_session_id
from rudder.domain.plans import (
    EffectScope,
    ExecutionPlan,
    PlanNode,
    PlanNodeKind,
    PlanRevision,
)
from rudder.runtime.errors import FrameworkContractError
from rudder.sessions import migrations as journal_migrations
from rudder.sessions.journal import Journal

SESSION_ID = str(new_session_id())
RUN_ID = str(new_run_id())


def _plan(*, schema_version: int = 1) -> ExecutionPlan:
    return ExecutionPlan(
        schema_version=schema_version,
        policy_version="adaptive-v1",
        revision=1,
        nodes=(
            PlanNode(local_id="inspect", kind=PlanNodeKind.AGENT, objective="Inspect"),
            PlanNode(
                local_id="verify",
                kind=PlanNodeKind.VERIFICATION,
                objective="Verify",
                depends_on=("inspect",),
                acceptance_criteria=("tests pass",),
            ),
        ),
    )


def _journal(path: Path) -> Journal:
    journal = Journal(path)
    journal.migrate()
    journal.create_session(session_id=SESSION_ID, title="Plans", created_at=datetime.now(UTC))
    journal.create_run(
        run_id=RUN_ID,
        session_id=SESSION_ID,
        status="running",
        budget_limit_usd=Decimal("2"),
        created_at=datetime.now(UTC),
    )
    return journal


def test_plan_admission_persists_whole_graph_without_allocating_tasks(tmp_path: Path) -> None:
    journal = _journal(tmp_path / "journal.sqlite")
    delivered = []

    def observe(event: object) -> None:
        assert journal.events_after(run_id=RUN_ID)
        delivered.append(event)

    admitted = journal.admit_plan(
        run_id=RUN_ID, plan=_plan(), event_observer=observe
    )

    assert journal.get_plan(admitted.plan_id).plan == _plan()
    assert set(admitted.node_ids) == {"inspect", "verify"}
    snapshot = journal.get_session_snapshot(SESSION_ID)
    assert snapshot.tasks == ()
    assert snapshot.runs[0].plan_schema_version == 1
    assert snapshot.runs[0].execution_policy_version == "adaptive-v1"
    assert [event.type for event in snapshot.events] == [
        "plan.admitted",
        "plan.node_admitted",
        "plan.node_admitted",
    ]
    assert delivered == list(snapshot.events)


def test_failed_plan_admission_leaves_no_partial_records(tmp_path: Path) -> None:
    journal = _journal(tmp_path / "journal.sqlite")
    future = _plan(schema_version=2)

    with pytest.raises(FrameworkContractError, match="plan.schema_unsupported"):
        journal.admit_plan(run_id=RUN_ID, plan=future)

    assert journal.plans_for_run(RUN_ID) == ()
    assert journal.get_session_snapshot(SESSION_ID).tasks == ()


def test_second_plan_for_one_run_is_rejected_in_favor_of_revision(tmp_path: Path) -> None:
    journal = _journal(tmp_path / "journal.sqlite")
    admitted = journal.admit_plan(run_id=RUN_ID, plan=_plan())

    with pytest.raises(FrameworkContractError, match="plan.already_admitted"):
        journal.admit_plan(run_id=RUN_ID, plan=_plan())

    assert journal.plans_for_run(RUN_ID) == (journal.get_plan(admitted.plan_id),)


def test_unauthorized_plan_effect_leaves_no_partial_records(tmp_path: Path) -> None:
    journal = _journal(tmp_path / "journal.sqlite")
    plan = ExecutionPlan(
        schema_version=1,
        policy_version="adaptive-v1",
        revision=1,
        nodes=(
            PlanNode(
                local_id="publish",
                kind=PlanNodeKind.TOOL,
                objective="Publish",
                effect_scope=EffectScope.EXTERNAL_WRITE,
            ),
        ),
    )

    with pytest.raises(FrameworkContractError, match="plan.effect_unauthorized"):
        journal.admit_plan(run_id=RUN_ID, plan=plan)

    assert journal.plans_for_run(RUN_ID) == ()


def test_old_journal_runs_resume_with_legacy_policy_metadata(tmp_path: Path) -> None:
    journal = _journal(tmp_path / "journal.sqlite")

    run = journal.get_session_snapshot(SESSION_ID).runs[0]

    assert run.plan_schema_version is None
    assert run.execution_policy_version is None


def test_plan_migration_preserves_an_existing_legacy_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "legacy.sqlite"
    migrations = journal_migrations.MIGRATIONS
    monkeypatch.setattr(journal_migrations, "MIGRATIONS", migrations[:-1])
    _journal(database)

    monkeypatch.setattr(journal_migrations, "MIGRATIONS", migrations)
    upgraded = Journal(database)
    upgraded.migrate()

    run = upgraded.get_session_snapshot(SESSION_ID).runs[0]
    assert run.plan_schema_version is None
    assert run.execution_policy_version is None


def test_reader_rejects_a_stored_future_plan_version(tmp_path: Path) -> None:
    journal = _journal(tmp_path / "journal.sqlite")
    admitted = journal.admit_plan(run_id=RUN_ID, plan=_plan())
    with sqlite3.connect(journal.path) as connection:
        connection.execute(
            "UPDATE execution_plans SET schema_version=2 WHERE plan_id=?",
            (admitted.plan_id,),
        )

    with pytest.raises(FrameworkContractError, match="plan.schema_unsupported"):
        journal.get_plan(admitted.plan_id)


def test_session_reader_rejects_a_stored_future_policy_version(tmp_path: Path) -> None:
    journal = _journal(tmp_path / "journal.sqlite")
    with sqlite3.connect(journal.path) as connection:
        connection.execute(
            "UPDATE runs SET plan_schema_version=1,execution_policy_version='adaptive-v2' "
            "WHERE run_id=?",
            (RUN_ID,),
        )

    with pytest.raises(FrameworkContractError, match="plan.policy_unsupported"):
        journal.get_session_snapshot(SESSION_ID)


def test_plan_content_is_redacted_before_persistence(tmp_path: Path) -> None:
    canary = "plan-secret-canary"
    journal = Journal(tmp_path / "journal.sqlite", redactor=SecretRedactor([canary]))
    journal.migrate()
    journal.create_session(session_id=SESSION_ID, title="Plans", created_at=datetime.now(UTC))
    journal.create_run(
        run_id=RUN_ID,
        session_id=SESSION_ID,
        status="running",
        budget_limit_usd=None,
        created_at=datetime.now(UTC),
    )
    plan = _plan().model_copy(
        update={"nodes": (_plan().nodes[0].model_copy(update={"objective": canary}),)}
    )

    journal.admit_plan(run_id=RUN_ID, plan=plan)

    assert canary.encode() not in journal.path.read_bytes()


def test_plan_revision_compare_and_set_preserves_existing_node_identity(tmp_path: Path) -> None:
    journal = _journal(tmp_path / "journal.sqlite")
    admitted = journal.admit_plan(run_id=RUN_ID, plan=_plan())
    delivered = []
    revised = ExecutionPlan(
        schema_version=1,
        policy_version="adaptive-v1",
        revision=2,
        nodes=(
            *_plan().nodes,
            PlanNode(local_id="finish", kind=PlanNodeKind.AGENT, objective="Finish"),
        ),
    )
    change = PlanRevision(
        expected_revision=1,
        added_nodes=(revised.nodes[-1],),
        justification="New evidence requires synthesis",
    )

    updated = journal.revise_plan(
        plan_id=admitted.plan_id,
        revision=change,
        plan=revised,
        event_observer=delivered.append,
    )

    assert updated.node_ids["inspect"] == admitted.node_ids["inspect"]
    assert journal.get_plan(admitted.plan_id).plan.revision == 2
    assert [event.type for event in delivered] == ["plan.revised"]
    with pytest.raises(FrameworkContractError, match="plan.revision_conflict"):
        journal.revise_plan(plan_id=admitted.plan_id, revision=change, plan=revised)
