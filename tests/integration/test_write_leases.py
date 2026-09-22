from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fakes.barriers import AsyncStartBarrier

from skail.domain.events import SecretRedactor
from skail.runtime.leases import WorkspaceLeaseManager, write_capable
from skail.tools.backend import PolicyFilesystemBackend
from skail.tools.registry import SideEffect


@pytest.mark.asyncio
async def test_lead_write_waits_while_child_holds_lease(tmp_path: Path) -> None:
    leases = WorkspaceLeaseManager()
    backend = PolicyFilesystemBackend(
        tmp_path, redactor=SecretRedactor(), task_id="lead", lease_manager=leases
    )

    barrier = AsyncStartBarrier()
    lead_started = asyncio.Event()
    lead_done = asyncio.Event()

    loop = asyncio.get_running_loop()

    async def child_writer() -> None:
        async with leases.acquire("child-task"):
            await barrier.worker("child-holding")

    def lead_writer() -> None:
        loop.call_soon_threadsafe(lead_started.set)
        backend.write("output.txt", "from lead")
        loop.call_soon_threadsafe(lead_done.set)

    child_task = asyncio.create_task(child_writer())
    await barrier.wait_for_started(1)
    print("[DEBUG] barrier started 1")
    assert leases.holder == "child-task"

    # Start lead writer
    lead_coro = asyncio.create_task(asyncio.to_thread(lead_writer))
    await lead_started.wait()
    await asyncio.sleep(0.05)
    # Lead must not have finished because child holds the lease
    assert not lead_done.is_set()

    # Release child
    barrier.release("child-holding")
    await child_task

    # Now lead can complete
    await asyncio.wait_for(lead_done.wait(), timeout=2.0)
    assert (tmp_path / "output.txt").read_text(encoding="utf-8") == "from lead"
    await lead_coro


@pytest.mark.asyncio
async def test_child_child_writer_serialization() -> None:
    leases = WorkspaceLeaseManager()
    barrier = AsyncStartBarrier()
    order: list[str] = []

    async def writer(owner: str) -> None:
        async with leases.acquire(owner):
            order.append(f"{owner}-acquired")
            await barrier.worker(owner)
            order.append(f"{owner}-released")

    task1 = asyncio.create_task(writer("child-1"))
    await barrier.wait_for_started(1)
    assert leases.holder == "child-1"

    task2 = asyncio.create_task(writer("child-2"))
    await asyncio.sleep(0.05)
    # Child 2 has not acquired because child 1 is holding
    assert "child-2-acquired" not in order

    # Release child 1
    barrier.release("child-1")
    await task1

    # Now child 2 can acquire
    await barrier.wait_for_started(2)
    assert leases.holder == "child-2"
    assert "child-2-acquired" in order

    barrier.release("child-2")
    await task2
    assert leases.holder is None


@pytest.mark.asyncio
async def test_cancellation_while_waiting_does_not_strand_lease() -> None:
    leases = WorkspaceLeaseManager()
    barrier = AsyncStartBarrier()

    async def holder() -> None:
        async with leases.acquire("holder"):
            await barrier.worker("holder")

    holder_task = asyncio.create_task(holder())
    await barrier.wait_for_started(1)
    assert leases.holder == "holder"

    # Waiter tries to acquire and waits
    async def waiter() -> None:
        async with leases.acquire("waiter"):
            pass

    waiter_task = asyncio.create_task(waiter())
    await asyncio.sleep(0.05)

    # Cancel waiter while waiting
    waiter_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter_task

    # Release holder
    barrier.release("holder")
    await holder_task
    assert leases.holder is None

    # Next requester can acquire immediately without being stranded
    async with leases.acquire("subsequent"):
        assert leases.holder == "subsequent"
    assert leases.holder is None


def test_nested_acquisition_by_same_owner_does_not_deadlock() -> None:
    leases = WorkspaceLeaseManager()
    with leases.hold("same-owner"):
        assert leases.holder == "same-owner"
        with leases.hold("same-owner"):
            assert leases.holder == "same-owner"
        assert leases.holder == "same-owner"
    assert leases.holder is None


def test_stale_owner_recovery_releases_lease() -> None:
    leases = WorkspaceLeaseManager()
    with leases.hold("leaked-owner"):
        assert leases.holder == "leaked-owner"
        # Simulate leak/crash: recover
        recovered = leases.recover_stale("leaked-owner")
        assert recovered is True
        assert leases.holder is None

    # Wrong owner does not recover
    assert leases.recover_stale("other") is False


def test_write_capable_side_effects() -> None:
    assert write_capable((SideEffect.READ_ONLY,)) is False
    assert write_capable((SideEffect.WORKSPACE_WRITE,)) is True
    assert write_capable((SideEffect.EXTERNAL_WRITE,)) is True
    assert write_capable((SideEffect.UNKNOWN,)) is True


def test_delegated_write_scope_is_enforced_by_filesystem_backend(tmp_path: Path) -> None:
    backend = PolicyFilesystemBackend(
        tmp_path,
        redactor=SecretRedactor(),
        task_id="scoped-task",
        allowed_write_paths=("src/allowed",),
    )

    allowed = backend.write("src/allowed/result.txt", "ok")
    denied = backend.write("src/outside.txt", "no")

    assert allowed.error is None
    assert denied.error == "write is outside the delegated task scope"
    assert not (tmp_path / "src" / "outside.txt").exists()
