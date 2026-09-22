from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


class StaleAnswerError(ValueError):
    pass


@dataclass(frozen=True)
class Question:
    question_id: str
    graph_id: str
    task_id: str | None
    prompt: str
    options: tuple[str, ...]
    reason: str
    blocking_scope: str
    status: str
    answer: str | None = None


class QuestionStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS questions ("
                "question_id TEXT PRIMARY KEY, graph_id TEXT NOT NULL, task_id TEXT, "
                "prompt TEXT NOT NULL, options_json TEXT NOT NULL, reason TEXT NOT NULL, "
                "blocking_scope TEXT NOT NULL, status TEXT NOT NULL, answer TEXT, "
                "idempotency_key TEXT NOT NULL UNIQUE)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _question(row: sqlite3.Row) -> Question:
        return Question(
            row["question_id"],
            row["graph_id"],
            row["task_id"],
            row["prompt"],
            tuple(json.loads(row["options_json"])),
            row["reason"],
            row["blocking_scope"],
            row["status"],
            row["answer"],
        )

    def ask(
        self,
        *,
        graph_id: str,
        task_id: str | None,
        prompt: str,
        reason: str,
        blocking_scope: str,
        idempotency_key: str,
        options: tuple[str, ...] = (),
    ) -> Question:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM questions WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO questions VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(uuid4()),
                        graph_id,
                        task_id,
                        prompt,
                        json.dumps(options),
                        reason,
                        blocking_scope,
                        "pending",
                        None,
                        idempotency_key,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM questions WHERE idempotency_key=?", (idempotency_key,)
                ).fetchone()
        assert row is not None
        return self._question(row)

    def pending(self, graph_id: str) -> tuple[Question, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM questions WHERE graph_id=? AND status='pending' ORDER BY rowid",
                (graph_id,),
            ).fetchall()
        return tuple(self._question(row) for row in rows)

    def _transition(
        self, question_id: str, graph_id: str, status: str, answer: str | None
    ) -> Question:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM questions WHERE question_id=?", (question_id,)
            ).fetchone()
            if row is None or row["graph_id"] != graph_id or row["status"] != "pending":
                raise StaleAnswerError("question is invalid, stale, or belongs to another graph")
            options = tuple(json.loads(row["options_json"]))
            if answer is not None and options and answer not in options:
                raise ValueError("answer is not one of the question options")
            connection.execute(
                "UPDATE questions SET status=?,answer=? WHERE question_id=?",
                (status, answer, question_id),
            )
            row = connection.execute(
                "SELECT * FROM questions WHERE question_id=?", (question_id,)
            ).fetchone()
        assert row is not None
        return self._question(row)

    def answer(self, question_id: str, answer: str, *, graph_id: str) -> Question:
        return self._transition(question_id, graph_id, "answered", answer)

    def cancel(self, question_id: str, *, graph_id: str) -> Question:
        return self._transition(question_id, graph_id, "cancelled", None)
