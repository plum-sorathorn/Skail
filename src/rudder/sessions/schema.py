from __future__ import annotations

MIGRATIONS: tuple[tuple[int, str], ...] = (
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(session_id),
            status TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            budget_limit_usd TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(run_id),
            description TEXT NOT NULL,
            status TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS attempts (
            attempt_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(task_id),
            attempt_number INTEGER NOT NULL CHECK (attempt_number IN (1, 2)),
            status TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS assignments (
            assignment_id TEXT PRIMARY KEY,
            attempt_id TEXT NOT NULL UNIQUE REFERENCES attempts(attempt_id),
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            estimated_cost_usd TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS budget_reservations (
            reservation_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(run_id),
            task_id TEXT REFERENCES tasks(task_id),
            amount_usd TEXT NOT NULL,
            status TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS usage_records (
            usage_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(run_id),
            task_id TEXT REFERENCES tasks(task_id),
            amount_usd TEXT NOT NULL,
            authoritative INTEGER NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS approvals (
            approval_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(run_id),
            task_id TEXT REFERENCES tasks(task_id),
            status TEXT NOT NULL,
            question TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(run_id),
            sequence INTEGER NOT NULL,
            envelope_json TEXT NOT NULL,
            UNIQUE(run_id, sequence)
        );
        """,
    ),
)
