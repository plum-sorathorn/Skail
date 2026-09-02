from __future__ import annotations

import os

import pytest


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
