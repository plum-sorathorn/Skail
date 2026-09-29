import asyncio
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import pytest
from fakes.barriers import AsyncStartBarrier
from fakes.models import ScriptedChatModel, parallel_tool_call_message, tool_call_message
from langchain_core.messages import AIMessage

from skail.agents.lead import LeadControls
from skail.domain.decisions import ExecutionDecision
from skail.domain.ids import new_session_id
from skail.domain.plans import ExecutionPlan, PlanNodeState
from skail.domain.tasks import (
    ArtifactRef,
    AttemptStatus,
    TaskResult,
    TaskStatus,
    VerificationResult,
)
from skail.runtime.run_controller import RunController
from skail.runtime.workspaces import WorkspaceManager, WorkspaceMode
from skail.sessions.journal import Journal
from skail.tools.execution import ExecutionPolicy, ExecutionResult
from skail.tui.app import SkailApp
from skail.tui.widgets.composer import ComposerTextArea


def _journal(tmp_path: Path) -> Journal:
    j = Journal(tmp_path / "journal.sqlite")
    j.migrate()
    return j


def _git(workspace: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=workspace, check=True, capture_output=True, text=True
    )


def _repository(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _git(workspace, "init")
    _git(workspace, "config", "user.email", "tests@example.invalid")
    _git(workspace, "config", "user.name", "Skail tests")
    (workspace / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(workspace, "add", "tracked.txt")
    _git(workspace, "commit", "-m", "initial")
    return workspace


@pytest.mark.asyncio
async def test_worktree_writer_receives_a_dirty_snapshot_and_records_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _repository(tmp_path)
    (workspace / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    journal = _journal(tmp_path / "state")
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Worktree writer", created_at=datetime.now(UTC)
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    ("execution_decision", _direct_decision("Delegate safely"), "decision-1"),
                    (
                        "task",
                        {
                            "description": (
                                '{"description":"Update the tracked file",'
                                '"success_criteria":["Provide evidence for the completed task"],'
                                '"write_scope":["tracked.txt"]}'
                            ),
                            "subagent_type": "implementer",
                        },
                        "task-1",
                    ),
                ]
            ),
            AIMessage(content="The worker completed its isolated task."),
        ],
    )
    child_roots: list[Path] = []
    child_options: list[dict[str, object]] = []

    class ChildAgent:
        def __init__(self, root: Path, task_id: str) -> None:
            self.root = root
            self.task_id = task_id

        async def ainvoke(self, state):
            del state
            child_roots.append(self.root)
            assert (self.root / "tracked.txt").read_text(encoding="utf-8") == "dirty\n"
            (self.root / "tracked.txt").write_bytes(b"integrated\n")
            return {
                "messages": [
                    AIMessage(
                        content=TaskResult(
                            task_id=self.task_id,
                            status="succeeded",
                            summary="updated in isolated workspace",
                            verification=(
                                VerificationResult(
                                    criterion="Provide evidence for the completed task",
                                    passed=True,
                                    evidence="tracked.txt:1",
                                    evidence_ref=ArtifactRef(
                                        kind="file",
                                        path="tracked.txt",
                                        digest=hashlib.sha256(b"integrated\n").hexdigest(),
                                    ),
                                ),
                            ),
                        ).model_dump_json()
                    )
                ]
            }

    def build_child(*args, **kwargs):
        del args
        child_options.append(kwargs)
        return ChildAgent(kwargs["workspace"], kwargs["task_id"])

    monkeypatch.setattr("skail.runtime.run_controller.build_default_agent", build_child)
    controller = RunController(
        session_id=session_id,
        workspace=workspace,
        journal=journal,
        models={"lead-model": lead_model, "implementer-model": lead_model},
        workspace_mode="worktree",
        workspace_manager=WorkspaceManager(tmp_path / "skail-data"),
    )

    result = await controller.run_instruction("Delegate this change")

    assert controller.workspace_selection.mode is WorkspaceMode.WORKTREE
    assert child_roots and child_roots[0] != workspace
    assert child_options[0]["forbidden_host_paths"] == (workspace.resolve(),)
    assert child_options[0]["execute_allowed"] is False
    assert result.child_results, result
    assert result.child_results[0].status == "succeeded", result.child_results
    assert not child_roots[0].exists(), (
        (child_roots[0] / "retained.json").read_text(encoding="utf-8")
        if (child_roots[0] / "retained.json").exists()
        else "worktree retained without reason"
    )
    assert (workspace / "tracked.txt").read_text(encoding="utf-8") == "integrated\n"
    with sqlite3.connect(journal.path) as connection:
        changesets = connection.execute("SELECT status FROM change_sets").fetchall()
    assert changesets == [("integrated",)]
    selection_events = [
        event
        for event in journal.events_after(run_id=str(result.run_id))
        if event.type == "diagnostic.workspace"
    ]
    assert selection_events[-1].payload.details["mode"] == "worktree"


@pytest.mark.asyncio
async def test_disjoint_worktree_writers_overlap_before_serial_integration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _repository(tmp_path)
    (workspace / "second.txt").write_bytes(b"second base\n")
    _git(workspace, "add", "second.txt")
    _git(workspace, "commit", "-m", "second input")
    journal = _journal(tmp_path / "state")
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Overlapping writers", created_at=datetime.now(UTC)
    )
    requests = []
    for path in ("tracked.txt", "second.txt"):
        requests.append(
            (
                "task",
                {
                    "description": (
                        '{"description":"Update ' + path + '",'
                        '"success_criteria":["Provide evidence for the completed task"],'
                        '"write_scope":["' + path + '"]}'
                    ),
                    "subagent_type": "implementer",
                },
                f"task-{path}",
            )
        )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        _direct_decision("Run disjoint writers"),
                        "decision-1",
                    ),
                    *requests,
                ]
            ),
            AIMessage(content="Both changes were integrated."),
        ],
    )
    barrier = AsyncStartBarrier()

    class ChildAgent:
        def __init__(self, root: Path, task_id: str, allowed_paths: tuple[str, ...]) -> None:
            self.root = root
            self.task_id = task_id
            self.path = allowed_paths[0]

        async def ainvoke(self, state):
            del state
            await barrier.worker(self.path)
            content = f"integrated {self.path}\n".encode()
            (self.root / self.path).write_bytes(content)
            return {
                "messages": [
                    AIMessage(
                        content=TaskResult(
                            task_id=self.task_id,
                            status="succeeded",
                            summary=f"updated {self.path}",
                            verification=(
                                VerificationResult(
                                    criterion="Provide evidence for the completed task",
                                    passed=True,
                                    evidence=f"{self.path}:1",
                                    evidence_ref=ArtifactRef(
                                        kind="file",
                                        path=self.path,
                                        digest=hashlib.sha256(content).hexdigest(),
                                    ),
                                ),
                            ),
                        ).model_dump_json()
                    )
                ]
            }

    def build_child(*args, **kwargs):
        del args
        return ChildAgent(kwargs["workspace"], kwargs["task_id"], kwargs["allowed_write_paths"])

    monkeypatch.setattr("skail.runtime.run_controller.build_default_agent", build_child)
    controller = RunController(
        session_id=session_id,
        workspace=workspace,
        journal=journal,
        models={"lead-model": lead_model, "implementer-model": lead_model},
        workspace_mode="worktree",
        workspace_manager=WorkspaceManager(tmp_path / "skail-data"),
    )

    operation = asyncio.create_task(controller.run_instruction("Run both changes"))
    await asyncio.wait_for(barrier.wait_for_started(2), timeout=5)
    barrier.release("tracked.txt")
    barrier.release("second.txt")
    result = await asyncio.wait_for(operation, timeout=10)

    assert set(barrier.started) == {"tracked.txt", "second.txt"}
    assert all(item.status == "succeeded" for item in result.child_results)
    assert (workspace / "tracked.txt").read_bytes() == b"integrated tracked.txt\n"
    assert (workspace / "second.txt").read_bytes() == b"integrated second.txt\n"


