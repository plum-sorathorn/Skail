from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from skail.tools.approvals import ApprovalStore


class ActionClass(StrEnum):
    ORDINARY = "ordinary"
    WORKSPACE_MUTATION = "workspace_mutation"
    EXTERNAL = "external"
    PRIVILEGE = "privilege"
    DESTRUCTIVE = "destructive"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CommandRequest:
    executable: str
    arguments: tuple[str, ...]
    cwd: Path
    request_id: str = ""
    session_id: str = ""
    run_id: str = ""
    task_id: str = ""
    action_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "cwd", self.cwd.resolve())
        if not self.request_id:
            object.__setattr__(self, "request_id", str(uuid4()))


@dataclass(frozen=True)
class PolicyResult:
    action_class: ActionClass
    allowed: bool = False
    requires_approval: bool = False
    rejected: bool = False


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class ExecutionSecurityContext:
    trusted_project: bool = False
    workspace_write_allowed: bool = False
    write_lease_held: bool = False


class ExecutionPolicy:
    def __init__(
        self,
        workspace: Path,
        context: ExecutionSecurityContext | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.context = context or ExecutionSecurityContext()

    def evaluate(self, request: CommandRequest) -> PolicyResult:
        try:
            request.cwd.resolve().relative_to(self.workspace)
        except ValueError:
            return PolicyResult(ActionClass.DESTRUCTIVE, rejected=True)
        name = Path(request.executable).name.lower()
        if name in {"sudo", "runas"}:
            return PolicyResult(ActionClass.PRIVILEGE, rejected=True)
        if name in {"rm", "rmdir", "del", "format", "shutdown", "reboot"}:
            return PolicyResult(ActionClass.DESTRUCTIVE, rejected=True)
        # Shell command strings require a parser-specific policy. Keep them structured
        # and approval-worthy rather than claiming an unreliable token inspection.
        if name in {"powershell", "powershell.exe", "pwsh", "cmd", "cmd.exe", "sh", "bash"}:
            return PolicyResult(ActionClass.UNKNOWN, requires_approval=True)
        if name in {"curl", "wget", "ssh", "scp", "gh"}:
            return PolicyResult(ActionClass.EXTERNAL, requires_approval=True)
        if name == "git":
            lowered = tuple(argument.lower() for argument in request.arguments)
            if lowered and lowered[0].startswith("-"):
                return PolicyResult(ActionClass.UNKNOWN, requires_approval=True)
            subcommand = lowered[0] if lowered else ""
            if subcommand == "diff" and "--no-index" in lowered:
                return PolicyResult(ActionClass.UNKNOWN, requires_approval=True)
            if subcommand == "config" and {"--global", "--system"}.intersection(lowered):
                return PolicyResult(ActionClass.EXTERNAL, requires_approval=True)
            if self._contains_unsafe_path(request.arguments[1:]):
                return PolicyResult(ActionClass.UNKNOWN, requires_approval=True)
            if subcommand in {"clean", "reset", "restore"}:
                return PolicyResult(ActionClass.DESTRUCTIVE, rejected=True)
            if subcommand in {"push", "fetch", "pull", "clone"}:
                return PolicyResult(ActionClass.EXTERNAL, requires_approval=True)
            if request.arguments and request.arguments[0] in {
                "status", "diff", "log", "show", "branch", "rev-parse",
            }:
                return PolicyResult(ActionClass.ORDINARY, allowed=True)
            return self._workspace_mutation()
        if name == "rg" and self._contains_unsafe_path(request.arguments):
            return PolicyResult(ActionClass.UNKNOWN, requires_approval=True)
        if name in {"rg", "ruff", "mypy", "pytest"}:
            return self._ordinary_project_command()
        if name in {"python", "python.exe"}:
            safe_modules = {"pytest", "ruff", "mypy", "build"}
            if (
                len(request.arguments) >= 2
                and request.arguments[0] == "-m"
                and request.arguments[1] in safe_modules
            ):
                return self._ordinary_project_command()
            return PolicyResult(ActionClass.UNKNOWN, requires_approval=True)
        safe_subcommands = {
            "cargo": {"build", "check", "test"},
            "dotnet": {"build", "test"},
            "npm": {"test"},
        }
        if name in safe_subcommands:
            if request.arguments and request.arguments[0] in safe_subcommands[name]:
                return self._ordinary_project_command()
            return PolicyResult(ActionClass.UNKNOWN, requires_approval=True)
        return PolicyResult(ActionClass.UNKNOWN, requires_approval=True)

    def _ordinary_project_command(self) -> PolicyResult:
        return PolicyResult(
            ActionClass.ORDINARY,
            allowed=self.context.trusted_project,
            requires_approval=not self.context.trusted_project,
        )

    @staticmethod
    def _contains_unsafe_path(arguments: tuple[str, ...]) -> bool:
        for argument in arguments:
            if argument.startswith("-"):
                continue
            candidate = Path(argument).expanduser()
            if (
                candidate.is_absolute()
                or ".." in candidate.parts
                or argument.startswith("~")
            ):
                return True
        return False

    def _workspace_mutation(self) -> PolicyResult:
        allowed = (
            self.context.trusted_project
            and self.context.workspace_write_allowed
            and self.context.write_lease_held
        )
        return PolicyResult(
            ActionClass.WORKSPACE_MUTATION,
            allowed=allowed,
            requires_approval=not allowed,
        )

    def run(
        self,
        request: CommandRequest,
        *,
        interactive: bool,
        approvals: ApprovalStore | None = None,
    ) -> ExecutionResult:
        decision = self.evaluate(request)
        if decision.rejected:
            return ExecutionResult("rejected")
        if decision.requires_approval:
            if approvals is not None and approvals.is_allowed(request):
                decision = PolicyResult(decision.action_class, allowed=True)
            else:
                return ExecutionResult("approval_required")
        completed = subprocess.run(
            [request.executable, *request.arguments],
            cwd=request.cwd,
            capture_output=True,
            text=True,
            shell=False,
            check=False,
        )
        return ExecutionResult(
            "completed", completed.returncode, completed.stdout, completed.stderr
        )
