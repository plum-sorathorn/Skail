#!/usr/bin/env python
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
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
    print("[4/4] Running and validating fresh evaluation results...")
    with tempfile.TemporaryDirectory(prefix="rudder-release-eval-") as directory:
        output = Path(directory) / "report.json"
        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "eval_routing.py"),
                "--fixtures",
                "evals/manifest.toml",
                "--output",
                str(output),
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Evaluation failed:\n{proc.stderr or proc.stdout}")
        report = json.loads(output.read_text(encoding="utf-8"))
    if report.get("fixture_count") != 52:
        raise AssertionError("evaluation fixture count must be 52")
    results = report.get("results")
    if not isinstance(results, list) or len(results) != 52 * 5:
        raise AssertionError("evaluation must contain every fixture for every policy")
    comparison = report.get("comparison")
    if not isinstance(comparison, dict) or comparison.get("all_gates_passed") is not True:
        raise AssertionError("evaluation acceptance gates did not pass")
    print("  -> Fresh evaluation report is complete and all acceptance gates passed.")


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