@pytest.mark.asyncio
async def test_two_plan_writers_checkpoint_and_evidence_only_revision_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _repository(tmp_path)
    journal = _journal(tmp_path / "state")
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id),
        title="Two writers and a final checkpoint",
        created_at=datetime.now(UTC),
    )
    criterion = "Write assigned source and test files with runtime-readable evidence."
    outputs = {
        "parser": {
            "src/live_fixture/parser.py": (
                b"def parse_record(line):\n"
                b"    key, value = line.split('=', 1)\n"
                b"    return key, value\n"
            ),
            "tests/test_parser.py": (
                b"from live_fixture.parser import parse_record\n\n"
                b"def test_parser_splits_only_once():\n"
                b"    assert parse_record('name=one=two') == ('name', 'one=two')\n"
            ),
        },
        "report": {
            "src/live_fixture/report.py": (
                b"def render_report(title, rows):\n"
                b"    return title + '\\n' + '\\n'.join(rows)\n"
            ),
            "tests/test_report.py": (
                b"from live_fixture.report import render_report\n\n"
                b"def test_report_keeps_title_and_rows():\n"
                b"    assert render_report('Daily', ['one', 'two']) == 'Daily\\none\\ntwo'\n"
            ),
        },
    }
    digests = {
        path: hashlib.sha256(content).hexdigest()
        for files in outputs.values()
        for path, content in files.items()
    }
    evidence_refs = ["plan-node:parser:succeeded"]
    evidence_refs.extend(
        f"file:{path}:{digests[path]}" for path in outputs["parser"]
    )
    evidence_refs.append("plan-node:report:succeeded")
    evidence_refs.extend(
        f"file:{path}:{digests[path]}" for path in outputs["report"]
    )

    plan = {
        "schema_version": 1,
        "policy_version": "adaptive-v1",
        "revision": 1,
        "nodes": [
            {
                "local_id": local_id,
                "kind": "agent",
                "objective": f"Implement the {local_id} module and focused test file",
                "acceptance_criteria": [criterion],
                "effect_scope": "workspace_write",
                "resource_scopes": list(files),
                "task_features": {"profile": "implementer"},
            }
            for local_id, files in outputs.items()
        ]
        + [
            {
                "local_id": "integrate",
                "kind": "checkpoint",
                "objective": "Accept the two completed writer results",
                "depends_on": ["parser", "report"],
                "effect_scope": "read",
            }
        ],
    }
    revised_plan = {**plan, "revision": 2}
    barrier = AsyncStartBarrier()
    started: list[str] = []

    class Writer:
        def __init__(self, root: Path, task_id: str, local_id: str) -> None:
            self.root = root
            self.task_id = task_id
            self.local_id = local_id

        async def ainvoke(self, state) -> dict[str, object]:
            del state
            started.append(self.local_id)
            await barrier.worker(self.local_id)
            artifacts = []
            for path, content in outputs[self.local_id].items():
                target = self.root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                artifacts.append(
                    ArtifactRef(kind="file", path=path, digest=digests[path])
                )
            result = TaskResult(
                task_id=self.task_id,
                status="succeeded",
                summary=f"Implemented and returned file digests for {self.local_id}.",
                artifacts=tuple(artifacts),
                changed_paths=tuple(outputs[self.local_id]),
                verification=(
                    VerificationResult(
                        criterion=criterion,
                        passed=True,
                        evidence="The scoped files were written; test execution is operator-owned.",
                        evidence_ref=artifacts[0],
                    ),
                ),
            )
            return {"messages": [AIMessage(content=result.model_dump_json())]}

    def build_child(*args, **kwargs):
        del args
        allowed = tuple(kwargs["allowed_write_paths"])
        local_id = "parser" if "src/live_fixture/parser.py" in allowed else "report"
        return Writer(kwargs["workspace"], kwargs["task_id"], local_id)

    monkeypatch.setattr("skail.runtime.run_controller.build_default_agent", build_child)
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        {
                            "mode": "planned",
                            "objective": "Implement parser and report independently",
                            "reason": "The two scoped changes can run concurrently.",
                            "plan": plan,
                        },
                        "admit-two-writers",
                    )
                ]
            ),
            AIMessage(content="The two admitted writers are running."),
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        {
                            "mode": "planned",
                            "objective": "Accept both completed writer results",
                            "reason": (
                                "Both scoped results and their runtime file digests are present."
                            ),
                            "plan": revised_plan,
                            "revision": {
                                "expected_revision": 1,
                                "added_nodes": [],
                                "replaced_local_ids": [],
                                "cancelled_local_ids": [],
                                "justification": "All planned implementation work is complete.",
                                "evidence_refs": evidence_refs,
                            },
                        },
                        "ack-two-writer-checkpoint",
                    )
                ]
            ),
            AIMessage(content="Both implementations were integrated for independent testing."),
            AIMessage(content="The queued read-only follow-up ran after integration."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=workspace,
        journal=journal,
        models={"lead-model": lead_model, "implementer-model": lead_model},
        profile_models={"implementer": "implementer-model"},
        workspace_mode="worktree",
        workspace_manager=WorkspaceManager(tmp_path / "skail-data"),
    )

    app = SkailApp(controller=controller, session_id=session_id)
    queued = "After integration, summarize which modules changed. Do not edit files."
    async with app.run_test(size=(120, 40)) as pilot:
        composer = app.query_one("#composer-input", ComposerTextArea)
        composer.text = "Implement the two independent fixture modules"
        await pilot.press("enter")
        await asyncio.wait_for(barrier.wait_for_started(2), timeout=10)
        assert set(started) == {"parser", "report"}
        composer.text = queued
        await pilot.press("ctrl+enter")
        await pilot.pause()
        assert app.projection.queue == [queued]
        barrier.release("parser")
        barrier.release("report")
        for _ in range(200):
            await pilot.pause(0.05)
            snapshot = journal.get_session_snapshot(str(session_id))
            if (
                len(snapshot.runs) == 2
                and snapshot.runs[-1].status == "completed"
                and not app._run_active
                and not app.projection.queue
            ):
                break

    final_snapshot = journal.get_session_snapshot(str(session_id))
    checkpoint_payloads = []
    for call in lead_model.calls:
        for message in call:
            if not isinstance(message.content, str):
                continue
            try:
                payload = json.loads(message.content)
            except json.JSONDecodeError:
                continue
            if payload.get("type") == "skail.plan_checkpoint":
                checkpoint_payloads.append(payload)
    checkpoint_payloads = list(
        {json.dumps(payload, sort_keys=True): payload for payload in checkpoint_payloads}.values()
    )
    assert len(checkpoint_payloads) == 1
    assert checkpoint_payloads[0]["next_revision"] == 2
    decision_example = checkpoint_payloads[0]["evidence_only_decision_example"]
    assert {key: value for key, value in decision_example.items() if key != "plan"} == {
        "mode": "planned",
        "objective": "Acknowledge the completed plan checkpoint.",
        "constraints": [],
        "reason": "All planned implementation work is complete; preserve the existing nodes.",
        "revision": {
            "expected_revision": 1,
            "added_nodes": [],
            "replaced_local_ids": [],
            "cancelled_local_ids": [],
            "justification": "No plan changes are needed after reviewing accepted results.",
            "evidence_refs": evidence_refs,
        },
    }
    expected_plan = ExecutionPlan.model_validate(revised_plan)
    assert decision_example["plan"] == expected_plan.model_dump(mode="json")
    validated_example = ExecutionDecision.model_validate(decision_example)
    assert validated_example.plan == expected_plan
    assert "evidence_only_decision_example" in checkpoint_payloads[0]["instruction"]
    assert "Do not omit revision metadata." in checkpoint_payloads[0]["instruction"]
    assert len(final_snapshot.runs) == 2
    assert final_snapshot.runs[0].status == "completed"
    assert final_snapshot.runs[1].status == "completed"
    first_run_id = final_snapshot.runs[0].run_id
    first_tasks = {
        task.task_id: task for task in final_snapshot.tasks if task.run_id == first_run_id
    }
    first_attempts = [
        attempt for attempt in final_snapshot.attempts if attempt.task_id in first_tasks
    ]
    assert len(first_tasks) == 3
    assert len(first_attempts) == 3
    assert all(task.status is TaskStatus.SUCCEEDED for task in first_tasks.values())
    assert set(started) == {"parser", "report"}
    assert (workspace / "src/live_fixture/parser.py").read_bytes() == outputs["parser"][
        "src/live_fixture/parser.py"
    ]
    assert (workspace / "tests/test_report.py").read_bytes() == outputs["report"][
        "tests/test_report.py"
    ]
    persisted = journal.plans_for_run(first_run_id)[0]
    assert persisted.plan.revision == 2
    assert persisted.node_states == {
        "parser": PlanNodeState.SUCCEEDED,
        "report": PlanNodeState.SUCCEEDED,
        "integrate": PlanNodeState.SUCCEEDED,
    }
    child_task_ids = {
        journal.plan_node_task_binding(persisted.node_ids[local_id]).task_id
        for local_id in ("parser", "report")
    }
    with sqlite3.connect(journal.path) as connection:
        result_rows = connection.execute(
            "SELECT task_id,payload_json FROM task_results WHERE task_id IN (?,?)",
            tuple(sorted(child_task_ids)),
        ).fetchall()
    child_results = {task_id: json.loads(payload) for task_id, payload in result_rows}
    assert len(child_results) == 2
    assert all(result["status"] == "succeeded" for result in child_results.values())
    assert all(
        result["verification"][0]["evidence_ref"]["digest"]
        for result in child_results.values()
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, (str(workspace / "src"), environment.get("PYTHONPATH", "")))
    )
    focused = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_parser.py", "tests/test_report.py"],
        cwd=workspace,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )
    assert focused.returncode == 0, focused.stdout + focused.stderr
    assert "2 passed" in focused.stdout
    change_sets = journal.get_session_snapshot(str(session_id)).changesets
    assert [record.status for record in change_sets] == [
        "integrated",
        "integrated",
    ]
    assert len(
        [
            item
            for item in app.projection.transcript_items
            if item.role == "user" and item.content == queued
        ]
    ) == 1
    assert len(
        [
            item
            for item in app.projection.transcript_items
            if item.role == "lead"
            and item.content == "The queued read-only follow-up ran after integration."
        ]
    ) == 1


