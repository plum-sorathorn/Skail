from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from skail.domain.security import (
    ProjectTrustLevel,
    TrustAssessment,
    WorkspaceIdentity,
)


@dataclass(frozen=True)
class TrustRecord:
    identity: WorkspaceIdentity
    level: ProjectTrustLevel
    revision: int


class DurableRevocationSignal:
    def __init__(
        self, store: ProjectTrustStore, identity: WorkspaceIdentity, revision: int
    ) -> None:
        self._store = store
        self._identity = identity
        self._revision = revision

    def is_set(self) -> bool:
        record = self._store._record(self._identity.key)
        return (
            record is None
            or record.revision != self._revision
            or record.identity != self._identity
            or record.level is not ProjectTrustLevel.TRUSTED
        )


class ProjectTrustStore:
    """SQLite-backed trust decisions visible across Skail processes."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS trust_records ("
                "workspace_key TEXT PRIMARY KEY, canonical_path TEXT NOT NULL, "
                "device INTEGER NOT NULL, inode INTEGER NOT NULL, level TEXT NOT NULL, "
                "revision INTEGER NOT NULL, updated_at TEXT NOT NULL)"
            )

    def assess(self, identity: WorkspaceIdentity) -> TrustAssessment:
        record = self._record(identity.key)
        if record is None:
            return TrustAssessment(
                level=ProjectTrustLevel.UNTRUSTED,
                requires_prompt=True,
                reason="workspace has no trust decision",
            )
        if record.identity != identity:
            return TrustAssessment(
                level=ProjectTrustLevel.UNTRUSTED,
                requires_prompt=True,
                reason="workspace filesystem identity changed",
            )
        if record.level is ProjectTrustLevel.DENIED:
            return TrustAssessment(
                level=record.level,
                requires_prompt=False,
                reason="workspace trust was denied",
            )
        return TrustAssessment(
            level=record.level,
            requires_prompt=record.level is ProjectTrustLevel.UNTRUSTED,
            reason=f"workspace is {record.level.value}",
        )

    def set_level(
        self, identity: WorkspaceIdentity, level: ProjectTrustLevel
    ) -> TrustAssessment:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT revision FROM trust_records WHERE workspace_key=?", (identity.key,)
            ).fetchone()
            revision = 1 if row is None else int(row[0]) + 1
            connection.execute(
                "INSERT INTO trust_records VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(workspace_key) DO UPDATE SET "
                "canonical_path=excluded.canonical_path,device=excluded.device,"
                "inode=excluded.inode,level=excluded.level,revision=excluded.revision,"
                "updated_at=excluded.updated_at",
                (
                    identity.key,
                    identity.canonical_path,
                    identity.device,
                    identity.inode,
                    level.value,
                    revision,
                    datetime.now(UTC).isoformat(),
                ),
            )
        return self.assess(identity)

    def revocation_signal(self, identity: WorkspaceIdentity) -> DurableRevocationSignal:
        record = self._record(identity.key)
        revision = 0 if record is None else record.revision
        return DurableRevocationSignal(self, identity, revision)

    def _record(self, key: str) -> TrustRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT canonical_path,device,inode,level,revision "
                "FROM trust_records WHERE workspace_key=?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return TrustRecord(
            identity=WorkspaceIdentity(
                canonical_path=row["canonical_path"],
                device=row["device"],
                inode=row["inode"],
            ),
            level=ProjectTrustLevel(row["level"]),
            revision=row["revision"],
        )
