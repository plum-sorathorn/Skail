"""Skail's public package boundary."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("skail-harness")
except PackageNotFoundError:  # Source checkout before installation.
    __version__ = "0.1.0"

__all__ = ["__version__"]
