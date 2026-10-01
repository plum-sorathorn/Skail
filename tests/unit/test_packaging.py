from __future__ import annotations

import email
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import scripts.package_check as package_check
from scripts.package_check import inspect_sdist, inspect_wheel

ROOT = Path(__file__).resolve().parents[2]


def _wheel_for_test(tmp_path: Path) -> Path:
    configured_artifact_dir = os.environ.get("SKAIL_PACKAGE_ARTIFACT_DIR")
    if configured_artifact_dir is None:
        artifact_dir = tmp_path
        subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--outdir", str(artifact_dir)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        artifact_dir = Path(configured_artifact_dir)
    wheels = list(artifact_dir.glob("*.whl"))
    if len(wheels) != 1:
        raise AssertionError("wheel inspection requires exactly one built wheel")
    return wheels[0]


def _assert_wheel_contains_only_skail_runtime(wheel_path: Path) -> None:
    with zipfile.ZipFile(wheel_path) as wheel:
        names = wheel.namelist()
        assert "skail/__init__.py" in names
        assert "skail/cli/main.py" in names
        assert not any(name.startswith((("r" + "udder") + "/", "legacy/")) for name in names)

        entry_name = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
        entries = wheel.read(entry_name).decode()
        assert "skail = skail.cli.main:main" in entries
        assert ("r" + "udder") not in entries
        assert "conduck =" not in entries

        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = email.message_from_bytes(wheel.read(metadata_name))
        assert metadata["Name"] == "skail-harness"
        assert metadata["Requires-Python"] == ">=3.12"
        assert "Skail" in metadata["Summary"]


def test_wheel_contains_only_the_skail_runtime(tmp_path: Path) -> None:
    _assert_wheel_contains_only_skail_runtime(_wheel_for_test(tmp_path))


def test_wheel_inspection_reuses_the_release_artifact_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wheel_path = tmp_path / "skail_harness-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, "w") as wheel:
        wheel.writestr("skail/__init__.py", "")
        wheel.writestr("skail/cli/main.py", "")
        wheel.writestr(
            "skail_harness-0.1.0.dist-info/entry_points.txt",
            "[console_scripts]\nskail = skail.cli.main:main\n",
        )
        wheel.writestr(
            "skail_harness-0.1.0.dist-info/METADATA",
            "Name: skail-harness\nRequires-Python: >=3.12\nSummary: Skail\n",
        )
    monkeypatch.setenv("SKAIL_PACKAGE_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("wheel rebuilt"))

    _assert_wheel_contains_only_skail_runtime(wheel_path)


def test_package_verification_can_keep_the_inspected_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tarfile

    artifact_dir = tmp_path / "release-artifacts"
    evidence_path = tmp_path / "package-evidence.json"
    runtime_file = tmp_path / "runtime.py"
    runtime_file.write_text("", encoding="utf-8")

    def fake_build(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        output_dir = Path(command[command.index("--outdir") + 1])
        with zipfile.ZipFile(output_dir / "skail_harness-0.1.0-py3-none-any.whl", "w") as archive:
            archive.writestr("skail/__init__.py", "")
        with tarfile.open(output_dir / "skail_harness-0.1.0.tar.gz", "w:gz") as archive:
            archive.add(
                runtime_file,
                arcname="skail_harness-0.1.0/src/skail/__init__.py",
            )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(package_check.subprocess, "run", fake_build)
    monkeypatch.setattr(
        package_check,
        "source_identity",
        lambda: ("commit", "source-digest"),
    )
    monkeypatch.setattr(package_check, "verify_installation", lambda *_: None)

    evidence = package_check.verify(evidence_path, artifact_dir=artifact_dir)

    assert len(list(artifact_dir.glob("*.whl"))) == 1
    assert len(list(artifact_dir.glob("*.tar.gz"))) == 1
    assert evidence["source_commit"] == "commit"
    manifest = json.loads(
        (artifact_dir / package_check.PACKAGE_MANIFEST).read_text(encoding="utf-8")
    )
    assert manifest["source_digest"] == "source-digest"
    assert evidence_path.exists()


def test_wheel_inspection_rejects_legacy_content(tmp_path: Path) -> None:
    wheel = tmp_path / "bad.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("skail/__init__.py", "")
        archive.writestr("legacy/old.py", "")
    with pytest.raises(AssertionError, match="forbidden"):
        inspect_wheel(wheel)


def test_sdist_inspection_requires_runtime_and_rejects_legacy(tmp_path: Path) -> None:
    import tarfile

    archive_path = tmp_path / "bad.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        runtime = tmp_path / "runtime.py"
        runtime.write_text("", encoding="utf-8")
        archive.add(runtime, arcname="skail_harness-0.1.0/src/skail/__init__.py")
        legacy = tmp_path / "legacy.py"
        legacy.write_text("", encoding="utf-8")
        archive.add(legacy, arcname="skail_harness-0.1.0/legacy/old.py")
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
        archive.add(runtime, arcname="skail_harness-0.1.0/src/skail/__init__.py")
        archive.add(leaked, arcname=f"skail_harness-0.1.0/{forbidden_path}")

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

    relative_wheel = Path("relative-artifacts") / "skail.whl"
    package_check.verify_installation(relative_wheel, tmp_path)

    assert builder_options["system_site_packages"] is True
    assert commands[0][-2:] == ["--no-deps", str(relative_wheel.resolve())]
