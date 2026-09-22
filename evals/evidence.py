from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from evals.schema import (
    EvaluationFixture,
    EvaluationPolicyControls,
    EvaluationProvenance,
    OracleSpec,
    OracleType,
    RawExecutionRecord,
)
from skail.routing.selector import RouteCandidate

ROOT = Path(__file__).resolve().parents[1]


def digest_value(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def git_value(*args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    return (completed.stdout or "").strip() or "unavailable"


def fixture_digest(fixtures: Sequence[EvaluationFixture]) -> str:
    return digest_value([fixture.model_dump(mode="json") for fixture in fixtures])


def catalog_digest(catalog_revision: str, candidates: Sequence[RouteCandidate]) -> str:
    return digest_value(
        {
            "catalog_revision": catalog_revision,
            "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
        }
    )


def policy_digest(controls: Mapping[str, EvaluationPolicyControls]) -> str:
    return digest_value(
        {name: control.model_dump(mode="json") for name, control in controls.items()}
    )


def source_identity() -> tuple[str, str]:
    commit = git_value("rev-parse", "HEAD")
    tree = git_value("rev-parse", "HEAD^{tree}")
    diff = git_value("diff", "--binary", "--no-ext-diff", "HEAD")
    return commit, digest_value({"tree": tree, "working_diff": diff})


def evaluate_recorded_oracle(record: RawExecutionRecord, oracle: OracleSpec) -> bool:
    files = dict(record.workspace_text_files)
    match oracle.type:
        case OracleType.FILE_EXISTS:
            return oracle.target in files
        case OracleType.FILE_CONTAINS:
            return oracle.target in files and (oracle.expected or "") in files[oracle.target]
        case OracleType.FILE_CONTENT:
            return (
                oracle.target in files
                and files[oracle.target].strip() == (oracle.expected or "").strip()
            )
        case OracleType.COMMAND_EXIT_ZERO:
            return record.oracle_command_exit_code == 0
        case OracleType.MULTI_ASSERT:
            return all(
                evaluate_recorded_oracle(record, OracleSpec.model_validate(assertion))
                for assertion in oracle.assertions
            )
        case _:
            return False


def workspace_evidence_matches(record: RawExecutionRecord) -> bool:
    digests = dict(record.workspace_files)
    contents = dict(record.workspace_text_files)
    if len(digests) != len(record.workspace_files) or len(contents) != len(
        record.workspace_text_files
    ):
        return False
    return set(digests) == set(contents) and all(
        hashlib.sha256(content.encode("utf-8")).hexdigest() == digests[path]
        for path, content in contents.items()
    )


def evaluation_provenance(
    *,
    fixtures: Sequence[EvaluationFixture],
    catalog_revision: str,
    candidates: Sequence[RouteCandidate],
    policy_controls: Mapping[str, EvaluationPolicyControls],
    command: tuple[str, ...],
) -> EvaluationProvenance:
    source_commit, source_digest = source_identity()
    dependencies = {
        name: importlib.metadata.version(name)
        for name in ("deepagents", "langchain", "langchain-core", "langgraph", "pydantic")
    }
    return EvaluationProvenance(
        source_commit=source_commit,
        source_digest=source_digest,
        fixture_digest=fixture_digest(fixtures),
        catalog_digest=catalog_digest(catalog_revision, candidates),
        policy_digest=policy_digest(policy_controls),
        operating_system=platform.platform(),
        python_version=platform.python_version(),
        dependency_versions=dependencies,
        command=command,
    )
