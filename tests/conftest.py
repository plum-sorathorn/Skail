from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def reject_release_test_runtime_state() -> Iterator[None]:
    if os.environ.get("SKAIL_ASSERT_CLEAN_TEST_ROOT") != "1":
        yield
        return
    root = Path(__file__).resolve().parents[1]
    runtime_dir = root / ".skail"
    before = (
        tuple(sorted(path.relative_to(runtime_dir).as_posix() for path in runtime_dir.rglob("*")))
        if runtime_dir.is_dir()
        else ()
    )
    yield
    after = (
        tuple(sorted(path.relative_to(runtime_dir).as_posix() for path in runtime_dir.rglob("*")))
        if runtime_dir.is_dir()
        else ()
    )
    assert after == before, f"release test changed runtime state at {runtime_dir}"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-provider-live",
        action="store_true",
        default=False,
        help="run provider-live tests when their credential variables are present",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-provider-live"):
        for item in items:
            marker = item.get_closest_marker("provider_live")
            if marker is None:
                continue
            required = tuple(marker.kwargs.get("env", ()))
            missing = [name for name in required if not os.environ.get(name)]
            if missing:
                reason = f"missing credentials: {', '.join(missing)}"
                item.add_marker(pytest.mark.skip(reason=reason))
        return

    skip = pytest.mark.skip(reason="provider-live tests require --run-provider-live")
    for item in items:
        if item.get_closest_marker("provider_live") is not None:
            item.add_marker(skip)
