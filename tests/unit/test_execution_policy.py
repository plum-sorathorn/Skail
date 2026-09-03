from __future__ import annotations

from pathlib import Path

from rudder.tools.approvals import ApprovalChoice, ApprovalStore
from rudder.tools.execution import (
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
    outside_rg = CommandRequest("rg", ("TOKEN", "C:/outside"), tmp_path)
    assert policy.evaluate(outside_rg).requires_approval
    assert policy.evaluate(
        CommandRequest("curl", ("https://example.com",), tmp_path)
    ).requires_approval
    assert policy.evaluate(CommandRequest("unknown-tool", (), tmp_path)).requires_approval
    assert policy.evaluate(CommandRequest("sudo", ("x",), tmp_path)).rejected


def test_edited_approval_creates_a_new_request_and_scopes_are_narrow(tmp_path: Path) -> None:
    path = tmp_path / "approvals.sqlite3"
    store = ApprovalStore(path)
    original = CommandRequest("curl", ("https://bad.invalid",), tmp_path, request_id="old")
    decision = store.decide(
        original, ApprovalChoice.EDIT, edited=("curl", ("https://example.com",))
    )
    assert decision.request.request_id != "old"
    assert decision.request.arguments == ("https://example.com",)
    store.decide(decision.request, ApprovalChoice.ALLOW_SESSION)
    assert ApprovalStore(path).is_allowed(decision.request)
    assert not store.is_allowed(CommandRequest("curl", ("https://other.example",), tmp_path))


def test_non_interactive_approval_returns_without_executing(tmp_path: Path) -> None:
    result = ExecutionPolicy(tmp_path).run(
        CommandRequest("curl", ("https://example.com",), tmp_path), interactive=False
    )
    assert result.status == "approval_required"
    assert result.returncode is None


def test_allow_once_is_consumed_without_broadening_request(tmp_path: Path) -> None:
    request = CommandRequest("git", ("commit", "-m", "safe"), tmp_path)
    approvals = ApprovalStore()
    approvals.decide(request, ApprovalChoice.ALLOW_ONCE)
    assert approvals.is_allowed(request)
    assert not approvals.is_allowed(request)
