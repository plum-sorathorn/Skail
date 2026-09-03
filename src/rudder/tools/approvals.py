from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from rudder.tools.execution import CommandRequest


class ApprovalChoice(StrEnum):
    ALLOW_ONCE = "allow_once"
    ALLOW_SESSION = "allow_session"
    ALLOW_PROJECT_RULE = "allow_project_rule"
    EDIT = "edit_then_allow"
    REJECT = "reject"


@dataclass(frozen=True)
class ApprovalDecision:
    choice: ApprovalChoice
    request: CommandRequest


class ApprovalStore:
    def __init__(self, path: Path | None = None) -> None:
        self._session: set[tuple[str, tuple[str, ...], str]] = set()
        self._once: set[tuple[str, tuple[str, ...], str]] = set()
        self._path = path
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS command_approvals ("
                    "executable TEXT NOT NULL, arguments TEXT NOT NULL, cwd TEXT NOT NULL, "
                    "scope TEXT NOT NULL, PRIMARY KEY(executable, arguments, cwd, scope))"
                )

    @staticmethod
    def _key(request: CommandRequest) -> tuple[str, tuple[str, ...], str]:
        return request.executable, request.arguments, str(request.cwd)

    def decide(
        self,
        request: CommandRequest,
        choice: ApprovalChoice,
        *,
        edited: tuple[str, tuple[str, ...]] | None = None,
    ) -> ApprovalDecision:
        if choice is ApprovalChoice.EDIT:
            if edited is None:
                raise ValueError("edited action is required")
            request = CommandRequest(edited[0], edited[1], request.cwd, request_id=str(uuid4()))
        elif choice is ApprovalChoice.ALLOW_ONCE:
            self._once.add(self._key(request))
        elif choice is ApprovalChoice.ALLOW_SESSION:
            self._session.add(self._key(request))
            self._persist(request, "session")
        elif choice is ApprovalChoice.ALLOW_PROJECT_RULE:
            self._persist(request, "project")
        return ApprovalDecision(choice, request)

    def is_allowed(self, request: CommandRequest) -> bool:
        key = self._key(request)
        if key in self._once:
            self._once.remove(key)
            return True
        if key in self._session:
            return True
        if self._path is None:
            return False
        executable, arguments, cwd = self._serialized_key(request)
        with sqlite3.connect(self._path) as connection:
            row = connection.execute(
                "SELECT 1 FROM command_approvals WHERE executable=? AND arguments=? "
                "AND cwd=? AND scope IN ('session','project')",
                (executable, arguments, cwd),
            ).fetchone()
        return row is not None

    @staticmethod
    def _serialized_key(request: CommandRequest) -> tuple[str, str, str]:
        import json

        return request.executable, json.dumps(request.arguments), str(request.cwd)

    def _persist(self, request: CommandRequest, scope: str) -> None:
        if self._path is None:
            return
        with sqlite3.connect(self._path) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO command_approvals VALUES (?,?,?,?)",
                (*self._serialized_key(request), scope),
            )
