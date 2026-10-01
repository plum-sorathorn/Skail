#!/usr/bin/env python
"""Measure the serial pytest suite on two source trees with one interpreter."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from importlib.metadata import distributions
from pathlib import Path
from typing import Any

PYTEST_ARGS = ("-m", "pytest", "-q", "--durations=40")
SECRET_ENV_NAMES = (
    "ANTHROPIC_API_KEY",
    "GITHUB_TOKEN",
    "LLMGATEWAY_API_KEY",
    "OPENAI_API_KEY",
)


def node_ids_from_collection(output: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                normalized
                for line in output.splitlines()
                for normalized in (line.strip().replace("\\", "/"),)
                if "::" in normalized and normalized.startswith(("tests/", "evals/"))
            }
        )
    )


def measured_pair_order(pair_index: int) -> tuple[str, str]:
    if pair_index % 2 == 0:
        return ("baseline", "candidate")
    return ("candidate", "baseline")


def _git_value(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    return completed.stdout.strip()


def _source_identity(root: Path) -> dict[str, str]:
    commit = _git_value(root, "rev-parse", "HEAD")
    tree = _git_value(root, "rev-parse", "HEAD^{tree}")
    working_diff = _git_value(root, "diff", "--binary", "--no-ext-diff", "HEAD")
    untracked_paths = _git_value(root, "ls-files", "--others", "--exclude-standard").splitlines()
    untracked = [
        {
            "path": relative,
            "sha256": hashlib.sha256((root / relative).read_bytes()).hexdigest(),
        }
        for relative in sorted(untracked_paths)
        if (root / relative).is_file()
    ]
    digest_input = json.dumps(
        {"tree": tree, "working_diff": working_diff, "untracked": untracked},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    status = _git_value(root, "status", "--short", "--untracked-files=normal")
    return {
        "commit": commit,
        "digest": hashlib.sha256(digest_input.encode("utf-8")).hexdigest(),
        "dirty": str(bool(status)),
    }


def _child_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("SKAIL_PACKAGE_ARTIFACT_DIR", None)
    for name in SECRET_ENV_NAMES:
        environment.pop(name, None)
    return environment


def _collect(
    tree: Path,
    label: str,
    output_dir: Path,
    environment: dict[str, str],
) -> tuple[str, ...]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=tree,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    (output_dir / f"{label}-collection.stdout.log").write_text(
        result.stdout, encoding="utf-8"
    )
    (output_dir / f"{label}-collection.stderr.log").write_text(
        result.stderr, encoding="utf-8"
    )
    if result.returncode != 0:
        raise RuntimeError(f"{label} pytest collection failed with exit code {result.returncode}")
    ids = node_ids_from_collection(result.stdout)
    if not ids:
        raise RuntimeError(f"{label} pytest collection produced no node IDs")
    return ids


def _power_scheme() -> str | None:
    if os.name != "nt":
        return None
    result = subprocess.run(
        ["powercfg", "/getactivescheme"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _elapsed_seconds(stdout: str) -> float | None:
    for line in reversed(stdout.splitlines()):
        if " passed" not in line or " in " not in line:
            continue
        elapsed = line.rsplit(" in ", 1)[-1].split(" ", 1)[0].removesuffix("s")
        try:
            if ":" not in elapsed:
                return float(elapsed)
            parts = [float(part) for part in elapsed.split(":")]
            if len(parts) == 2:
                return 60 * parts[0] + parts[1]
            if len(parts) == 3:
                return 3600 * parts[0] + 60 * parts[1] + parts[2]
        except ValueError:
            return None
    return None


def measure(
    *,
    baseline: Path,
    candidate: Path,
    output_dir: Path,
    pairs: int = 3,
    warmups: int = 1,
) -> dict[str, Any]:
    if pairs < 1 or warmups < 0:
        raise ValueError("pairs must be positive and warmups cannot be negative")
    trees = {"baseline": baseline.resolve(), "candidate": candidate.resolve()}
    for label, tree in trees.items():
        if not tree.is_dir() or not (tree / "pyproject.toml").is_file():
            raise ValueError(f"{label} must be a project root with pyproject.toml")
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise FileExistsError("measurement output directory must be empty")
    started_at_utc = datetime.now(UTC).isoformat()

    environment = _child_environment()
    collections = {
        label: _collect(tree, label, output_dir, environment)
        for label, tree in trees.items()
    }
    common = sorted(set(collections["baseline"]) & set(collections["candidate"]))
    collection_summary = {
        label: {"count": len(ids), "node_ids": list(ids)} for label, ids in collections.items()
    }
    collection_summary["comparison"] = {
        "common_count": len(common),
        "baseline_only": sorted(set(collections["baseline"]) - set(common)),
        "candidate_only": sorted(set(collections["candidate"]) - set(common)),
    }
    (output_dir / "collections.json").write_text(
        json.dumps(collection_summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    environment_summary = {
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "power_scheme": _power_scheme(),
        "pytest_environment": {
            name: environment.get(name)
            for name in ("PYTEST_ADDOPTS", "PYTHONHASHSEED", "CI")
            if environment.get(name) is not None
        },
        "distribution_versions": sorted(
            f"{distribution.metadata['Name']}=={distribution.version}"
            for distribution in distributions()
            if distribution.metadata.get("Name")
        ),
    }
    (output_dir / "environment.json").write_text(
        json.dumps(environment_summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    records: list[dict[str, Any]] = []

    def run(label: str, phase: str, index: int) -> None:
        tree = trees[label]
        run_id = f"{len(records) + 1:02d}-{label}-{phase}-{index:02d}"
        started_at = datetime.now(UTC).isoformat()
        command = [sys.executable, *PYTEST_ARGS]
        start = time.perf_counter()
        result = subprocess.run(
            command,
            cwd=tree,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        external_wall = time.perf_counter() - start
        stdout_path = output_dir / f"{run_id}.stdout.log"
        stderr_path = output_dir / f"{run_id}.stderr.log"
        stdout_path.write_text(result.stdout, encoding="utf-8")
        stderr_path.write_text(result.stderr, encoding="utf-8")
        records.append(
            {
                "run_id": run_id,
                "tree": label,
                "phase": phase,
                "pair": index if phase == "measured" else None,
                "started_at_utc": started_at,
                "command": command,
                "source": _source_identity(tree),
                "exit_code": result.returncode,
                "external_wall_seconds": round(external_wall, 3),
                "pytest_reported_seconds": _elapsed_seconds(result.stdout),
                "stdout_log": stdout_path.name,
                "stderr_log": stderr_path.name,
            }
        )
        summary = {
            "schema_version": 1,
            "started_at_utc": started_at_utc,
            "environment": environment_summary,
            "collections": collection_summary,
            "runs": records,
        }
        (output_dir / "measurement.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    for label in ("baseline", "candidate"):
        for warmup in range(1, warmups + 1):
            run(label, "warmup", warmup)
    for pair in range(pairs):
        for label in measured_pair_order(pair):
            run(label, "measured", pair + 1)

    medians = {
        label: statistics.median(
            record["external_wall_seconds"]
            for record in records
            if record["tree"] == label and record["phase"] == "measured"
        )
        for label in trees
    }
    final = {
        "schema_version": 1,
        "started_at_utc": started_at_utc,
        "finished_at_utc": datetime.now(UTC).isoformat(),
        "environment": environment_summary,
        "collections": collection_summary,
        "runs": records,
        "external_wall_medians_seconds": medians,
        "all_runs_passed": all(record["exit_code"] == 0 for record in records),
    }
    (output_dir / "measurement.json").write_text(
        json.dumps(final, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return final


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    args = parser.parse_args(argv)
    if args.pairs < 1 or args.warmups < 0:
        parser.error("--pairs must be positive and --warmups cannot be negative")
    result = measure(
        baseline=args.baseline,
        candidate=args.candidate,
        output_dir=args.output_dir,
        pairs=args.pairs,
        warmups=args.warmups,
    )
    print(
        json.dumps(
            {
                "external_wall_medians_seconds": result["external_wall_medians_seconds"],
                "all_runs_passed": result["all_runs_passed"],
            },
            indent=2,
        )
    )
    return 0 if result["all_runs_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
