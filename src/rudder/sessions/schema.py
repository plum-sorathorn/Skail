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
    (
        2,
        """
        ALTER TABLE budget_reservations ADD COLUMN purpose TEXT NOT NULL DEFAULT 'task_attempt';
        ALTER TABLE usage_records ADD COLUMN reservation_id TEXT
            REFERENCES budget_reservations(reservation_id);
        CREATE UNIQUE INDEX usage_reservation_unique
            ON usage_records(reservation_id) WHERE reservation_id IS NOT NULL;
        CREATE TABLE budget_warning_state (
            run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
            warning_percent TEXT NOT NULL,
            is_above_threshold INTEGER NOT NULL
        );
        """,
    ),
    (
        3,
        """
        ALTER TABLE assignments RENAME TO assignments_v1;
        CREATE TABLE assignments (
            assignment_id TEXT PRIMARY KEY,
            attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id),
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            estimated_cost_usd TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        INSERT INTO assignments SELECT * FROM assignments_v1;
        DROP TABLE assignments_v1;
        """,
    ),
    (
        4,
        """
        CREATE TABLE assignment_batches (
            idempotency_key TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """,
    ),
    (
        5,
        """
        CREATE TABLE assignment_call_usage (
            assignment_id TEXT NOT NULL REFERENCES assignments(assignment_id),
            call_id TEXT NOT NULL,
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            amount_usd TEXT NOT NULL,
            authoritative INTEGER NOT NULL,
            PRIMARY KEY (assignment_id, call_id)
        );
        """,
    ),
    (
        6,
        """
        CREATE TABLE context_packets (
            packet_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(run_id),
            task_id TEXT REFERENCES tasks(task_id),
            attempt_id TEXT REFERENCES attempts(attempt_id),
            payload_json TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        );
        """,
    ),
    (
        7,
        """
        CREATE TABLE provider_calls (
            call_id TEXT PRIMARY KEY,
            assignment_id TEXT NOT NULL REFERENCES assignments(assignment_id),
            attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id),
            execution_key TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            status TEXT NOT NULL,
            input_tokens INTEGER,
            output_tokens INTEGER,
            amount_usd TEXT,
            authority TEXT,
            error_summary TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(assignment_id, ordinal),
            UNIQUE(assignment_id, execution_key)
        );
        CREATE TABLE accounting_reconciliation_failures (
            failure_id TEXT PRIMARY KEY,
            assignment_id TEXT NOT NULL REFERENCES assignments(assignment_id),
            call_id TEXT REFERENCES provider_calls(call_id),
            status TEXT NOT NULL,
            summary TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(assignment_id, call_id)
        );
        """,
    ),
    (
        8,
        """
        CREATE TABLE task_results (
            task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """,
    ),
    (
        9,
        """
        ALTER TABLE runs ADD COLUMN plan_schema_version INTEGER;
        ALTER TABLE runs ADD COLUMN execution_policy_version TEXT;
        CREATE TABLE execution_plans (
            plan_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL UNIQUE REFERENCES runs(run_id),
            schema_version INTEGER NOT NULL,
            policy_version TEXT NOT NULL,
            current_revision INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE plan_nodes (
            node_id TEXT PRIMARY KEY,
            plan_id TEXT NOT NULL REFERENCES execution_plans(plan_id),
            local_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(plan_id, local_id)
        );
        CREATE TABLE plan_revisions (
            plan_id TEXT NOT NULL REFERENCES execution_plans(plan_id),
            revision INTEGER NOT NULL,
            expected_prior_revision INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(plan_id, revision)
        );
        """,
    ),
    (
        10,
        """
        CREATE TABLE plan_node_states (
            node_id TEXT PRIMARY KEY REFERENCES plan_nodes(node_id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """,
    ),
)
