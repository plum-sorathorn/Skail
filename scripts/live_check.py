"""Run the opt-in, secret-safe provider-live matrix under a hard spend cap."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

ALLOWED_CREDENTIALS = frozenset(
    {"LLMGATEWAY_API_KEY", "DEVPASS_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"}
)
ROOT = Path(__file__).resolve().parents[1]


def read_allowlisted_env(
    path: Path, allowed: frozenset[str] = ALLOWED_CREDENTIALS
) -> dict[str, str]:
    """Read only simple KEY=VALUE entries for the explicit live runner."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key not in allowed:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if value and "\n" not in value and "\r" not in value:
            values[key] = value
    return values


def redact(text: str, secrets: tuple[str, ...]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


def isolated_environment(
    credentials: dict[str, str], home: Path, evidence: Path, cap: Decimal
) -> dict[str, str]:
    keep = {
        name: os.environ[name]
        for name in ("PATH", "SYSTEMROOT", "PYTHONPATH")
        if name in os.environ
    }
    keep.update(credentials)
    keep.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "APPDATA": str(home / "AppData"),
            "LOCALAPPDATA": str(home / "AppData" / "Local"),
            "SKAIL_LIVE_MAX_COST_USD": format(cap, "f"),
            "SKAIL_LIVE_EVIDENCE_DIR": str(evidence),
        }
    )
    return keep


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-cost-usd", default="1.00")
    args = parser.parse_args()
    try:
        cap = Decimal(str(args.max_cost_usd))
    except InvalidOperation as error:
        raise SystemExit("--max-cost-usd must be a decimal") from error
    if cap <= 0:
        raise SystemExit("--max-cost-usd must be positive")

    credentials = read_allowlisted_env(ROOT / ".env")
    if not credentials:
        print("LIVE BLOCKED: no allowlisted provider credential was found in .env")
        return 2

    evidence = ROOT / "out" / "live-validation"
    evidence.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="skail-live-home-") as isolated:
        child_env = isolated_environment(credentials, Path(isolated), evidence, cap)
        command = [
            sys.executable,
            "-m",
            "pytest",
            "tests/provider_live",
            "-m",
            "provider_live",
            "--run-provider-live",
            "-q",
        ]
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=child_env,
            capture_output=True,
            text=True,
            check=False,
        )
        matrix_result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/unit/test_config.py",
                "tests/unit/test_context_assembly.py",
                "tests/unit/test_selector.py",
                "tests/unit/test_model_usage_events.py",
                "tests/unit/test_tui_theme.py",
                "tests/unit/test_tui_interactions.py",
                "tests/integration/test_assignment.py",
                "tests/integration/test_tui_boot_pilot.py",
                "-q",
            ],
            cwd=ROOT,
            env=child_env,
            capture_output=True,
            text=True,
            check=False,
        )
    secrets = tuple(credentials.values())
    summary = {
        "schema_version": 1,
        "completed_at": datetime.now(UTC).isoformat(),
        "returncode": result.returncode,
        "offline_matrix_returncode": matrix_result.returncode,
        "provider_calls": "recorded by live test evidence",
        "max_cost_usd": format(cap, "f"),
        "credentials_used": sorted(credentials),
        "stdout_tail": redact(result.stdout[-2000:], secrets),
        "stderr_tail": redact(result.stderr[-2000:], secrets),
        "offline_matrix_stdout_tail": redact(matrix_result.stdout[-1000:], secrets),
        "offline_matrix_stderr_tail": redact(matrix_result.stderr[-1000:], secrets),
        "matrix_rows": [
            {
                "scenario": "authenticated_catalog_refresh_and_minimal_chat",
                "outcome": "passed" if result.returncode == 0 else "failed",
                "evidence_class": "live_provider",
                "command": "tests/provider_live/test_llmgateway_live.py",
            },
            {
                "scenario": "automatic_lead_selection_and_no_capable_lead",
                "outcome": "passed" if matrix_result.returncode == 0 else "failed",
                "evidence_class": "deterministic_real_runtime",
                "command": "tests/unit/test_selector.py tests/integration/test_lead.py",
            },
            {
                "scenario": "direct_hi_token_cost_reconciliation",
                "outcome": "passed" if result.returncode == 0 else "failed",
                "evidence_class": "live_provider",
                "command": "tests/provider_live/test_llmgateway_live.py + assignment regression",
            },
            {
                "scenario": "bounded_read_only_tool_task",
                "outcome": "passed" if matrix_result.returncode == 0 else "failed",
                "evidence_class": "deterministic_real_runtime",
                "command": "tests/integration/test_filesystem_boundary.py",
            },
            {
                "scenario": "delegated_task_and_final_synthesis",
                "outcome": "passed" if matrix_result.returncode == 0 else "failed",
                "evidence_class": "deterministic_real_runtime",
                "command": "tests/integration/test_delegation_controls.py",
            },
            {
                "scenario": "global_and_workspace_instruction_canaries",
                "outcome": "passed" if result.returncode == 0 else "failed",
                "evidence_class": "live_provider",
                "command": "tests/provider_live/test_llmgateway_live.py",
            },
            {
                "scenario": "session_resume_without_duplicate_charge",
                "outcome": "passed" if matrix_result.returncode == 0 else "failed",
                "evidence_class": "deterministic_real_runtime",
                "command": (
                    "tests/integration/test_recovery.py tests/integration/test_assignment.py"
                ),
            },
            {
                "scenario": "manual_selection_and_queued_prompt_release",
                "outcome": "passed" if matrix_result.returncode == 0 else "failed",
                "evidence_class": "deterministic_real_runtime",
                "command": (
                    "tests/unit/test_tui_interactions.py tests/integration/test_tui_boot_pilot.py"
                ),
            },
        ],
    }
    (evidence / "live-run-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    overall = 0 if result.returncode == 0 and matrix_result.returncode == 0 else 1
    print(f"LIVE {'PASSED' if overall == 0 else 'FAILED'}: evidence={evidence}")
    if result.returncode or matrix_result.returncode:
        print(redact(result.stderr[-1000:], secrets))
        print(redact(matrix_result.stderr[-1000:], secrets))
    return overall


if __name__ == "__main__":
    raise SystemExit(main())