@pytest.mark.asyncio
async def test_delegation_off_removes_task_tool_and_forces_direct_work(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Delegation off", created_at=datetime.now(UTC)
    )

    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[AIMessage(content="I worked directly because task tool is unavailable.")],
    )

    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model},
    )

    result = await controller.run_instruction(
        "Try to delegate", controls=LeadControls(delegation="off")
    )

    # In "off" mode, the task tool is not registered on the lead agent
    assert "task" not in lead_model.bound_tool_names
    assert "worked directly" in result.output
    assert len(result.child_results) == 0


@pytest.mark.asyncio
async def test_delegation_off_rejects_a_hallucinated_task_without_admission(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Delegation off task", created_at=datetime.now(UTC)
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    ("execution_decision", _direct_decision("Bounded work"), "decision-1"),
                    (
                        "task",
                        {"description": "Do not admit", "subagent_type": "implementer"},
                        "task-1",
                    ),
                ]
            ),
            AIMessage(content="I completed the bounded work directly."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model},
    )

    await controller.run_instruction(
        "Do this directly", controls=LeadControls(delegation="off")
    )

    snapshot = journal.get_session_snapshot(str(session_id))
    assert len(snapshot.tasks) == 1  # The lead task only.
    assert len(snapshot.attempts) == 1


@pytest.mark.asyncio
async def test_task_before_decision_is_not_admitted_or_assigned(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Task before decision", created_at=datetime.now(UTC)
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "task",
                        {"description": "Do not admit", "subagent_type": "implementer"},
                        "task-1",
                    ),
                    ("execution_decision", _direct_decision("Bounded work"), "decision-1"),
                ]
            ),
            AIMessage(content="The task was rejected before admission."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model},
    )

    await controller.run_instruction("Do bounded work")

    snapshot = journal.get_session_snapshot(str(session_id))
    assert len(snapshot.tasks) == 1  # The lead task only.
    assert len(snapshot.attempts) == 1


@pytest.mark.asyncio
async def test_read_only_controls_reject_write_capable_task_before_admission(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Read-only task", created_at=datetime.now(UTC)
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    ("execution_decision", _direct_decision("Inspect only"), "decision-1"),
                    (
                        "task",
                        {"description": "Modify a file", "subagent_type": "implementer"},
                        "task-1",
                    ),
                ]
            ),
            AIMessage(content="The write-capable task was rejected."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model},
    )

    await controller.run_instruction(
        "Inspect only", controls=LeadControls(write_allowed=False)
    )

    snapshot = journal.get_session_snapshot(str(session_id))
    assert len(snapshot.tasks) == 1  # The lead task only.
    assert len(snapshot.attempts) == 1


