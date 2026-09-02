from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from rudder.sessions.schema import MIGRATIONS


def apply_migrations(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    applied = {
        row[0] for row in connection.execute("SELECT version FROM schema_migrations")
    }
    for version, script in MIGRATIONS:
        if version in applied:
            continue
        for statement in script.split(";"):
            if statement.strip():
                connection.execute(statement)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (version, datetime.now(UTC).isoformat()),
        )
