from __future__ import annotations

import email
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import scripts.package_check as package_check
from scripts.package_check import inspect_sdist, inspect_wheel

ROOT = Path(__file__).resolve().parents[2]


def test_wheel_contains_only_the_rudder_runtime(tmp_path: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1

    with zipfile.ZipFile(wheels[0]) as wheel:
        names = wheel.namelist()
        assert "rudder/__init__.py" in names
        assert "rudder/cli/main.py" in names
        assert not any(name.startswith(("autoconduck/", "legacy/")) for name in names)

        entry_name = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
        entries = wheel.read(entry_name).decode()
        assert "rudder = rudder.cli.main:main" in entries
        assert "autoconduck" not in entries
        assert "conduck =" not in entries

        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = email.message_from_bytes(wheel.read(metadata_name))
        assert metadata["Name"] == "rudder-harness"
        assert metadata["Requires-Python"] == ">=3.12"
        assert "Rudder" in metadata["Summary"]


def test_wheel_inspection_rejects_legacy_content(tmp_path: Path) -> None:
    wheel = tmp_path / "bad.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("rudder/__init__.py", "")
        archive.writestr("legacy/old.py", "")
    with pytest.raises(AssertionError, match="forbidden"):
        inspect_wheel(wheel)


def test_sdist_inspection_requires_runtime_and_rejects_legacy(tmp_path: Path) -> None:
    import tarfile

    archive_path = tmp_path / "bad.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        runtime = tmp_path / "runtime.py"
        runtime.write_text("", encoding="utf-8")
        archive.add(runtime, arcname="rudder-harness-0.1.0/src/rudder/__init__.py")
        legacy = tmp_path / "legacy.py"
        legacy.write_text("", encoding="utf-8")
        archive.add(legacy, arcname="rudder-harness-0.1.0/legacy/autoconduck.py")
    with pytest.raises(AssertionError, match="legacy"):
        inspect_sdist(archive_path)


@pytest.mark.parametrize("forbidden_path", ("evals/run.py", "scripts/check.py", "tests/test_x.py"))
def test_sdist_inspection_rejects_development_content(
    tmp_path: Path, forbidden_path: str
) -> None:
    import tarfile

    archive_path = tmp_path / "bad.tar.gz"
    runtime = tmp_path / "runtime.py"
    runtime.write_text("", encoding="utf-8")
    leaked = tmp_path / "leaked.py"
    leaked.write_text("", encoding="utf-8")
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(runtime, arcname="rudder-harness-0.1.0/src/rudder/__init__.py")
        archive.add(leaked, arcname=f"rudder-harness-0.1.0/{forbidden_path}")

    with pytest.raises(AssertionError, match="forbidden"):
        inspect_sdist(archive_path)


def test_installation_verifier_does_not_resolve_dependencies_from_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    builder_options: dict[str, bool] = {}
    commands: list[list[str]] = []

    class FakeBuilder:
        def __init__(self, **kwargs: bool) -> None:
            builder_options.update(kwargs)

        def create(self, environment: Path) -> None:
            environment.mkdir()

    def fake_run(command: list[str], **_: object) -> None:
        commands.append(command)

    monkeypatch.setattr(package_check.venv, "EnvBuilder", FakeBuilder)
    monkeypatch.setattr(package_check, "_run", fake_run)

    package_check.verify_installation(tmp_path / "rudder.whl", tmp_path)

    assert builder_options["system_site_packages"] is True
    assert commands[0][-2:] == ["--no-deps", str(tmp_path / "rudder.whl")]