@pytest.mark.asyncio
async def test_explicit_plan_does_not_allow_task_to_bypass_plan_admission(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Explicit plan task", created_at=datetime.now(UTC)
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        {
                            "mode": "planned",
                            "objective": "Make a bounded change",
                            "constraints": [],
                            "reason": "The work has explicit dependencies.",
                            "plan": {
                                "schema_version": 1,
                                "policy_version": "adaptive-v1",
                                "revision": 1,
                                "nodes": [
                                    {
                                        "local_id": "implement",
                                        "kind": "agent",
                                        "objective": "Make the bounded change",
                                        "effect_scope": "workspace_write",
                                    }
                                ],
                            },
                        },
                        "decision-1",
                    ),
                    (
                        "task",
                        {"description": "Bypass the plan", "subagent_type": "implementer"},
                        "task-1",
                    ),
                ]
            ),
            AIMessage(content="The plan was recorded for the coordinator."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model},
    )

    result = await controller.run_instruction("Make a bounded change")

    snapshot = journal.get_session_snapshot(str(session_id))
    assert len(journal.plans_for_run(str(result.run_id))) == 1
    assert len(snapshot.tasks) == 2  # Lead plus the admitted plan node, never the bypass call.
    assert len(snapshot.attempts) == 3  # The admitted node may use its bounded retry.


@pytest.mark.asyncio
async def test_planned_ready_agent_nodes_use_the_admitted_child_lifecycle(tmp_path: Path) -> None:
    evidence_path = tmp_path / "planned-evidence.txt"
    evidence_path.write_text("planned dispatch evidence\n", encoding="utf-8")
    evidence_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Planned agent dispatch", created_at=datetime.now(UTC)
    )
    child_model = ScriptedChatModel(
        model_name="implementer-model",
        responses=[
            _child_success("first complete", evidence_digest),
            _child_success("second complete", evidence_digest),
            _child_success("dependent complete", evidence_digest),
        ],
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [("execution_decision", _planned_decision(), "decision-1")]
            ),
            AIMessage(content="The planned work has been dispatched."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model, "implementer-model": child_model},
        profile_models={"implementer": "implementer-model"},
    )

    result = await controller.run_instruction("Inspect two independent files")

    plan = journal.plans_for_run(str(result.run_id))[0]
    assert len(child_model.calls) == 3
    assert [child.status for child in result.child_results] == [
        "succeeded",
        "succeeded",
        "succeeded",
    ]
    assert plan.node_states == {
        "first": PlanNodeState.SUCCEEDED,
        "second": PlanNodeState.SUCCEEDED,
        "after_first": PlanNodeState.SUCCEEDED,
    }
    snapshot = journal.get_session_snapshot(str(session_id))
    assert len(snapshot.tasks) == 4  # Lead plus three plan-owned child tasks.
    assert len(snapshot.attempts) == 4
    bindings = [
        journal.plan_node_task_binding(plan.node_ids[local_id])
        for local_id in ("first", "second", "after_first")
    ]
    assert {binding.task_id for binding in bindings if binding is not None} == {
        str(child.task_id) for child in result.child_results
    }
    assert {binding.attempt_id for binding in bindings if binding is not None} <= {
        attempt.attempt_id for attempt in snapshot.attempts
    }


