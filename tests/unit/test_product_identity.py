from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_skail_distribution_import_and_command_identities_are_canonical() -> None:
    metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'name = "skail-harness"' in metadata
    assert 'skail = "skail.cli.main:main"' in metadata
    assert (ROOT / "src" / "skail").is_dir()
    assert not (ROOT / "src" / ("r" + "udder")).exists()


def test_skail_uses_its_own_configuration_namespace() -> None:
    paths = (ROOT / "src" / "skail" / "config" / "paths.py").read_text(encoding="utf-8")

    assert ".skail" in paths
    assert ("r" + "udder") not in paths.lower()
