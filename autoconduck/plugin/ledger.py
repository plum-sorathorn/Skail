"""Plugin ledger — durable event store (SQLite WAL, batched queue)."""

from __future__ import annotations

import asyncio
import collections
import datetime
import json
import logging
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DURABLE_KINDS = frozenset({"session_start", "task_start", "escalation", "terminal_result", "error", "subagent_start", "subagent_stop"})
# Endpoint-facing kinds that are valid but not all durable (non-durable counted only)
ALLOWED_EVENT_KINDS = frozenset({"session_start", "tool_call", "tool_result", "task_start", "task_progress", "task_done", "subagent_start", "subagent_stop"})

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    session_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    data TEXT,
    parent_session_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_parent ON events(parent_session_id);
"""


def _db_path() -> Path:
    from autoconduck.config.paths import run_dir

    return run_dir() / "plugin_ledger.db"


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class PluginLedger:
    """SQLite WAL ledger with bounded in-memory queue and background batch flusher."""

    def __init__(self, db_path: Path | None = None, retention_days: int = 30) -> None:
        self.db_path: Path = Path(db_path) if db_path is not None else _db_path()
        self.retention_days: int = retention_days
        self._queue: collections.deque[dict[str, Any]] = collections.deque(maxlen=1000)
        self._lock = threading.Lock()
        self._counts: dict[str, dict[str, int]] = {}
        self._flush_event = asyncio.Event()
        self._task: asyncio.Task[Any] | None = None
        self._closed = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ensure_db()

    # -- DB setup -------------------------------------------------------
    def _ensure_db(self) -> None:
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.db_path), timeout=5.0)
            try:
                conn.execute("PRAGMA journal_mode=WAL;")
                # Migration check for legacy tables before schema/index creation
                try:
                    columns = [row[1] for row in conn.execute("PRAGMA table_info(events)").fetchall()]
                    if columns and "parent_session_id" not in columns:
                        conn.execute("ALTER TABLE events ADD COLUMN parent_session_id TEXT;")
                except Exception as exc:
                    logger.warning("ledger pre-migration check failed: %s", exc)
                conn.executescript(SCHEMA)
                # Ensure parent_session_id column exists if table was just created or modified
                try:
                    columns = [row[1] for row in conn.execute("PRAGMA table_info(events)").fetchall()]
                    if "parent_session_id" not in columns:
                        conn.execute("ALTER TABLE events ADD COLUMN parent_session_id TEXT;")
                        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_parent ON events(parent_session_id);")
                except Exception as exc:
                    logger.warning("ledger migration failed: %s", exc)
                conn.commit()
                # retention prune on startup
                try:
                    cutoff = (
                        datetime.datetime.now(datetime.timezone.utc)
                        - datetime.timedelta(days=self.retention_days)
                    ).isoformat()
                    conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
                    conn.commit()
                except Exception as exc:
                    logger.warning("ledger retention prune failed: %s", exc)
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("ledger _ensure_db failed: %s", exc)

    # -- Enqueue --------------------------------------------------------
    def enqueue(
        self,
        session_id: str,
        task_id: str,
        kind: str,
        data: Any | None = None,
        parent_session_id: str | None = None,
    ) -> bool:
        """
        Queue a durable event for batch flush.
        Returns True if queued, False if counted-only or dropped.
        Never raises.
        """
        try:
            kind = str(kind)
            # only durable kinds are persisted
            if kind not in DURABLE_KINDS:
                try:
                    with self._lock:
                        sess = self._counts.setdefault(str(session_id), {})
                        sess[kind] = sess.get(kind, 0) + 1
                except Exception:
                    pass
                return False
            # sanitize data: no prompt content by default — ensure small JSON
            payload: str
            try:
                # strip prompt-ish keys if present
                if isinstance(data, dict):
                    safe = {k: v for k, v in data.items() if k not in ("prompt", "content", "raw_prompt")}
                    # truncate string values
                    for k, v in list(safe.items()):
                        if isinstance(v, str) and len(v) > 2000:
                            safe[k] = v[:2000] + "...[truncated]"
                    payload = json.dumps(safe, default=str)
                elif data is None:
                    payload = "{}"
                else:
                    payload = json.dumps({"value": str(data)[:4000]}, default=str)
            except Exception:
                payload = "{}"
            entry: dict[str, Any] = {
                "ts": _utc_now_iso(),
                "session_id": str(session_id),
                "task_id": str(task_id) if task_id else uuid.uuid4().hex[:8],
                "kind": kind,
                "data": payload,
                "parent_session_id": str(parent_session_id) if parent_session_id else None,
            }
            need_signal = False
            with self._lock:
                self._queue.append(entry)
                need_signal = len(self._queue) >= 25
            if need_signal:
                try:
                    if self._loop is not None and self._loop.is_running():
                        self._loop.call_soon_threadsafe(self._flush_event.set)
                    else:
                        try:
                            loop = asyncio.get_running_loop()
                            loop.call_soon(self._flush_event.set)
                        except RuntimeError:
                            pass
                except Exception:
                    pass
            return True
        except Exception as exc:
            logger.warning("ledger enqueue failed: %s", exc)
            return False

    def count_in_memory(self, session_id: str, kind: str) -> None:
        try:
            with self._lock:
                sess = self._counts.setdefault(str(session_id), {})
                sess[kind] = sess.get(kind, 0) + 1
        except Exception:
            pass

    def get_counts(self, session_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            if session_id is not None:
                return dict(self._counts.get(str(session_id), {}))
            return {k: dict(v) for k, v in self._counts.items()}

    # -- Flush ----------------------------------------------------------
    def flush_sync(self) -> int:
        """Synchronously flush queued events to SQLite. Returns rows written."""
        batch: list[dict[str, Any]]
        with self._lock:
            if not self._queue:
                return 0
            batch = list(self._queue)
            self._queue.clear()
        if not batch:
            return 0
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=5.0)
            try:
                conn.execute("PRAGMA journal_mode=WAL;")
                rows = [
                    (
                        e["ts"],
                        e["session_id"],
                        e["task_id"],
                        e["kind"],
                        e["data"],
                        e.get("parent_session_id"),
                    )
                    for e in batch
                ]
                conn.executemany(
                    "INSERT INTO events (ts, session_id, task_id, kind, data, parent_session_id) VALUES (?,?,?,?,?,?)",
                    rows,
                )
                conn.commit()
                return len(rows)
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("ledger flush failed (%d events dropped): %s", len(batch), exc)
            return 0

    async def _flusher(self) -> None:
        while not self._closed:
            try:
                try:
                    await asyncio.wait_for(self._flush_event.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    pass
                self._flush_event.clear()
                # flush on size>=25 or every 2s already handled
                with self._lock:
                    should = len(self._queue) > 0
                if should:
                    await asyncio.to_thread(self.flush_sync)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("ledger flusher error: %s", exc)
                await asyncio.sleep(1.0)

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._closed = False
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
        self._flush_event = asyncio.Event()
        self._task = asyncio.create_task(self._flusher())

    async def stop(self) -> None:
        self._closed = True
        try:
            self._flush_event.set()
        except Exception:
            pass
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=3.0)
            except Exception:
                try:
                    self._task.cancel()
                except Exception:
                    pass
        # final sync flush
        try:
            await asyncio.to_thread(self.flush_sync)
        except Exception:
            try:
                self.flush_sync()
            except Exception:
                pass

    def shutdown_sync(self) -> None:
        self._closed = True
        try:
            self.flush_sync()
        except Exception:
            pass

    # -- Query helpers --------------------------------------------------
    def query_events(
        self, session_id: str | None = None, task_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=5.0)
            try:
                q = "SELECT id, ts, session_id, task_id, kind, data, parent_session_id FROM events"
                conds: list[str] = []
                params: list[Any] = []
                if session_id is not None:
                    conds.append("session_id=?")
                    params.append(str(session_id))
                if task_id is not None:
                    conds.append("task_id=?")
                    params.append(str(task_id))
                if conds:
                    q += " WHERE " + " AND ".join(conds)
                q += " ORDER BY id DESC LIMIT ?"
                params.append(int(limit))
                rows = conn.execute(q, params).fetchall()
                out: list[dict[str, Any]] = []
                for r in rows:
                    try:
                        data = json.loads(r[5]) if r[5] else {}
                    except Exception:
                        data = {"raw": r[5]}
                    out.append(
                        {
                            "id": r[0],
                            "ts": r[1],
                            "session_id": r[2],
                            "task_id": r[3],
                            "kind": r[4],
                            "data": data,
                            "parent_session_id": r[6],
                        }
                    )
                return out
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("ledger query failed: %s", exc)
            return []

    def get_session_activation(self, session_id: str) -> dict[str, Any] | None:
        """Return the latest durable extension activation metadata for a session."""
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=5.0)
            try:
                row = conn.execute(
                    "SELECT data FROM events WHERE session_id=? AND kind='session_start' ORDER BY id DESC LIMIT 1",
                    (str(session_id),),
                ).fetchone()
                if row is None:
                    return None
                try:
                    return json.loads(row[0]) if row[0] else {}
                except Exception:
                    return {"raw": row[0]}
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("ledger session activation query failed: %s", exc)
            return None

    def prune(self) -> int:
        try:
            cutoff = (
                datetime.datetime.now(datetime.timezone.utc)
                - datetime.timedelta(days=self.retention_days)
            ).isoformat()
            conn = sqlite3.connect(str(self.db_path), timeout=5.0)
            try:
                cur = conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
                conn.commit()
                return int(cur.rowcount or 0)
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("ledger prune failed: %s", exc)
            return 0


# Singleton holder
_ledger: PluginLedger | None = None
_ledger_lock = threading.Lock()


def get_ledger() -> PluginLedger:
    global _ledger
    with _ledger_lock:
        if _ledger is not None:
            return _ledger
        try:
            from autoconduck.config.manager import get_config

            cfg = get_config()
            retention = 30
            try:
                retention = int(getattr(getattr(cfg, "plugins", None), "ledger_retention_days", 30))
            except Exception:
                retention = 30
        except Exception:
            retention = 30
        _ledger = PluginLedger(retention_days=retention)
        return _ledger


def reset_ledger_singleton() -> None:
    global _ledger
    with _ledger_lock:
        if _ledger is not None:
            try:
                _ledger.shutdown_sync()
            except Exception:
                pass
        _ledger = None


def ledger_enabled() -> bool:
    try:
        from autoconduck.config.manager import get_config

        cfg = get_config()
        return bool(getattr(getattr(cfg, "plugins", None), "enabled", False))
    except Exception:
        return False
