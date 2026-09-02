from __future__ import annotations

import asyncio

import pytest

from rudder.domain.events import LifecyclePayload, TaskPayload
from rudder.domain.ids import RunId, SessionId, new_run_id, new_session_id
from rudder.runtime.event_bus import EventBus


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
