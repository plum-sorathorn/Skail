from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from threading import RLock
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
        self._session: set[tuple[str, str, tuple[str, ...], str]] = set()
        self._once: set[tuple[str, str, str, str, str, tuple[str, ...], str]] = set()
        self._lock = RLock()
        self._path = path
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS command_approvals_v2 ("
                    "session_id TEXT NOT NULL, run_id TEXT NOT NULL, task_id TEXT NOT NULL, "
                    "action_id TEXT NOT NULL, executable TEXT NOT NULL, arguments TEXT NOT NULL, "
                    "cwd TEXT NOT NULL, scope TEXT NOT NULL, consumed INTEGER NOT NULL DEFAULT 0, "
                    "PRIMARY KEY(session_id,run_id,task_id,action_id,executable,arguments,cwd,"
                    "scope))"
                )

    @staticmethod
    def _session_key(request: CommandRequest) -> tuple[str, str, tuple[str, ...], str]:
        return request.session_id, request.executable, request.arguments, str(request.cwd)

    @staticmethod
    def _once_key(request: CommandRequest) -> tuple[str, str, str, str, str, tuple[str, ...], str]:
        return (
            request.session_id, request.run_id, request.task_id, request.action_id,
            request.executable, request.arguments, str(request.cwd),
        )

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
            request = CommandRequest(
                edited[0], edited[1], request.cwd, request_id=str(uuid4()),
                session_id=request.session_id, run_id=request.run_id,
                task_id=request.task_id, action_id=str(uuid4()),
            )
        elif choice is ApprovalChoice.ALLOW_ONCE:
            if self._path is None:
                with self._lock:
                    self._once.add(self._once_key(request))
            else:
                self._persist(request, "once")
        elif choice is ApprovalChoice.ALLOW_SESSION:
            if not request.session_id:
                raise ValueError("session approval requires a session identity")
            with self._lock:
                self._session.add(self._session_key(request))
            self._persist(request, "session")
        elif choice is ApprovalChoice.ALLOW_PROJECT_RULE:
            self._persist(request, "project")
        return ApprovalDecision(choice, request)

    def is_allowed(self, request: CommandRequest) -> bool:
        with self._lock:
            once_key = self._once_key(request)
            if once_key in self._once:
                self._once.remove(once_key)
                return True
            if self._session_key(request) in self._session:
                return True
        if self._path is None:
            return False
        executable, arguments, cwd = self._serialized_key(request)
        with sqlite3.connect(self._path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT scope FROM command_approvals_v2 WHERE session_id IN (?, '') "
                "AND (run_id=? OR run_id='') AND (task_id=? OR task_id='') "
                "AND (action_id=? OR action_id='') AND executable=? AND arguments=? AND cwd=? "
                "AND consumed=0 AND scope IN ('once','session','project') "
                "ORDER BY CASE scope WHEN 'once' THEN 0 WHEN 'session' THEN 1 ELSE 2 END LIMIT 1",
                (request.session_id, request.run_id, request.task_id, request.action_id,
                 executable, arguments, cwd),
            ).fetchone()
            if row is not None and row[0] == "once":
                connection.execute(
                    "UPDATE command_approvals_v2 SET consumed=1 WHERE session_id=? AND run_id=? "
                    "AND task_id=? AND action_id=? AND executable=? AND arguments=? AND cwd=? "
                    "AND scope='once' AND consumed=0",
                    (
                        request.session_id, request.run_id, request.task_id, request.action_id,
                        executable, arguments, cwd,
                    ),
                )
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
                "INSERT OR IGNORE INTO command_approvals_v2 VALUES (?,?,?,?,?,?,?,?,0)",
                (
                    "" if scope == "project" else request.session_id,
                    "" if scope in {"session", "project"} else request.run_id,
                    "" if scope in {"session", "project"} else request.task_id,
                    "" if scope in {"session", "project"} else request.action_id,
                    *self._serialized_key(request), scope,
                ),
            )
