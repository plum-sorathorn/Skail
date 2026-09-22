from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from skail.tools.approvals import ApprovalChoice, ApprovalStore
from skail.tools.execution import (
    ActionClass,
    CommandRequest,
    ExecutionPolicy,
    ExecutionSecurityContext,
)


def test_command_policy_table_and_structured_arguments(tmp_path: Path) -> None:
    policy = ExecutionPolicy(
        tmp_path,
        ExecutionSecurityContext(
            trusted_project=True,
            workspace_write_allowed=True,
            write_lease_held=True,
        ),
    )
    assert (
        policy.evaluate(CommandRequest("python", ("-m", "pytest"), tmp_path)).action_class
        is ActionClass.ORDINARY
    )
    assert policy.evaluate(CommandRequest("git", ("status",), tmp_path)).allowed
    mutation = policy.evaluate(CommandRequest("git", ("commit", "-m", "x"), tmp_path))
    assert mutation.action_class is ActionClass.WORKSPACE_MUTATION
    shell = policy.evaluate(
        CommandRequest("powershell", ("-Command", "Get-ChildItem"), tmp_path)
    )
    assert shell.requires_approval
    assert policy.evaluate(CommandRequest("rm", ("-rf", "."), tmp_path)).rejected
    assert policy.evaluate(CommandRequest("git", ("clean", "-fd"), tmp_path)).rejected
    assert policy.evaluate(CommandRequest("git", ("reset", "--hard"), tmp_path)).rejected
    assert policy.evaluate(CommandRequest("git", ("push",), tmp_path)).requires_approval
    alias = CommandRequest("git", ("-c", "alias.x=!whoami", "x"), tmp_path)
    assert policy.evaluate(alias).requires_approval
    no_index = CommandRequest(
        "git", ("diff", "--no-index", "C:/outside/a", "C:/outside/b"), tmp_path
    )
    assert policy.evaluate(no_index).requires_approval
    global_config = CommandRequest("git", ("config", "--global", "x", "y"), tmp_path)
    assert policy.evaluate(global_config).requires_approval
    outside_rg = CommandRequest("rg", ("TOKEN", str(tmp_path.parent)), tmp_path)
    assert policy.evaluate(outside_rg).requires_approval
    assert policy.evaluate(
        CommandRequest("curl", ("https://example.com",), tmp_path)
    ).requires_approval
    assert policy.evaluate(CommandRequest("unknown-tool", (), tmp_path)).requires_approval
    assert policy.evaluate(CommandRequest("sudo", ("x",), tmp_path)).rejected


def test_edited_approval_creates_a_new_request_and_scopes_are_narrow(tmp_path: Path) -> None:
    path = tmp_path / "approvals.sqlite3"
    store = ApprovalStore(path)
    original = CommandRequest(
        "curl", ("https://bad.invalid",), tmp_path, request_id="old",
        session_id="session-1", run_id="run-1", task_id="task-1", action_id="action-1",
    )
    decision = store.decide(
        original, ApprovalChoice.EDIT, edited=("curl", ("https://example.com",))
    )
    assert decision.request.request_id != "old"
    assert decision.request.arguments == ("https://example.com",)
    store.decide(decision.request, ApprovalChoice.ALLOW_SESSION)
    assert ApprovalStore(path).is_allowed(decision.request)
    other_session = CommandRequest(
        decision.request.executable,
        decision.request.arguments,
        decision.request.cwd,
        session_id="session-2",
        run_id=decision.request.run_id,
        task_id=decision.request.task_id,
        action_id=decision.request.action_id,
    )
    assert not ApprovalStore(path).is_allowed(other_session)
    assert not store.is_allowed(CommandRequest("curl", ("https://other.example",), tmp_path))


def test_non_interactive_approval_returns_without_executing(tmp_path: Path) -> None:
    result = ExecutionPolicy(tmp_path).run(
        CommandRequest("curl", ("https://example.com",), tmp_path), interactive=False
    )
    assert result.status == "approval_required"
    assert result.returncode is None


def test_allow_once_is_consumed_without_broadening_request(tmp_path: Path) -> None:
    request = CommandRequest(
        "git", ("commit", "-m", "safe"), tmp_path,
        session_id="session-1", run_id="run-1", task_id="task-1", action_id="action-1",
    )
    approvals = ApprovalStore(tmp_path / "approvals.sqlite")
    approvals.decide(request, ApprovalChoice.ALLOW_ONCE)
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(lambda _: approvals.is_allowed(request), range(2)))
    assert sorted(outcomes) == [False, True]
    assert not approvals.is_allowed(request)


def test_allow_once_rejects_changed_command_or_action_identity(tmp_path: Path) -> None:
    approvals = ApprovalStore(tmp_path / "approvals.sqlite")
    request = CommandRequest(
        "pwsh", ("-Command", "Write-Output safe"), tmp_path,
        session_id="session-1", run_id="run-1", task_id="lead", action_id="call-1",
    )
    approvals.decide(request, ApprovalChoice.ALLOW_ONCE)

    changed = CommandRequest(
        request.executable, ("-Command", "Write-Output changed"), request.cwd,
        session_id=request.session_id, run_id=request.run_id,
        task_id=request.task_id, action_id=request.action_id,
    )
    replay = CommandRequest(
        request.executable, request.arguments, request.cwd,
        session_id=request.session_id, run_id=request.run_id,
        task_id=request.task_id, action_id="call-2",
    )
    assert not approvals.is_allowed(changed)
    assert not approvals.is_allowed(replay)
    assert approvals.is_allowed(request)