@pytest.mark.asyncio
async def test_two_explorers_revision_then_scoped_writer_passes_operator_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _repository(tmp_path)
    parser_path = workspace / "src/live_fixture/parser.py"
    parser_path.parent.mkdir(parents=True)
    parser_path.write_text(
        "def parse_records(text, *, strict=False):\n"
        "    raise NotImplementedError\n",
        encoding="utf-8",
    )
    test_path = workspace / "tests/test_parser.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "from live_fixture.parser import parse_records\n\n"
        "def test_strict_split_preserves_equals_in_value():\n"
        "    assert parse_records('key=value=tail', strict=True) == [('key', 'value=tail')]\n\n"
        "def test_permissive_mode_ignores_invalid_lines():\n"
        "    assert parse_records('invalid', strict=False) == []\n",
        encoding="utf-8",
    )
    _git(workspace, "add", "src/live_fixture/parser.py", "tests/test_parser.py")
    _git(workspace, "commit", "-m", "Add strict parser fixture")
    journal = _journal(tmp_path / "state")
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id),
        title="Two discovery reports then parser implementation",
        created_at=datetime.now(UTC),
    )
    discovery_criterion = "Return source-backed parser findings with path:line evidence."
    write_criterion = "Implement strict parsing while preserving permissive behavior."
    findings = "src/live_fixture/parser.py:1; tests/test_parser.py:1"
    explorers = ScriptedChatModel(
        model_name="explorer-model",
        responses=[
            AIMessage(
                content=json.dumps(
                    {
                        "status": "succeeded",
                        "summary": "The parser is a stub and focused tests cover strict behavior.",
                        "verification": [
                            {
                                "criterion": discovery_criterion,
                                "passed": True,
                                "evidence": findings,
                            }
                        ],
                    }
                )
            ),
            AIMessage(
                content=json.dumps(
                    {
                        "status": "succeeded",
                        "summary": "The existing tests cover strict and permissive behavior.",
                        "verification": [
                            {
                                "criterion": discovery_criterion,
                                "passed": True,
                                "evidence": findings,
                            }
                        ],
                    }
                )
            ),
        ],
    )
    implementation = (
        "def parse_records(text, *, strict=False):\n"
        "    records = []\n"
        "    for line in text.splitlines():\n"
        "        if not line.strip() or '=' not in line:\n"
        "            if strict and line.strip():\n"
        "                raise ValueError('expected key=value')\n"
        "            continue\n"
        "        key, value = line.split('=', 1)\n"
        "        records.append((key, value))\n"
        "    return records\n"
    )
    implementation_digest = hashlib.sha256(
        implementation.replace("\n", os.linesep).encode()
    ).hexdigest()
    implementer = ScriptedChatModel(
        model_name="implementer-model",
        responses=[
            tool_call_message(
                "write_file",
                {"file_path": "src/live_fixture/parser.py", "content": implementation},
                call_id="write-parser",
            ),
            tool_call_message(
                "file_digest",
                {"file_path": "src/live_fixture/parser.py"},
                call_id="digest-parser",
            ),
            tool_call_message(
                "file_digest",
                {"file_path": "tests/test_parser.py"},
                call_id="digest-parser-tests",
            ),
            AIMessage(
                content=json.dumps(
                    {
                        "status": "succeeded",
                        "summary": "Implemented only the scoped parser source.",
                        "artifacts": [
                            {
                                "kind": "file",
                                "path": "src/live_fixture/parser.py",
                                "digest": implementation_digest,
                            },
                            {
                                "kind": "file",
                                "path": "tests/test_parser.py",
                                "digest": hashlib.sha256(test_path.read_bytes()).hexdigest(),
                            },
                        ],
                        "changed_paths": ["src/live_fixture/parser.py"],
                        "verification": [
                            {
                                "criterion": write_criterion,
                                "passed": True,
                                "evidence": (
                                    "The parser source and focused test digests were checked."
                                ),
                                "evidence_ref": {
                                    "kind": "file",
                                    "path": "src/live_fixture/parser.py",
                                    "digest": implementation_digest,
                                },
                            }
                        ],
                    }
                )
            ),
        ],
    )
    initial_plan = {
        "schema_version": 1,
        "policy_version": "adaptive-v1",
        "revision": 1,
        "nodes": [
            {
                "local_id": "audit-cli-api",
                "kind": "agent",
                "objective": "Audit parser implementation and report source-backed findings.",
                "acceptance_criteria": [discovery_criterion],
                "effect_scope": "read",
                "resource_scopes": ["src/live_fixture/parser.py"],
                "task_features": {"profile": "explorer"},
            },
            {
                "local_id": "audit-test-gaps",
                "kind": "agent",
                "objective": "Audit parser tests and report source-backed findings.",
                "acceptance_criteria": [discovery_criterion],
                "effect_scope": "read",
                "resource_scopes": ["tests/test_parser.py"],
                "task_features": {"profile": "explorer"},
            },
            {
                "local_id": "discovery-checkpoint",
                "kind": "checkpoint",
                "objective": "Review both discovery reports before implementation.",
                "depends_on": ["audit-cli-api", "audit-test-gaps"],
                "effect_scope": "read",
            },
        ],
    }
    writer = {
        "local_id": "implement-parser",
        "kind": "agent",
        "objective": "Implement strict parsing and preserve permissive parsing.",
        "acceptance_criteria": [write_criterion],
        "depends_on": ["discovery-checkpoint"],
        "effect_scope": "workspace_write",
        "resource_scopes": ["src/live_fixture/parser.py", "tests/test_parser.py"],
        "task_features": {"profile": "implementer"},
    }
    revised_plan = {
        **initial_plan,
        "revision": 2,
        "nodes": [*initial_plan["nodes"], writer],
    }
    revision_evidence = [
        "plan-node:audit-cli-api:succeeded",
        "plan-node:audit-test-gaps:succeeded",
    ]
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        {
                            "mode": "planned",
                            "objective": "Inspect the parser before choosing implementation work.",
                            "reason": "Two independent read-only audits ground the change.",
                            "plan": initial_plan,
                        },
                        "admit-discovery-plan",
                    )
                ]
            ),
            AIMessage(content="The two read-only audits are running."),
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        {
                            "mode": "planned",
                            "objective": "Implement the evidence-backed strict parser change.",
                            "reason": "Both reports support one scoped parser writer.",
                            "plan": revised_plan,
                            "revision": {
                                "expected_revision": 1,
                                "added_nodes": [writer],
                                "replaced_local_ids": [],
                                "cancelled_local_ids": [],
                                "justification": (
                                    "The reports identify the stub and focused test behavior."
                                ),
                                "evidence_refs": revision_evidence,
                            },
                        },
                        "revise-after-discovery",
                    )
                ]
            ),
            AIMessage(content="The scoped implementation was integrated for independent testing."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=workspace,
        journal=journal,
        models={
            "lead-model": lead_model,
            "explorer-model": explorers,
            "implementer-model": implementer,
        },
        profile_models={"explorer": "explorer-model", "implementer": "implementer-model"},
        workspace_mode="worktree",
        workspace_manager=WorkspaceManager(tmp_path / "skail-data"),
    )

    result = await controller.run_instruction(
        "Use planned execution. Submit two independent read-only discovery agent nodes and a "
        "checkpoint. After the checkpoint, add one implementer with effect_scope workspace_write "
        "scoped to the parser source and test files, then implement strict parsing while "
        "preserving "
        "permissive behavior."
    )

    assert result.status == "completed", (
        result.status,
        result.output,
        [
            (event.type, event.payload)
            for event in journal.events_after(run_id=str(result.run_id))
            if event.type
            in {"tool.failed", "task.blocked", "plan.node_blocked", "diagnostic.error"}
        ],
    )
    persisted = journal.plans_for_run(str(result.run_id))[0]
    assert persisted.plan.revision == 2
    assert persisted.node_states == {
        "audit-cli-api": PlanNodeState.SUCCEEDED,
        "audit-test-gaps": PlanNodeState.SUCCEEDED,
        "discovery-checkpoint": PlanNodeState.SUCCEEDED,
        "implement-parser": PlanNodeState.SUCCEEDED,
    }
    plan_events = journal.events_after(run_id=str(result.run_id))
    revision_sequence = next(
        event.sequence for event in plan_events if event.type == "plan.revised"
    )
    discovery_task_ids = {
        journal.plan_node_task_binding(persisted.node_ids[local_id]).task_id
        for local_id in ("audit-cli-api", "audit-test-gaps")
    }
    assert max(
        event.sequence
        for event in plan_events
        if event.type == "task.succeeded" and str(event.task_id) in discovery_task_ids
    ) < revision_sequence
    writer_task_id = journal.plan_node_task_binding(
        persisted.node_ids["implement-parser"]
    ).task_id
    assert next(
        event.sequence
        for event in plan_events
        if event.type == "task.proposed" and str(event.task_id) == writer_task_id
    ) > revision_sequence
    assert next(
        event.sequence
        for event in plan_events
        if event.type == "plan.node_succeeded"
        and event.payload.node_id == persisted.node_ids["discovery-checkpoint"]
    ) > revision_sequence
    snapshot = journal.get_session_snapshot(str(session_id))
    plan_tasks = [
        task for task in snapshot.tasks if task.run_id == str(result.run_id)
    ]
    assert len(plan_tasks) == 4
    explorer_prompt = "\n".join(str(message.content) for message in explorers.calls[0])
    assert "full workspace-relative path:line" in explorer_prompt
    assert "no leading slash or drive letter" in explorer_prompt
    assert "Do not shorten a source reference to its basename" in explorer_prompt
    assert implementer.bound_tool_names >= {"write_file", "file_digest"}
    assert (workspace / "src/live_fixture/parser.py").read_text(encoding="utf-8") == implementation
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, (str(workspace / "src"), environment.get("PYTHONPATH", "")))
    )
    focused = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_parser.py"],
        cwd=workspace,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )
    assert focused.returncode == 0, focused.stdout + focused.stderr
    assert "2 passed" in focused.stdout


@pytest.mark.asyncio
async def test_discovery_checkpoint_wakes_lead_and_dispatches_revision(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "planned-evidence.txt"
    evidence_path.write_text("planned dispatch evidence\n", encoding="utf-8")
    evidence_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    evidence_ref = f"file:planned-evidence.txt:{evidence_digest}"
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Discovery checkpoint", created_at=datetime.now(UTC)
    )
    child_model = ScriptedChatModel(
        model_name="implementer-model",
        responses=[
            _child_success("discovery complete", evidence_digest),
            _child_success("revised follow-up complete", evidence_digest),
        ],
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [("execution_decision", _discovery_decision(), "decision-1")]
            ),
            AIMessage(content="Discovery is running."),
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        _revised_discovery_decision(evidence_ref),
                        "decision-2",
                    )
                ]
            ),
            AIMessage(content="The evidence-backed revision completed."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model, "implementer-model": child_model},
    )

    result = await controller.run_instruction("Discover, reconsider, then report")

    plan = journal.plans_for_run(str(result.run_id))[0]
    assert result.status == "completed", (
        plan.plan.revision,
        [getattr(message, "content", "") for message in result.messages],
    )
    assert result.output == "The evidence-backed revision completed."
    assert len(lead_model.calls) == 4
    assert len(child_model.calls) == 2
    assert plan.plan.revision == 2
    assert plan.node_states == {
        "inspect": PlanNodeState.SUCCEEDED,
        "reconsider": PlanNodeState.SUCCEEDED,
        "report": PlanNodeState.SUCCEEDED,
    }
    assert [child.summary for child in result.child_results] == [
        "discovery complete",
        "revised follow-up complete",
    ]


