"""Session bias store — in-memory floor bump with TTL (turn-based expiry)."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

# Global cap for bias-adjusted floor (above confidence_floor_max)
BIAS_HARD_CAP = 0.75


class SessionBiasStore:
    """Thread-safe in-memory store: session_id -> {floor_bump, expires_at_turn, ts}.

    Hot-path safe: dict lookup only, bounded by threading.Lock, no awaits inside lock.
    Fail-soft: any error -> bump 0.0.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # session_id -> {"bump": float, "expires_at": int, "ts": float}
        self._store: dict[str, dict[str, Any]] = {}
        # session_id -> current turn counter (int)
        self._turns: dict[str, int] = {}

    def apply_escalation(self, session_id: str, bump: float, ttl_turns: int) -> float:
        try:
            sid = str(session_id) if session_id else ""
            if not sid:
                return 0.0
            bump_f = float(bump)
            ttl = int(ttl_turns)
            if ttl <= 0:
                ttl = 1
            # clamp bump to [0, 1]
            if bump_f < 0:
                bump_f = 0.0
            if bump_f > 1.0:
                bump_f = 1.0
            with self._lock:
                cur = int(self._turns.get(sid, 0))
                expires_at = cur + ttl
                self._store[sid] = {"bump": bump_f, "expires_at": expires_at, "ts": time.time()}
                return bump_f
        except Exception as exc:
            logger.warning("bias apply_escalation failed: %s", exc)
            return 0.0

    def get_bump(self, session_id: str | None) -> float:
        try:
            if not session_id:
                return 0.0
            sid = str(session_id)
            with self._lock:
                entry = self._store.get(sid)
                if not entry:
                    return 0.0
                expires_at = int(entry.get("expires_at", 0))
                cur = int(self._turns.get(sid, 0))
                if cur >= expires_at:
                    # expired — evict
                    try:
                        del self._store[sid]
                    except Exception:
                        pass
                    return 0.0
                return float(entry.get("bump", 0.0))
        except Exception as exc:
            logger.warning("bias get_bump failed: %s", exc)
            return 0.0

    def increment_turn(self, session_id: str | None) -> int:
        """Advance turn counter for a session. Returns new turn value."""
        try:
            if not session_id:
                return 0
            sid = str(session_id)
            with self._lock:
                cur = int(self._turns.get(sid, 0)) + 1
                self._turns[sid] = cur
                # opportunistic expiry cleanup
                entry = self._store.get(sid)
                if entry is not None and cur >= int(entry.get("expires_at", 0)):
                    try:
                        del self._store[sid]
                    except Exception:
                        pass
                return cur
        except Exception as exc:
            logger.warning("bias increment_turn failed: %s", exc)
            return 0

    def reset_session(self, session_id: str | None) -> None:
        try:
            if not session_id:
                return
            sid = str(session_id)
            with self._lock:
                self._store.pop(sid, None)
                self._turns.pop(sid, None)
        except Exception as exc:
            logger.warning("bias reset_session failed: %s", exc)

    def clear_all(self) -> None:
        try:
            with self._lock:
                self._store.clear()
                self._turns.clear()
        except Exception:
            pass

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "store": {k: dict(v) for k, v in self._store.items()},
                "turns": dict(self._turns),
            }


# Singleton
_bias_store: SessionBiasStore | None = None
_bias_lock = threading.Lock()


def get_bias_store() -> SessionBiasStore:
    global _bias_store
    with _bias_lock:
        if _bias_store is None:
            _bias_store = SessionBiasStore()
        return _bias_store


def reset_bias_singleton() -> None:
    global _bias_store
    with _bias_lock:
        if _bias_store is not None:
            try:
                _bias_store.clear_all()
            except Exception:
                pass
        _bias_store = None
