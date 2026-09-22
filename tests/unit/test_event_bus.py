from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from skail.domain.events import EventEnvelope, LifecyclePayload, RoutePayload, TaskPayload
from skail.domain.ids import RunId, SessionId, new_event_id, new_run_id, new_session_id
from skail.runtime.event_bus import EventBus
from skail.sessions import Journal


async def _publish_batch(
    bus: EventBus,
    *,
    session_id: SessionId,
    run_id: RunId,
    count: int,
) -> list[int]:
    events = await asyncio.gather(
        *(
            bus.publish(
                session_id=session_id,
                run_id=run_id,
                type="task.queued",
                payload=TaskPayload(status="queued", profile=f"worker-{index}"),
            )
            for index in range(count)
        )
    )
    return [event.sequence for event in events]


@pytest.mark.asyncio
async def test_concurrent_publish_allocates_unique_monotonic_sequences_per_run() -> None:
    bus = EventBus()
    session_id = new_session_id()
    first_run = new_run_id()
    second_run = new_run_id()
    first_run_stream = bus.subscribe(first_run)
    first_received = asyncio.create_task(anext(first_run_stream))
    await asyncio.sleep(0)

    first_sequences, second_sequences = await asyncio.gather(
        _publish_batch(bus, session_id=session_id, run_id=first_run, count=75),
        _publish_batch(bus, session_id=session_id, run_id=second_run, count=50),
    )
    received = [await first_received]
    received.extend([await anext(first_run_stream) for _ in range(74)])

    assert sorted(first_sequences) == list(range(1, 76))
    assert len(first_sequences) == len(set(first_sequences))
    assert [event.sequence for event in received] == list(range(1, 76))
    assert sorted(second_sequences) == list(range(1, 51))
    assert len(second_sequences) == len(set(second_sequences))
    await first_run_stream.aclose()


@pytest.mark.asyncio
async def test_sequences_continue_within_a_run_and_restart_for_another_run() -> None:
    bus = EventBus()
    session_id = new_session_id()
    first_run = new_run_id()
    second_run = new_run_id()

    first = await bus.publish(
        session_id=session_id,
        run_id=first_run,
        type="run.started",
        payload=LifecyclePayload(status="started"),
    )
    second = await bus.publish(
        session_id=session_id,
        run_id=first_run,
        type="run.completed",
        payload=LifecyclePayload(status="completed"),
    )
    other = await bus.publish(
        session_id=session_id,
        run_id=second_run,
        type="run.started",
        payload=LifecyclePayload(status="started"),
    )

    assert (first.sequence, second.sequence, other.sequence) == (1, 2, 1)
    assert len({first.event_id, second.event_id, other.event_id}) == 3


@pytest.mark.asyncio
async def test_subscriber_receives_only_its_run_events_in_publish_order() -> None:
    bus = EventBus()
    session_id = new_session_id()
    subscribed_run = new_run_id()
    other_run = new_run_id()
    stream = bus.subscribe(subscribed_run)
    pending = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)

    await bus.publish(
        session_id=session_id,
        run_id=other_run,
        type="run.started",
        payload=LifecyclePayload(status="started"),
    )
    expected = await bus.publish(
        session_id=session_id,
        run_id=subscribed_run,
        type="run.started",
        payload=LifecyclePayload(status="started"),
    )

    assert await pending == expected
    await stream.aclose()


@pytest.mark.asyncio
async def test_journal_backed_bus_continues_after_transactional_route_events(
    tmp_path: Path,
) -> None:
    journal = Journal(tmp_path / "skail.sqlite")
    journal.migrate()
    session_id = new_session_id()
    run_id = new_run_id()
    now = datetime.now(UTC)
    journal.create_session(session_id=session_id, title="events", created_at=now)
    journal.create_run(
        run_id=run_id,
        session_id=session_id,
        status="running",
        budget_limit_usd=Decimal("1"),
        created_at=now,
    )
    journal.append_event(
        event=EventEnvelope(
            event_id=new_event_id(),
            session_id=session_id,
            run_id=run_id,
            sequence=1,
            type="route.selected",
            payload=RoutePayload(action="selected", assignment_id="assignment"),
        )
    )
    bus = EventBus(journal)
    first = await bus.publish(
        session_id=session_id,
        run_id=run_id,
        type="run.started",
        payload=LifecyclePayload(status="started"),
    )
    second = await bus.publish(
        session_id=session_id,
        run_id=run_id,
        type="run.completed",
        payload=LifecyclePayload(status="completed"),
    )
    assert (first.sequence, second.sequence) == (2, 3)
    assert [event.sequence for event in journal.get_session_snapshot(str(session_id)).events] == [
        1,
        2,
        3,
    ]


def test_post_commit_delivery_waits_for_outer_transaction_and_isolates_subscribers(
    tmp_path: Path,
) -> None:
    journal = Journal(tmp_path / "skail.sqlite")
    journal.migrate()
    session_id = new_session_id()
    run_id = new_run_id()
    now = datetime.now(UTC)
    journal.create_session(session_id=session_id, title="events", created_at=now)
    journal.create_run(
        run_id=run_id,
        session_id=session_id,
        status="running",
        budget_limit_usd=Decimal("1"),
        created_at=now,
    )
    bus = EventBus(journal)
    received: list[str] = []
    bus.add_listener(lambda event: received.append(str(event.event_id)))
    bus.add_listener(lambda event: (_ for _ in ()).throw(RuntimeError("subscriber failed")))

    with journal.transaction() as outer:
        first = EventEnvelope(
            event_id=new_event_id(),
            session_id=session_id,
            run_id=run_id,
            sequence=1,
            type="run.started",
            payload=LifecyclePayload(status="started"),
        )
        outer.append_event(first)
        bus.publish_after_commit(outer, first)
        with journal.transaction() as inner:
            second = EventEnvelope(
                event_id=new_event_id(),
                session_id=session_id,
                run_id=run_id,
                sequence=2,
                type="run.completed",
                payload=LifecyclePayload(status="completed"),
            )
            inner.append_event(second)
            bus.publish_after_commit(inner, second)
        assert received == []

    assert received == [str(first.event_id), str(second.event_id)]
    assert [event.sequence for event in bus.replay(run_id, cursor=0)] == [1, 2]


def test_rolled_back_events_are_never_delivered_or_replayed(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "skail.sqlite")
    journal.migrate()
    session_id = new_session_id()
    run_id = new_run_id()
    now = datetime.now(UTC)
    journal.create_session(session_id=session_id, title="events", created_at=now)
    journal.create_run(
        run_id=run_id,
        session_id=session_id,
        status="running",
        budget_limit_usd=Decimal("1"),
        created_at=now,
    )
    bus = EventBus(journal)
    received: list[str] = []
    bus.add_listener(lambda event: received.append(str(event.event_id)))
    event = EventEnvelope(
        event_id=new_event_id(),
        session_id=session_id,
        run_id=run_id,
        sequence=1,
        type="run.started",
        payload=LifecyclePayload(status="started"),
    )

    with pytest.raises(RuntimeError, match="rollback"):
        with journal.transaction() as transaction:
            transaction.append_event(event)
            bus.publish_after_commit(transaction, event)
            raise RuntimeError("rollback")

    assert received == []
    assert bus.replay(run_id, cursor=0) == ()