@pytest.mark.asyncio
async def test_discovery_checkpoint_rejects_unavailable_revision_evidence(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "planned-evidence.txt"
    evidence_path.write_text("planned dispatch evidence\n", encoding="utf-8")
    evidence_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Invalid revision evidence", created_at=datetime.now(UTC)
    )
    child_model = ScriptedChatModel(
        model_name="implementer-model",
        responses=[_child_success("discovery complete", evidence_digest)],
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [("execution_decision", _discovery_decision(), "decision-1")]
            ),
            AIMessage(content="Discovery is running."),
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        _revised_discovery_decision("artifact:invented"),
                        "decision-2",
                    )
                ]
            ),
            AIMessage(content="I could not admit the revision."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model, "implementer-model": child_model},
    )

    result = await controller.run_instruction("Discover without inventing evidence")

    plan = journal.plans_for_run(str(result.run_id))[0]
    assert result.status == "blocked"
    assert plan.plan.revision == 1
    assert plan.node_states == {
        "inspect": PlanNodeState.SUCCEEDED,
        "reconsider": PlanNodeState.BLOCKED,
    }
    assert any(
        "decision.plan_refused" in str(getattr(message, "content", ""))
        for message in result.messages
    )
    assert len(child_model.calls) == 1


@pytest.mark.asyncio
async def test_planned_agent_nodes_obey_the_shared_child_limit(tmp_path: Path) -> None:
    evidence_path = tmp_path / "planned-evidence.txt"
    evidence_path.write_text("planned dispatch evidence\n", encoding="utf-8")
    evidence_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    barrier = AsyncStartBarrier()

    async def block_child(_: ScriptedChatModel, messages) -> None:
        prompt = str(messages[-1].content)
        label = (
            "first" if "Inspect the first file" in prompt
            else "second" if "Inspect the second file" in prompt
            else "after-first"
        )
        await barrier.worker(label)

    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Planned child cap", created_at=datetime.now(UTC)
    )
    child_model = ScriptedChatModel(
        model_name="implementer-model",
        responses=[
            _child_success("first complete", evidence_digest),
            _child_success("second complete", evidence_digest),
            _child_success("dependent complete", evidence_digest),
        ],
        async_call_hook=block_child,
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [("execution_decision", _planned_decision(), "decision-1")]
            ),
            AIMessage(content="The planned work has been dispatched."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model, "implementer-model": child_model},
        profile_models={"implementer": "implementer-model"},
    )

    run = asyncio.create_task(
        controller.run_instruction(
            "Inspect two independent files", controls=LeadControls(max_children=2)
        )
    )
    await barrier.wait_for_started(2)
    assert set(barrier.started) == {"first", "second"}
    barrier.release("first")
    await asyncio.wait_for(barrier.wait_for_started(3), timeout=1)
    assert barrier.started[-1] == "after-first"
    barrier.release("second")
    barrier.release("after-first")

    result = await run

    assert result.child_peak_active == 2
    assert [child.status for child in result.child_results] == [
        "succeeded", "succeeded", "succeeded"
    ]


@pytest.mark.asyncio
async def test_authorized_tool_node_settles_before_releasing_agent_without_a_model_call(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "planned-evidence.txt"
    evidence_path.write_text("planned dispatch evidence\n", encoding="utf-8")
    evidence_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Plan tool node", created_at=datetime.now(UTC)
    )
    child_model = ScriptedChatModel(
        model_name="implementer-model",
        responses=[_child_success("dependent complete", evidence_digest)],
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    (
                        "execution_decision",
                        {
                            "mode": "planned",
                            "objective": "Run a known local check",
                            "constraints": [],
                            "reason": "The check has one bounded follow-up.",
                            "plan": {
                                "schema_version": 1,
                                "policy_version": "adaptive-v1",
                                "revision": 1,
                                "nodes": [
                                    {
                                        "local_id": "check",
                                        "kind": "tool",
                                        "objective": "Check ruff version",
                                        "effect_scope": "read",
                                        "task_features": {
                                            "tool": "execute",
                                            "command": "python",
                                            "arguments": ["-m", "ruff", "--version"],
                                        },
                                    },
                                    {
                                        "local_id": "report",
                                        "kind": "agent",
                                        "objective": "Report the completed local check",
                                        "depends_on": ["check"],
                                        "effect_scope": "workspace_write",
                                        "task_features": {"profile": "implementer"},
                                    },
                                ],
                            },
                        },
                        "decision-1",
                    )
                ]
            ),
            AIMessage(content="The local tool check and dependent report completed."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model, "implementer-model": child_model},
        profile_models={"implementer": "implementer-model"},
    )

    controller.project_trusted = True
    result = await controller.run_instruction("Run the known check")

    plan = journal.plans_for_run(str(result.run_id))[0]
    assert plan.node_states == {
        "check": PlanNodeState.SUCCEEDED,
        "report": PlanNodeState.SUCCEEDED,
    }
    assert len(child_model.calls) == 1
    assert len(lead_model.calls) == 2


@pytest.mark.asyncio
async def test_tool_and_agent_nodes_share_the_three_child_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path = tmp_path / "planned-evidence.txt"
    evidence_path.write_text("planned dispatch evidence\n", encoding="utf-8")
    evidence_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    barrier = AsyncStartBarrier()
    tool_started = Event()
    release_tool = Event()

    def block_tool(*args, **kwargs) -> ExecutionResult:
        del args, kwargs
        tool_started.set()
        assert release_tool.wait(timeout=2)
        return ExecutionResult("completed", returncode=0)

    monkeypatch.setattr(ExecutionPolicy, "run", block_tool)

    async def block_child(model: ScriptedChatModel, _) -> None:
        await barrier.worker(f"agent-{len(model.calls)}")

    decision = _planned_decision()
    plan = decision["plan"]
    assert isinstance(plan, dict)
    nodes = plan["nodes"]
    assert isinstance(nodes, list)
    nodes.append(
        {
            "local_id": "tool",
            "kind": "tool",
            "objective": "Run the bounded local check",
            "effect_scope": "read",
            "task_features": {"tool": "execute", "command": "python", "arguments": []},
        }
    )
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Mixed child cap", created_at=datetime.now(UTC)
    )
    child_model = ScriptedChatModel(
        model_name="implementer-model",
        responses=[
            _child_success("first complete", evidence_digest),
            _child_success("second complete", evidence_digest),
            _child_success("dependent complete", evidence_digest),
        ],
        async_call_hook=block_child,
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message([("execution_decision", decision, "decision-1")]),
            AIMessage(content="Mixed work completed."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model, "implementer-model": child_model},
        project_trusted=True,
    )
    run = asyncio.create_task(controller.run_instruction("Run mixed planned work"))

    assert await asyncio.to_thread(tool_started.wait, 3)
    await barrier.wait_for_started(2)
    release_tool.set()
    for agent in barrier.started:
        barrier.release(agent)
    await barrier.wait_for_started(3)
    barrier.release(barrier.started[-1])

    result = await run

    assert result.child_peak_active == 3


