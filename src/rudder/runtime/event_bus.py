from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from rudder.domain.events import EventEnvelope, EventPayload
from rudder.domain.ids import (
    AttemptId,
    RunId,
    SessionId,
    TaskId,
    new_event_id,
)
from rudder.sessions.journal import Journal


class EventBus:
    def __init__(self, journal: Journal | None = None) -> None:
        self._lock = asyncio.Lock()
        self._sequences: dict[RunId, int] = defaultdict(int)
        self._subscribers: dict[RunId, set[asyncio.Queue[EventEnvelope]]] = defaultdict(set)
        self._journal = journal

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
        for queue in subscribers:
            queue.put_nowait(event)
        return event

    def publish_persisted_nowait(self, event: EventEnvelope) -> None:
        self._sequences[event.run_id] = max(self._sequences[event.run_id], event.sequence)
        for queue in tuple(self._subscribers[event.run_id]):
            queue.put_nowait(event)

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
