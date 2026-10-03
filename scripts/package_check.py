#!/usr/bin/env python
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_MANIFEST = "package-manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_identity() -> tuple[str, str]:
    def git_value(*args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            check=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        )
        return completed.stdout.strip() or "unavailable"

    commit = git_value("rev-parse", "HEAD")
    tree = git_value("rev-parse", "HEAD^{tree}")
    working_diff = git_value("diff", "--binary", "--no-ext-diff", "HEAD")
    identity = json.dumps(
        {"tree": tree, "working_diff": working_diff},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return commit, digest


def _artifact_records(artifact_dir: Path) -> list[dict[str, str]]:
    wheels = sorted(artifact_dir.glob("*.whl"))
    sdists = sorted(artifact_dir.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise AssertionError("package artifact directory must contain exactly one wheel and sdist")
    return [
        {"name": path.name, "sha256": sha256(path)}
        for path in sorted((*wheels, *sdists), key=lambda item: item.name)
    ]


def write_package_manifest(
    artifact_dir: Path,
    *,
    source_commit: str,
    source_digest: str,
) -> dict[str, object]:
    manifest: dict[str, object] = {
        "schema_version": 1,
        "source_commit": source_commit,
        "source_digest": source_digest,
        "python": sys.version,
        "platform": platform.platform(),
        "artifacts": _artifact_records(artifact_dir),
    }
    path = artifact_dir / PACKAGE_MANIFEST
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
    return manifest


def validate_package_manifest(
    artifact_dir: Path,
    *,
    expected_source_commit: str,
    expected_source_digest: str,
) -> dict[str, object]:
    path = artifact_dir / PACKAGE_MANIFEST
    if not path.is_file():
        raise AssertionError("package manifest is missing; rerun package_check.py")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AssertionError("package manifest is invalid; rerun package_check.py") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise AssertionError("package manifest schema is invalid; rerun package_check.py")
    if (
        manifest.get("source_commit") != expected_source_commit
        or manifest.get("source_digest") != expected_source_digest
    ):
        raise AssertionError("package manifest source identity does not match the candidate")
    if manifest.get("artifacts") != _artifact_records(artifact_dir):
        raise AssertionError("package artifacts do not match their manifest hashes")
    return manifest


def inspect_wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if "skail/__init__.py" not in names:
            raise AssertionError("wheel does not contain the skail runtime")
        forbidden = ("evals/", "scripts/", "tests/", "legacy/")
        leaked = [
            name for name in names if name.startswith(forbidden) or ("r" + "udder") in name.lower()
        ]
        if leaked:
            raise AssertionError(f"wheel contains forbidden content: {leaked[0]}")


def inspect_sdist(path: Path) -> None:
    import tarfile

    with tarfile.open(path, "r:gz") as archive:
        names = archive.getnames()
        if not any(name.endswith("/src/skail/__init__.py") for name in names):
            raise AssertionError("sdist does not contain the skail source")
        forbidden = ("evals/", "scripts/", "tests/", "legacy/")
        leaked = [
            name
            for name in names
            if name.partition("/")[2].startswith(forbidden) or ("r" + "udder") in name.lower()
        ]
        if leaked:
            raise AssertionError(f"sdist contains forbidden content: {leaked[0]}")


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True, capture_output=True, text=True)


def verify_installation(wheel: Path, workspace: Path) -> None:
    environment = workspace / "venv"
    venv.EnvBuilder(with_pip=True, clear=True, system_site_packages=True).create(environment)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    _run([str(python), "-m", "pip", "install", "--no-deps", str(wheel.resolve())], cwd=workspace)
    clean_env = os.environ.copy()
    clean_env.pop("PYTHONPATH", None)
    commands = (
        ("skail", "--help"),
        ("skail", "--version"),
    )
    executable_dir = environment / ("Scripts" if os.name == "nt" else "bin")
    for command in commands:
        _run([str(executable_dir / command[0]), *command[1:]], cwd=workspace, env=clean_env)


def verify(
    output: Path | None = None,
    *,
    artifact_dir: Path | None = None,
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="skail-package-check-") as directory:
        artifacts = artifact_dir or Path(directory) / "artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        if artifact_dir is not None and any(artifacts.iterdir()):
            raise FileExistsError("package artifact directory must be empty")
        _run(
            [sys.executable, "-m", "build", "--wheel", "--sdist", "--outdir", str(artifacts)],
            cwd=ROOT,
        )
        wheels = list(artifacts.glob("*.whl"))
        sdists = list(artifacts.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise AssertionError("primary build must produce exactly one wheel and sdist")
        inspect_wheel(wheels[0])
        inspect_sdist(sdists[0])
        verify_installation(wheels[0], Path(directory) / "installation")
        commit, source_digest = source_identity()
        evidence: dict[str, object] = {
            "source_commit": commit,
            "source_digest": source_digest,
            "python": sys.version,
            "platform": platform.platform(),
            "wheel": {"name": wheels[0].name, "sha256": sha256(wheels[0])},
            "sdist": {"name": sdists[0].name, "sha256": sha256(sdists[0])},
        }
        if artifact_dir is not None:
            write_package_manifest(
                artifacts,
                source_commit=commit,
                source_digest=source_digest,
            )
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and verify isolated Skail artifacts")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--artifact-dir", type=Path)
    args = parser.parse_args(argv)
    evidence = verify(args.evidence, artifact_dir=args.artifact_dir)
    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