@pytest.mark.asyncio
async def test_unverified_agent_success_does_not_release_its_plan_dependent(tmp_path: Path) -> None:
    decision = _planned_decision()
    plan_payload = decision["plan"]
    assert isinstance(plan_payload, dict)
    nodes = plan_payload["nodes"]
    assert isinstance(nodes, list)
    nodes[:] = [nodes[0], nodes[2]]
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Unverified planned result", created_at=datetime.now(UTC)
    )
    child_model = ScriptedChatModel(
        model_name="implementer-model",
        responses=[
            AIMessage(content='{"status":"succeeded","summary":"No evidence."}'),
            AIMessage(content='{"status":"succeeded","summary":"Still no evidence."}'),
        ],
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message([("execution_decision", decision, "decision-1")]),
            AIMessage(content="The unverified result was retained as a failure."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model, "implementer-model": child_model},
    )

    result = await controller.run_instruction("Run an unverified plan")

    plan = journal.plans_for_run(str(result.run_id))[0]
    assert plan.node_states == {
        "first": PlanNodeState.BLOCKED,
        "after_first": PlanNodeState.BLOCKED,
    }
    assert len(child_model.calls) == 1
    assert result.status == "blocked"
    snapshot = journal.get_session_snapshot(str(session_id))
    assert snapshot.runs[0].status == "blocked"
    assert "run.completed" not in {event.type for event in snapshot.events}
    assert "run.blocked" in {event.type for event in snapshot.events}


@pytest.mark.asyncio
async def test_cancelling_planned_work_marks_inflight_nodes_terminal(tmp_path: Path) -> None:
    evidence_path = tmp_path / "planned-evidence.txt"
    evidence_path.write_text("planned dispatch evidence\n", encoding="utf-8")
    evidence_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    barrier = AsyncStartBarrier()

    async def block_child(_: ScriptedChatModel, messages) -> None:
        prompt = str(messages[-1].content)
        await barrier.worker("first" if "Inspect the first file" in prompt else "second")

    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Cancel planned work", created_at=datetime.now(UTC)
    )
    child_model = ScriptedChatModel(
        model_name="implementer-model",
        responses=[
            _child_success("first complete", evidence_digest),
            _child_success("second complete", evidence_digest),
        ],
        async_call_hook=block_child,
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [("execution_decision", _planned_decision(), "decision-1")]
            ),
            AIMessage(content="The planned work has been dispatched."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model, "implementer-model": child_model},
    )
    run = asyncio.create_task(controller.run_instruction("Cancel planned work"))
    await barrier.wait_for_started(2)
    run.cancel()

    with pytest.raises(asyncio.CancelledError):
        await run

    snapshot = journal.get_session_snapshot(str(session_id))
    plan = journal.plans_for_run(snapshot.runs[0].run_id)[0]
    assert plan.node_states == {
        "first": PlanNodeState.CANCELLED,
        "second": PlanNodeState.CANCELLED,
        "after_first": PlanNodeState.BLOCKED,
    }
    assert snapshot.runs[0].status == "cancelled"
    lead_task = next(task for task in snapshot.tasks if task.description == "Cancel planned work")
    assert lead_task.status is TaskStatus.RETURNED_TO_LEAD
    lead_attempt = next(
        attempt for attempt in snapshot.attempts if attempt.task_id == lead_task.task_id
    )
    assert lead_attempt.status is AttemptStatus.INTERRUPTED


@pytest.mark.asyncio
async def test_cancelling_planned_work_terminalizes_unlaunched_task_rows(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "planned-evidence.txt"
    evidence_path.write_text("planned dispatch evidence\n", encoding="utf-8")
    evidence_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    barrier = AsyncStartBarrier()

    async def block_child(_: ScriptedChatModel, messages) -> None:
        prompt = str(messages[-1].content)
        label = "first" if "Inspect the first file" in prompt else "second"
        await barrier.worker(label)

    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Cancel queued plan work", created_at=datetime.now(UTC)
    )
    child_model = ScriptedChatModel(
        model_name="implementer-model",
        responses=[
            _child_success("first complete", evidence_digest),
            _child_success("second complete", evidence_digest),
        ],
        async_call_hook=block_child,
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [("execution_decision", _planned_decision(), "decision-1")]
            ),
            AIMessage(content="The planned work has been dispatched."),
        ],
    )
    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model, "implementer-model": child_model},
    )
    run = asyncio.create_task(
        controller.run_instruction(
            "Cancel queued plan work", controls=LeadControls(max_children=1)
        )
    )
    await barrier.wait_for_started(1)
    assert len(barrier.started) == 1
    run.cancel()

    with pytest.raises(asyncio.CancelledError):
        await run

    snapshot = journal.get_session_snapshot(str(session_id))
    run_id = snapshot.runs[0].run_id
    child_tasks = {
        task.description: task
        for task in snapshot.tasks
        if task.run_id == run_id and task.description.startswith("Inspect the ")
    }
    started_label = barrier.started[0]
    started_description = f"Inspect the {started_label} file"
    unstarted_label = ({"first", "second"} - {started_label}).pop()
    unstarted_description = f"Inspect the {unstarted_label} file"
    assert child_tasks[started_description].status is TaskStatus.CANCELLED
    assert child_tasks[unstarted_description].status is TaskStatus.CANCELLED
    attempts = {attempt.task_id: attempt for attempt in snapshot.attempts}
    assert attempts[child_tasks[started_description].task_id].status is AttemptStatus.CANCELLED
    assert attempts[child_tasks[unstarted_description].task_id].status is AttemptStatus.CANCELLED


@pytest.mark.asyncio
async def test_delegation_ask_blocks_when_unapproved(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id),
        title="Delegation ask unapproved",
        created_at=datetime.now(UTC),
    )

    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    ("execution_decision", _direct_decision("Perform work"), "decision-1"),
                    (
                        "task",
                        {"description": "Perform work", "subagent_type": "implementer"},
                        "task-1",
                    ),
                ]
            ),
            AIMessage(content="Delegation was blocked by user approval requirement."),
        ],
    )

    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model},
    )

    result = await controller.run_instruction(
        "Delegate with ask",
        controls=LeadControls(delegation="ask"),
        delegation_approved=False,
    )

    assert "task" in lead_model.bound_tool_names
    # Child was blocked
    assert "blocked by user approval" in result.output


