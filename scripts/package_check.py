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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    _run([str(python), "-m", "pip", "install", "--no-deps", str(wheel)], cwd=workspace)
    clean_env = os.environ.copy()
    clean_env.pop("PYTHONPATH", None)
    commands = (
        ("skail", "--help"),
        ("skail", "--version"),
        ("skail", "smoke", "--fake-provider"),
    )
    executable_dir = environment / ("Scripts" if os.name == "nt" else "bin")
    for command in commands:
        _run([str(executable_dir / command[0]), *command[1:]], cwd=workspace, env=clean_env)


def verify(output: Path | None = None) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="skail-package-check-") as directory:
        artifacts = Path(directory) / "artifacts"
        artifacts.mkdir()
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
        verify_installation(wheels[0], Path(directory))
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        evidence: dict[str, object] = {
            "source_commit": commit,
            "python": sys.version,
            "platform": platform.platform(),
            "wheel": {"name": wheels[0].name, "sha256": sha256(wheels[0])},
            "sdist": {"name": sdists[0].name, "sha256": sha256(sdists[0])},
        }
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and verify isolated Skail artifacts")
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args(argv)
    evidence = verify(args.evidence)
    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
