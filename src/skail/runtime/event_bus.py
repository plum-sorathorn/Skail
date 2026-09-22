from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any

from skail.domain.events import EventEnvelope, EventPayload
from skail.domain.ids import (
    AttemptId,
    RunId,
    SessionId,
    TaskId,
    new_event_id,
)
from skail.sessions.journal import Journal


class EventBus:
    def __init__(self, journal: Journal | None = None) -> None:
        self._lock = asyncio.Lock()
        self._sequences: dict[RunId, int] = defaultdict(int)
        self._subscribers: dict[RunId, set[asyncio.Queue[EventEnvelope]]] = defaultdict(set)
        self._listeners: set[Callable[[EventEnvelope], None]] = set()
        self._journal = journal

    def add_listener(self, listener: Callable[[EventEnvelope], None]) -> None:
        self._listeners.add(listener)

    def remove_listener(self, listener: Callable[[EventEnvelope], None]) -> None:
        self._listeners.discard(listener)

    def publish_after_commit(self, transaction: Any, event: EventEnvelope) -> None:
        transaction.after_commit(lambda: self.publish_persisted_nowait(event))

    def replay(self, run_id: RunId, *, cursor: int = 0) -> tuple[EventEnvelope, ...]:
        if self._journal is None:
            return ()
        return self._journal.events_after(run_id=str(run_id), cursor=cursor)

    async def publish(
        self,
        *,
        session_id: SessionId,
        run_id: RunId,
        type: str,
        payload: EventPayload,
        task_id: TaskId | None = None,
        attempt_id: AttemptId | None = None,
    ) -> EventEnvelope:
        async with self._lock:
            if self._journal is None:
                self._sequences[run_id] += 1
                sequence = self._sequences[run_id]
                event = EventEnvelope(
                    event_id=new_event_id(),
                    session_id=session_id,
                    run_id=run_id,
                    task_id=task_id,
                    attempt_id=attempt_id,
                    sequence=sequence,
                    occurred_at=datetime.now(UTC),
                    type=type,
                    payload=payload,
                )
            else:
                with self._journal.transaction() as transaction:
                    persisted = transaction.connection.execute(
                        "SELECT COALESCE(MAX(sequence),0) FROM events WHERE run_id=?",
                        (str(run_id),),
                    ).fetchone()[0]
                    sequence = max(self._sequences[run_id], persisted) + 1
                    event = EventEnvelope(
                        event_id=new_event_id(),
                        session_id=session_id,
                        run_id=run_id,
                        task_id=task_id,
                        attempt_id=attempt_id,
                        sequence=sequence,
                        occurred_at=datetime.now(UTC),
                        type=type,
                        payload=payload,
                    )
                    transaction.append_event(event)
                self._sequences[run_id] = sequence
            subscribers = tuple(self._subscribers[run_id])
        self._deliver(event, subscribers)
        return event

    def publish_persisted_nowait(self, event: EventEnvelope) -> None:
        self._sequences[event.run_id] = max(self._sequences[event.run_id], event.sequence)
        self._deliver(event, tuple(self._subscribers[event.run_id]))

    def _deliver(
        self, event: EventEnvelope, queues: tuple[asyncio.Queue[EventEnvelope], ...]
    ) -> None:
        for queue in queues:
            try:
                queue.put_nowait(event)
            except Exception:
                continue
        for listener in tuple(self._listeners):
            try:
                listener(event)
            except Exception:
                continue

    async def subscribe(self, run_id: RunId) -> AsyncIterator[EventEnvelope]:
        queue: asyncio.Queue[EventEnvelope] = asyncio.Queue()
        async with self._lock:
            self._subscribers[run_id].add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                subscribers = self._subscribers.get(run_id)
                if subscribers is not None:
                    subscribers.discard(queue)
