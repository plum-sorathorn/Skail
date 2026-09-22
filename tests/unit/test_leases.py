from __future__ import annotations

import pytest

from skail.runtime.leases import WorkspaceLeaseManager, write_capable
from skail.tools.registry import SideEffect


def test_write_classification_treats_execute_and_unknown_as_write_capable() -> None:
    assert write_capable((SideEffect.READ_ONLY,)) is False
    assert write_capable((SideEffect.WORKSPACE_WRITE,)) is True
    assert write_capable((SideEffect.UNKNOWN,)) is True


@pytest.mark.asyncio
async def test_lease_releases_after_holder_exit() -> None:
    leases = WorkspaceLeaseManager()
    async with leases.acquire("child"):
        assert leases.holder == "child"
    async with leases.acquire("lead"):
        assert leases.holder == "lead"


def test_lease_is_reentrant_for_one_owner_and_recovers_a_stale_owner() -> None:
    leases = WorkspaceLeaseManager()
    with leases.hold("child"):
        with leases.hold("child"):
            assert leases.holder == "child"
        assert leases.holder == "child"
        assert leases.recover_stale("child") is True
    assert leases.holder is None
