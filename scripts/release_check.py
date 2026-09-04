#!/usr/bin/env python
from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check_docs() -> None:
    print("[1/4] Verifying required documentation...")
    required_docs = [
        ROOT / "README.md",
        ROOT / "LICENSE",
        ROOT / "docs" / "rudder" / "SPEC.md",
        ROOT / "docs" / "rudder" / "ARCHITECTURE.md",
        ROOT / "docs" / "rudder" / "CLI.md",
        ROOT / "docs" / "rudder" / "FEATURES.md",
        ROOT / "docs" / "rudder" / "EVALUATION.md",
        ROOT / "docs" / "rudder" / "THREAT_MODEL.md",
        ROOT / "docs" / "rudder" / "PERFORMANCE.md",
        ROOT / "evals" / "manifest.toml",
    ]
    for doc in required_docs:
        if not doc.exists():
            raise FileNotFoundError(f"Missing required documentation: {doc}")
    print("  -> All 10 core documentation files and manifests present.")


def check_wheel_contents() -> None:
    print("[2/4] Verifying wheel distribution contents...")
    dist_dir = ROOT / "dist"
    if not dist_dir.exists():
        print("  -> Building package with python -m build...")
        subprocess.run([sys.executable, "-m", "build"], cwd=str(ROOT), check=True)

    wheels = list(dist_dir.glob("*.whl"))
    if not wheels:
        raise FileNotFoundError("No built wheel found in dist/")

    wheel_path = sorted(wheels, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    print(f"  -> Inspecting latest wheel: {wheel_path.name}")

    with zipfile.ZipFile(wheel_path) as zf:
        namelist = zf.namelist()
        for name in namelist:
            # Must only contain rudder package or dist-info
            if name.startswith("legacy/"):
                raise AssertionError(f"Forbidden legacy content packaged in wheel: {name}")
            if "autoconduck" in name.lower() and not name.startswith("rudder_agent-"):
                raise AssertionError(f"Forbidden legacy autoconduck reference in wheel: {name}")

        rudder_files = [n for n in namelist if n.startswith("rudder/")]
        if not rudder_files:
            raise AssertionError("Wheel contains no rudder package files!")
        print(f"  -> Verified {len(rudder_files)} package files in wheel; 0 legacy files.")


def check_smoke() -> None:
    print("[3/4] Running fake-provider smoke verification...")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "smoke.py"), "--fake-provider"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Smoke test failed:\n{proc.stderr}")
    print("  -> Fake-provider smoke: OK.")


def check_evals() -> None:
    print("[4/4] Verifying evaluation results...")
    run_1 = ROOT / "evals" / "results" / "run_1.json"
    if not run_1.exists():
        raise FileNotFoundError(f"Evaluation result missing: {run_1}")
    print(f"  -> Evaluation results present: {run_1.name}")


def main() -> int:
    print("=== Rudder Release Candidate Verification ===")
    try:
        check_docs()
        check_wheel_contents()
        check_smoke()
        check_evals()
        print("\n=== Release candidate verification PASSED cleanly! ===")
        return 0
    except Exception as exc:
        print(f"\n[ERROR] Release candidate verification failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