@pytest.mark.asyncio
async def test_delegation_ask_executes_when_approved(tmp_path: Path) -> None:
    (tmp_path / "approved.txt").write_text("approved evidence\n", encoding="utf-8")
    approved_digest = hashlib.sha256((tmp_path / "approved.txt").read_bytes()).hexdigest()
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Delegation ask approved", created_at=datetime.now(UTC)
    )

    child_model = ScriptedChatModel(
        model_name="implementer-model",
        responses=[
            tool_call_message(
                "read_file", {"file_path": "approved.txt"}, call_id="approved-read"
            ),
            AIMessage(
                content=(
                    '{"status":"succeeded","summary":"Approved child output",'
                    '"verification":[{"criterion":"Provide evidence for the completed task",'
                    '"passed":true,"evidence":"approved.txt digest",'
                    '"evidence_ref":{"kind":"file","path":"approved.txt",'
                    f'"digest":"{approved_digest}"}}}}]}}'
                )
            )
        ],
    )
    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    ("execution_decision", _direct_decision("Approved work"), "decision-1"),
                    (
                        "task",
                        {"description": "Approved work", "subagent_type": "implementer"},
                        "task-1",
                    ),
                ]
            ),
            AIMessage(content="Approved delegation completed successfully."),
        ],
    )

    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model, "implementer-model": child_model},
    )

    result = await controller.run_instruction(
        "Delegate with approved ask",
        controls=LeadControls(delegation="ask"),
        delegation_approved=True,
    )

    assert "Approved delegation completed" in result.output
    assert len(result.child_results) == 1
    assert result.child_results[0].verification[0].evidence_ref is not None
    assert controller._validate_evidence_ref(
        result.child_results[0].verification[0].evidence_ref
    )
    assert result.child_results[0].status == "succeeded", result.child_results[0]
    plans = journal.plans_for_run(str(result.run_id))
    assert len(plans) == 1
    assert plans[0].node_states == {"compat-task-1": PlanNodeState.SUCCEEDED}


@pytest.mark.asyncio
async def test_write_allowed_false_removes_mutating_tools(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Write disallowed", created_at=datetime.now(UTC)
    )

    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[AIMessage(content="Read-only mode.")],
    )

    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model},
    )

    await controller.run_instruction(
        "Read only", controls=LeadControls(write_allowed=False)
    )

    assert {"write_file", "edit_file", "execute"}.isdisjoint(lead_model.bound_tool_names)


@pytest.mark.asyncio
async def test_returned_child_failure_is_synthesized_once_without_looping(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    session_id = new_session_id()
    journal.create_session(
        session_id=str(session_id), title="Failure synthesis", created_at=datetime.now(UTC)
    )

    # Simulated child failure returned to lead
    def failing_child_assigner(spec, number, excluded):
        return None  # Will be overridden in execute

    lead_model = ScriptedChatModel(
        model_name="lead-model",
        responses=[
            parallel_tool_call_message(
                [
                    ("execution_decision", _direct_decision("Impossible task"), "decision-1"),
                    (
                        "task",
                        {"description": "Impossible task", "subagent_type": "implementer"},
                        "task-1",
                    ),
                ]
            ),
            AIMessage(
                content="The delegated task failed after escalation: synthesizing failure report."
            ),
        ],
    )

    controller = RunController(
        session_id=session_id,
        workspace=tmp_path,
        journal=journal,
        models={"lead-model": lead_model},
    )

    # Force the child subagent execution to return a returned_to_lead result
    async def mock_execute(spec, assignment, packet):
        return TaskResult(
            task_id=spec.task_id,
            status="failed",
            summary="attempt failed",
        )

    result = await controller.run_instruction("Run impossible task")
    assert "synthesizing failure report" in result.output
    # Lead called exactly 2 times (task tool call, then final synthesis); no resubmission loop
    assert len(lead_model.calls) == 2


def _direct_decision(objective: str) -> dict[str, object]:
    return {
        "mode": "direct",
        "objective": objective,
        "constraints": [],
        "reason": "The requested work is bounded.",
    }


def _planned_decision() -> dict[str, object]:
    return {
        "mode": "planned",
        "objective": "Inspect independent files",
        "constraints": ["read only"],
        "reason": "The inspections are independent.",
        "plan": {
            "schema_version": 1,
            "policy_version": "adaptive-v1",
            "revision": 1,
            "nodes": [
                {
                    "local_id": "first",
                    "kind": "agent",
                    "objective": "Inspect the first file",
                    "effect_scope": "read",
                    "task_features": {"profile": "explorer"},
                },
                {
                    "local_id": "second",
                    "kind": "agent",
                    "objective": "Inspect the second file",
                    "effect_scope": "read",
                    "task_features": {"profile": "explorer"},
                },
                {
                    "local_id": "after_first",
                    "kind": "agent",
                    "objective": "Inspect the first result",
                    "depends_on": ["first"],
                    "effect_scope": "read",
                    "task_features": {"profile": "explorer"},
                },
            ],
        },
    }


def _discovery_decision() -> dict[str, object]:
    return {
        "mode": "discovery",
        "objective": "Inspect evidence before choosing the follow-up",
        "constraints": ["read only"],
        "reason": "The follow-up depends on repository evidence.",
        "plan": {
            "schema_version": 1,
            "policy_version": "adaptive-v1",
            "revision": 1,
            "nodes": [
                {
                    "local_id": "inspect",
                    "kind": "agent",
                    "objective": "Inspect the evidence file",
                    "effect_scope": "read",
                    "task_features": {"profile": "explorer"},
                },
                {
                    "local_id": "reconsider",
                    "kind": "checkpoint",
                    "objective": "Revise the plan from inspected evidence",
                    "depends_on": ["inspect"],
                    "effect_scope": "read",
                },
            ],
        },
    }


def _revised_discovery_decision(evidence_ref: str) -> dict[str, object]:
    report = {
        "local_id": "report",
        "kind": "agent",
        "objective": "Report the evidence-backed conclusion",
        "depends_on": ["reconsider"],
        "effect_scope": "read",
        "task_features": {"profile": "explorer"},
    }
    initial = _discovery_decision()
    plan = initial["plan"]
    assert isinstance(plan, dict)
    nodes = plan["nodes"]
    assert isinstance(nodes, list)
    return {
        "mode": "planned",
        "objective": "Report the evidence-backed conclusion",
        "constraints": ["use only recorded discovery evidence"],
        "reason": "The discovery evidence resolved the checkpoint.",
        "plan": {
            **plan,
            "revision": 2,
            "nodes": [*nodes, report],
        },
        "revision": {
            "expected_revision": 1,
            "added_nodes": [report],
            "justification": "The recorded discovery evidence supports the follow-up.",
            "evidence_refs": [evidence_ref],
        },
    }


def _child_success(summary: str, evidence_digest: str) -> AIMessage:
    return AIMessage(
        content=(
            '{"status":"succeeded","summary":"' + summary + '",'
            '"verification":[{"criterion":"dispatch evidence","passed":true,'
            '"evidence":"planned-evidence.txt:1",'
            '"evidence_ref":{"kind":"file","path":"planned-evidence.txt",'
            '"digest":"' + evidence_digest + '"}}]}'
        )
    )
