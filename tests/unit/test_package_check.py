from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from evals.evidence import source_identity as evaluation_source_identity
from scripts import package_check


def test_verify_retains_package_manifest_for_reused_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_dir = tmp_path / "artifacts"

    def build(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
        del cwd, env
        output = Path(command[command.index("--outdir") + 1])
        wheel = output / "skail_harness-0.1.0-py3-none-any.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("skail/__init__.py", "")
        (output / "skail_harness-0.1.0.tar.gz").write_bytes(b"sdist")

    monkeypatch.setattr(package_check, "_run", build)
    monkeypatch.setattr(package_check, "inspect_wheel", lambda _: None)
    monkeypatch.setattr(package_check, "inspect_sdist", lambda _: None)
    monkeypatch.setattr(package_check, "verify_installation", lambda *_: None)
    monkeypatch.setattr(
        package_check,
        "source_identity",
        lambda: ("candidate-sha", "candidate-tree-digest"),
    )

    result = package_check.verify(artifact_dir=artifact_dir)

    manifest = json.loads(
        (artifact_dir / package_check.PACKAGE_MANIFEST).read_text(encoding="utf-8")
    )
    assert manifest["source_commit"] == "candidate-sha"
    assert manifest["source_digest"] == "candidate-tree-digest"
    assert {item["name"] for item in manifest["artifacts"]} == {
        result["wheel"]["name"],
        result["sdist"]["name"],
    }
    assert all(len(item["sha256"]) == 64 for item in manifest["artifacts"])


def test_package_check_source_identity_matches_evaluation_identity() -> None:
    assert package_check.source_identity() == evaluation_source_identity()


def test_package_check_source_identity_matches_a_clean_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def git(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        output = {
            ("rev-parse", "HEAD"): "candidate-commit\n",
            ("rev-parse", "HEAD^{tree}"): "candidate-tree\n",
            ("diff", "--binary", "--no-ext-diff", "HEAD"): "",
        }[tuple(command[1:])]
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(package_check.subprocess, "run", git)

    assert package_check.source_identity() == evaluation_source_identity()
