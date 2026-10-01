"""Drive one approved live TUI scenario through an isolated Windows PTY."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.live_check import read_allowlisted_env, redact  # noqa: E402

CAMPAIGN_CAP_USD = Decimal("3.00")
KEYS = {
    "enter": "\r",
    "ctrl+c": "\x03",
    "ctrl+enter": "\x1b[13;5u",
    "escape": "\x1b",
    "tab": "\t",
    "shift+tab": "\x1b[Z",
}


@dataclass(frozen=True)
class InteractionStep:
    action: str
    value: str
    timeout_seconds: float = 120.0
    minimum_runs: int = 1


@dataclass(frozen=True)
class LiveSpec:
    scenario_id: str
    argv: tuple[str, ...]
    workspace: Path
    budget_usd: Decimal
    campaign_reserve_usd: Decimal
    selected_models: tuple[str, ...]
    lead_model: str
    capability_profiles: tuple[Mapping[str, Any], ...]
    steps: tuple[InteractionStep, ...]
    env: Mapping[str, str]
    expectations: Mapping[str, Any] = field(default_factory=dict)
    rows: int = 24
    columns: int = 80


class ReadablePTY(Protocol):
    def read(self, size: int = 1024) -> str: ...

    def isalive(self) -> bool: ...


def validate_spec(
    value: object,
    *,
    root: Path = ROOT,
    campaign_cap: Decimal = Decimal("3.00"),
) -> LiveSpec:
    if not isinstance(value, dict):
        raise ValueError("scenario spec must be a JSON object")
    required = {
        "scenario_id",
        "argv",
        "workspace",
        "budget_usd",
        "campaign_reserve_usd",
        "selected_models",
        "lead_model",
        "capability_profiles",
        "steps",
    }
    if not required.issubset(value):
        raise ValueError(
            "scenario spec requires scenario_id, argv, workspace, budget, selected models, "
            "lead model, capability profiles, and steps"
        )
    scenario_id = value["scenario_id"]
    if not isinstance(scenario_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", scenario_id):
        raise ValueError("scenario_id must use only letters, digits, dot, underscore, and hyphen")
    argv = value["argv"]
    if not isinstance(argv, list) or not argv or any(
        not isinstance(part, str) or not part for part in argv
    ):
        raise ValueError("argv must be a non-empty JSON string array; shell strings are refused")
    workspace_value = value["workspace"]
    if not isinstance(workspace_value, str) or not workspace_value:
        raise ValueError("workspace must be an absolute directory path")
    workspace = Path(workspace_value)
    if not workspace.is_absolute() or not workspace.is_dir():
        raise ValueError("workspace must be an existing absolute directory")
    workspace = workspace.resolve()
    try:
        workspace.relative_to(root.resolve())
    except ValueError:
        pass
    else:
        raise ValueError("live workspace must be outside the source checkout")
    try:
        budget = Decimal(str(value["budget_usd"]))
    except InvalidOperation as exc:
        raise ValueError("budget_usd must be a positive decimal") from exc
    if not budget.is_finite() or budget <= 0:
        raise ValueError("budget_usd must be a positive finite decimal")
    try:
        reserve = Decimal(str(value["campaign_reserve_usd"]))
    except InvalidOperation as exc:
        raise ValueError("campaign_reserve_usd must be a positive decimal") from exc
    if not reserve.is_finite() or reserve <= 0 or reserve > campaign_cap:
        raise ValueError("campaign_reserve_usd must fit within the campaign cap")
    if budget > reserve:
        raise ValueError("run budget cannot exceed its campaign reservation")
    budget_values = [
        argv[index + 1]
        for index, argument in enumerate(argv[:-1])
        if argument == "--budget"
    ]
    budget_values.extend(
        argument.partition("=")[2]
        for argument in argv
        if argument.startswith("--budget=")
    )
    if len(budget_values) != 1:
        raise ValueError("argv must pass exactly one --budget equal to budget_usd")
    try:
        cli_budget = Decimal(budget_values[0])
    except InvalidOperation as exc:
        raise ValueError("argv --budget must be a decimal") from exc
    if cli_budget != budget:
        raise ValueError("argv --budget must equal scenario budget_usd")
    selected_models = value["selected_models"]
    lead_model = value["lead_model"]
    profiles = value["capability_profiles"]
    if (
        not isinstance(selected_models, list)
        or not selected_models
        or any(
            not isinstance(model, str)
            or not model.startswith("llmgateway:")
            or not model.partition(":")[2]
            for model in selected_models
        )
        or len(set(selected_models)) != len(selected_models)
    ):
        raise ValueError("selected_models must be a unique list of provider:model IDs")
    if not isinstance(lead_model, str) or lead_model not in selected_models:
        raise ValueError("lead_model must be an explicitly selected model")
    if not isinstance(profiles, list) or len(profiles) != len(selected_models):
        raise ValueError("capability_profiles must cover exactly the selected model roster")
    profile_models: set[str] = set()
    for profile in profiles:
        if not isinstance(profile, dict):
            raise ValueError("each capability profile must be a JSON object")
        provider = profile.get("provider")
        model = profile.get("model")
        if not isinstance(provider, str) or not isinstance(model, str):
            raise ValueError("capability profile requires provider and model")
        model_id = f"{provider}:{model}"
        if model_id not in selected_models or provider != "llmgateway":
            raise ValueError("capability profile must match a selected LLM Gateway model")
        if profile.get("source") != "user" or profile.get("trusted") is not True:
            raise ValueError("automatic routing requires a trusted, user-reviewed profile")
        if not isinstance(profile.get("provenance"), str) or not profile["provenance"].strip():
            raise ValueError("user-reviewed capability profile requires provenance")
        if not isinstance(profile.get("as_of"), str) or not profile["as_of"].strip():
            raise ValueError("user-reviewed capability profile requires an as_of timestamp")
        fields = profile.get("fields")
        capability = fields.get("capability") if isinstance(fields, dict) else None
        dimensions = ("coding", "reasoning", "tool_reliability", "latency")
        if not isinstance(capability, dict) or any(key not in capability for key in dimensions):
            raise ValueError("capability profile is missing required routing dimensions")
        for key in dimensions:
            score = capability[key]
            if (
                isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not 0 <= score <= 1
            ):
                raise ValueError("capability scores must be between 0 and 1")
        profile_models.add(model_id)
    if profile_models != set(selected_models):
        raise ValueError("capability_profiles must contain one matching profile per selected model")
    model_flags = {"--model", "--lead-model", "--default-model", "--agent-model"}
    for index, argument in enumerate(argv):
        option, separator, inline_value = argument.partition("=")
        if option not in model_flags:
            continue
        if separator:
            pin = inline_value
        elif index + 1 < len(argv):
            pin = argv[index + 1]
        else:
            raise ValueError(f"{option} requires a selected model")
        if option == "--agent-model":
            _, assignment_separator, pin = pin.partition("=")
            if not assignment_separator:
                raise ValueError("--agent-model must use PROFILE=PROVIDER:MODEL")
        if pin != "auto" and ":" in pin and pin not in selected_models:
            raise ValueError("CLI model pins must be members of selected_models")
        if pin != "auto" and ":" not in pin:
            raise ValueError("CLI model pins must use a selected PROVIDER:MODEL ID")
    raw_steps = value["steps"]
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("steps must be a non-empty JSON array")
    steps: list[InteractionStep] = []
    for raw in raw_steps:
        if not isinstance(raw, dict):
            raise ValueError("each interaction step must be a JSON object")
        actions = [
            name
            for name in (
                "wait_for",
                "wait_for_provider_call",
                "wait_for_run_status",
                "send_text",
                "key",
                "assert_file_absent",
            )
            if name in raw
        ]
        if len(actions) != 1:
            raise ValueError(
                "each step must contain exactly one wait, send_text, key, or file-assertion action"
            )
        action = actions[0]
        step_value = raw[action]
        if not isinstance(step_value, str) or not step_value:
            raise ValueError(f"{action} must be a non-empty string")
        if action == "key" and step_value not in KEYS:
            raise ValueError(f"unsupported key: {step_value}")
        if action == "wait_for_provider_call" and step_value not in selected_models:
            raise ValueError("wait_for_provider_call must name a selected model")
        if action == "wait_for_run_status" and step_value not in {
            "completed",
            "blocked",
            "cancelled",
            "failed",
        }:
            raise ValueError("wait_for_run_status must name a terminal run status")
        if action == "assert_file_absent" and (
            Path(step_value).is_absolute()
            or ".." in Path(step_value).parts
            or Path(step_value).drive
        ):
            raise ValueError("assert_file_absent must use a workspace-relative path")
        if action == "wait_for":
            try:
                re.compile(step_value)
            except re.error as exc:
                raise ValueError("wait_for must be a valid regular expression") from exc
        timeout = raw.get("timeout_seconds", 120.0)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ValueError("timeout_seconds must be a number")
        if not 0 < timeout <= 1800:
            raise ValueError("timeout_seconds must be between 0 and 1800")
        minimum_runs = raw.get("minimum_runs", 1)
        if (
            isinstance(minimum_runs, bool)
            or not isinstance(minimum_runs, int)
            or not 1 <= minimum_runs <= 50
        ):
            raise ValueError("minimum_runs must be between 1 and 50")
        if action == "send_text" and ("\n" in step_value or "\r" in step_value):
            raise ValueError("send_text cannot contain Enter; use an explicit key step")
        steps.append(InteractionStep(action, step_value, float(timeout), minimum_runs))
    env = value.get("env", {})
    if not isinstance(env, dict) or env:
        raise ValueError("scenario specs cannot carry environment overrides or credentials")
    rows = value.get("rows", 24)
    columns = value.get("columns", 80)
    if (
        isinstance(rows, bool)
        or isinstance(columns, bool)
        or not isinstance(rows, int)
        or not isinstance(columns, int)
        or not 24 <= rows <= 60
        or not 80 <= columns <= 200
    ):
        raise ValueError("terminal dimensions must be 24-60 rows by 80-200 columns")
    expectations = value.get("expectations", {})
    if not isinstance(expectations, dict):
        raise ValueError("expectations must be a JSON object")
    allowed_expectations = {
        "event_counts",
        "run_status_counts",
        "question_kind",
        "interrupt_ui",
        "terminal_answer_required",
        "task_count",
        "max_provider_calls",
        "changed_paths",
        "file_contents",
    }
    if set(expectations) - allowed_expectations:
        raise ValueError("expectations contain unsupported keys")
    event_counts = expectations.get("event_counts", {})
    if not isinstance(event_counts, dict) or any(
        key not in {"user.question", "user.answer", "user.cancellation"}
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count < 0
        for key, count in event_counts.items()
    ):
        raise ValueError("event_counts may name user.question, user.answer, or user.cancellation")
    run_counts = expectations.get("run_status_counts", {})
    if not isinstance(run_counts, dict) or any(
        key not in {"completed", "blocked", "cancelled", "failed", "interrupted"}
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count < 0
        for key, count in run_counts.items()
    ):
        raise ValueError("run_status_counts contains an unsupported status or count")
    if expectations.get("question_kind") not in {None, "free_form", "fixed_choice"}:
        raise ValueError("question_kind must be free_form or fixed_choice")
    if expectations.get("interrupt_ui") not in {
        None,
        "question_free_form",
        "question_fixed_choice",
        "approval",
    }:
        raise ValueError("interrupt_ui must name a supported question or approval card")
    if "terminal_answer_required" in expectations and not isinstance(
        expectations["terminal_answer_required"], bool
    ):
        raise ValueError("terminal_answer_required must be a boolean")
    for field_name, maximum in (("task_count", 100), ("max_provider_calls", 32)):
        expected_count = expectations.get(field_name)
        if expected_count is not None and (
            isinstance(expected_count, bool)
            or not isinstance(expected_count, int)
            or not 0 <= expected_count <= maximum
        ):
            raise ValueError(f"{field_name} must be between 0 and {maximum}")
    changed_paths = expectations.get("changed_paths", [])
    file_contents = expectations.get("file_contents", {})
    def safe_relative(item: object) -> bool:
        return (
            isinstance(item, str)
            and bool(item)
            and not Path(item).is_absolute()
            and ".." not in Path(item).parts
            and not Path(item).drive
        )

    if (
        not isinstance(changed_paths, list)
        or any(not safe_relative(path) for path in changed_paths)
        or len(set(changed_paths)) != len(changed_paths)
        or not isinstance(file_contents, dict)
        or any(
            not safe_relative(path) or not isinstance(text, str)
            for path, text in file_contents.items()
        )
    ):
        raise ValueError("workspace expectations must use unique workspace-relative file paths")
    return LiveSpec(
        scenario_id,
        tuple(argv),
        workspace,
        budget,
        reserve,
        tuple(selected_models),
        lead_model,
        tuple(dict(profile) for profile in profiles),
        tuple(steps),
        dict(env),
        dict(expectations),
        rows,
        columns,
    )


class ScreenCapture:
    def __init__(self, *, columns: int, rows: int) -> None:
        try:
            import pyte
        except ImportError as exc:
            raise RuntimeError("install the live extra with `pip install -e .[live]`") from exc
        self._screen = pyte.Screen(columns, rows)
        self._stream = pyte.Stream(self._screen)
        self._chunks: list[str] = []
        self.generation = 0

    def feed(self, chunk: str) -> None:
        self._chunks.append(chunk)
        self._stream.feed(chunk)
        self.generation += 1

    @property
    def text(self) -> str:
        return "\n".join(self._screen.display)

    @property
    def transcript(self) -> str:
        return "".join(self._chunks)


def find_started_provider_call(journal_path: Path, model_ref: str) -> dict[str, str] | None:
    provider, separator, model = model_ref.partition(":")
    if not separator or not provider or not model or not journal_path.is_file():
        return None
    uri = f"{journal_path.resolve().as_uri()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=0.1)
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute(
                "SELECT c.call_id,a.provider,a.model,c.status,c.created_at,c.updated_at "
                "FROM provider_calls c "
                "JOIN assignments a ON a.assignment_id=c.assignment_id "
                "JOIN attempts p ON p.attempt_id=a.attempt_id "
                "JOIN tasks t ON t.task_id=p.task_id "
                "JOIN runs r ON r.run_id=t.run_id "
                "WHERE a.provider=? AND a.model=? AND c.status='started' "
                "AND r.status='running' ORDER BY c.created_at DESC LIMIT 1",
                (provider, model),
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    return {
        key: str(row[key])
        for key in ("call_id", "provider", "model", "status", "created_at", "updated_at")
    }


def find_latest_run(journal_path: Path) -> dict[str, Any] | None:
    if not journal_path.is_file():
        return None
    uri = f"{journal_path.resolve().as_uri()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=0.1)
        connection.row_factory = sqlite3.Row
        try:
            count = connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            row = connection.execute(
                "SELECT r.run_id,r.status,s.status AS session_status "
                "FROM runs r JOIN sessions s ON s.session_id=r.session_id "
                "ORDER BY r.created_at DESC,r.rowid DESC LIMIT 1"
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    return {
        "run_id": str(row["run_id"]),
        "status": str(row["status"]),
        "session_status": str(row["session_status"]),
        "run_count": int(count),
    }


def read_to_eof(process: ReadablePTY, on_chunk: Callable[[str], None]) -> None:
    """Read through PTY EOF, including output buffered after process exit."""
    while True:
        try:
            chunk = process.read(4096)
        except EOFError:
            return
        if chunk:
            on_chunk(chunk)
            continue
        if not process.isalive():
            return
        time.sleep(0.01)


class PTYSession:
    def __init__(
        self, spec: LiveSpec, env: dict[str, str], *, journal_path: Path | None = None
    ) -> None:
        if os.name != "nt":
            raise RuntimeError("real live acceptance runs require Windows and pywinpty")
        try:
            from winpty import PtyProcess
        except ImportError as exc:
            raise RuntimeError("install the live extra with `pip install -e .[live]`") from exc
        self.process = PtyProcess.spawn(
            list(spec.argv),
            cwd=str(spec.workspace),
            env=env,
            dimensions=(spec.rows, spec.columns),
        )
        self.capture = ScreenCapture(columns=spec.columns, rows=spec.rows)
        self.journal_path = journal_path
        self._chunks: queue.Queue[str | BaseException | None] = queue.Queue()
        self._eof = False
        self._reader = threading.Thread(target=self._read, name="skail-live-pty", daemon=True)
        self._reader.start()

    def _read(self) -> None:
        try:
            read_to_eof(self.process, self._chunks.put)
        except BaseException as exc:
            self._chunks.put(exc)
        finally:
            self._chunks.put(None)

    def _consume(self, timeout: float) -> bool:
        try:
            chunk = self._chunks.get(timeout=max(0.0, timeout))
        except queue.Empty:
            return True
        if chunk is None:
            self._eof = True
            return False
        if isinstance(chunk, BaseException):
            raise RuntimeError("PTY output reader failed") from chunk
        self.capture.feed(chunk)
        return True

    def wait_for(self, pattern: str, timeout_seconds: float) -> str:
        matcher = re.compile(pattern, re.MULTILINE)
        deadline = time.monotonic() + timeout_seconds
        while True:
            screen = self.capture.text
            if matcher.search(screen):
                return screen
            if self._eof:
                raise RuntimeError("PTY process ended before the requested screen state appeared")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("PTY screen state did not appear before its deadline")
            self._consume(min(remaining, 0.1))

    def wait_for_provider_call(self, model_ref: str, timeout_seconds: float) -> dict[str, str]:
        if self.journal_path is None:
            raise RuntimeError("provider-call observation requires the isolated journal path")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            call = find_started_provider_call(self.journal_path, model_ref)
            if call is not None:
                return {**call, "observed_at": datetime.now(UTC).isoformat()}
            if self._eof:
                break
            self._consume(0.02)
        raise TimeoutError("the selected provider call was not observed in started state")

    def wait_for_run_status(
        self, status: str, timeout_seconds: float, minimum_runs: int
    ) -> dict[str, Any]:
        if self.journal_path is None:
            raise RuntimeError("run status observation requires the isolated journal path")
        terminal = {"completed", "blocked", "cancelled", "failed"}
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            latest = find_latest_run(self.journal_path)
            if latest is not None and latest["run_count"] >= minimum_runs:
                pending_resume = latest["session_status"] == "interrupted"
                if latest["status"] == status and not pending_resume:
                    return {**latest, "observed_at": datetime.now(UTC).isoformat()}
                if latest["status"] in terminal and not pending_resume:
                    raise RuntimeError(
                        f"run {latest['run_id']} ended {latest['status']}, expected {status}"
                    )
            if self._eof:
                break
            self._consume(0.02)
        raise TimeoutError("expected run status was not observed before its deadline")

    def send_text(self, value: str) -> None:
        self.process.write(value)

    def send_key(self, value: str) -> None:
        self.process.write(KEYS[value])

    def drain_for(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while not self._eof and time.monotonic() < deadline:
            if not self._consume(min(0.1, deadline - time.monotonic())):
                return

    def close(self) -> None:
        if self.process.isalive():
            self.process.terminate(force=True)
        self._reader.join(timeout=5)
        deadline = time.monotonic() + 5
        while not self._eof and time.monotonic() < deadline:
            self._consume(0.1)
        if not self._eof:
            raise RuntimeError("PTY reader did not drain to EOF after stopping its owned child")


def _child_environment(
    credentials: Mapping[str, str], home: Path, evidence_dir: Path, spec: LiveSpec
) -> dict[str, str]:
    environment = {
        name: os.environ[name]
        for name in ("PATH", "SYSTEMROOT", "WINDIR", "PATHEXT", "TEMP", "TMP")
        if name in os.environ
    }
    environment.update(credentials)
    environment.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "APPDATA": str(home / "AppData"),
            "LOCALAPPDATA": str(home / "AppData" / "Local"),
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
            "PYTHONUTF8": "1",
            "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT))),
            "SKAIL_LIVE_MAX_COST_USD": format(spec.budget_usd, "f"),
            "SKAIL_LIVE_EVIDENCE_DIR": str(evidence_dir),
        }
    )
    environment.update(spec.env)
    return environment


def write_user_config(home: Path, spec: LiveSpec) -> Path:
    import tomli_w

    user_config = {
        "routing": {"mode": "auto", "lead_model": spec.lead_model},
        "orchestration": {"max_agents": 3, "max_depth": 1},
        "budget": {"run_usd": float(spec.budget_usd), "warning_percent": 80},
        "providers": {
            "llmgateway": {
                "type": "openai-compatible",
                "base_url": "https://api.llmgateway.io/v1",
                "api_key_env": "LLMGATEWAY_API_KEY",
                "models": [model.partition(":")[2] for model in spec.selected_models],
            }
        },
        "catalog": {"entries": [dict(profile) for profile in spec.capability_profiles]},
    }
    path = home / ".skail" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomli_w.dumps(user_config), encoding="utf-8")
    return path


def _catalog_preflight(
    credentials: Mapping[str, str], spec: LiveSpec, evidence_dir: Path
) -> dict[str, Any]:
    token = credentials.get("LLMGATEWAY_API_KEY")
    if not token:
        raise ValueError("selected model roster requires an LLM Gateway credential")
    response = httpx.get(
        "https://api.llmgateway.io/v1/models",
        headers={"Authorization": f"Bearer {token}"},
        timeout=25.0,
    )
    if not response.is_success:
        raise RuntimeError(f"authenticated model discovery returned HTTP {response.status_code}")
    body = response.json()
    entries = body.get("data") if isinstance(body, dict) else None
    if not isinstance(entries, list):
        raise ValueError("authenticated model discovery response has no data array")
    by_id = {
        entry.get("id"): entry
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }
    selected: list[dict[str, Any]] = []
    for model_ref in spec.selected_models:
        model_id = model_ref.partition(":")[2]
        entry = by_id.get(model_id)
        if entry is None:
            raise ValueError(f"selected model {model_ref} is not in the authenticated roster")
        pricing = entry.get("pricing")
        if not isinstance(pricing, dict):
            raise ValueError(f"selected model {model_ref} has no current pricing")
        for price_field in ("prompt", "completion"):
            try:
                rate = Decimal(str(pricing[price_field]))
            except (KeyError, InvalidOperation) as exc:
                raise ValueError(f"selected model {model_ref} has incomplete pricing") from exc
            if not rate.is_finite() or rate <= 0:
                raise ValueError(f"selected model {model_ref} has invalid pricing")
        providers = entry.get("providers", [])
        if not isinstance(providers, list) or not any(
            isinstance(provider, dict) and provider.get("tools") is True
            for provider in providers
        ):
            raise ValueError(f"selected model {model_ref} has no tool-capable provider mapping")
        selected.append(entry)
    result = {
        "retrieved_at": datetime.now(UTC).isoformat(),
        "endpoint": "https://api.llmgateway.io/v1/models",
        "http_status": response.status_code,
        "accessible_model_count": len(entries),
        "selected_models": list(spec.selected_models),
        "models": selected,
    }
    _write_json(evidence_dir / "catalog-preflight.json", result)
    return result


def _redact_value(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, str):
        return redact(value, secrets)
    if isinstance(value, list):
        return [_redact_value(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: _redact_value(item, secrets) for key, item in value.items()}
    return value


def _evidence_path(path: Path) -> Path:
    if not path.is_absolute():
        raise ValueError("evidence directory must be an absolute path")
    resolved = path.resolve()
    output_root = (ROOT / "out" / "live-agentic").resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        try:
            resolved.relative_to(output_root)
        except ValueError as exc:
            raise ValueError(
                "evidence must be outside the checkout or under out/live-agentic"
            ) from exc
    if resolved.exists() and any(resolved.iterdir()):
        raise FileExistsError("evidence directory must be empty")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def verify_session_export(
    export: Mapping[str, Any],
    *,
    terminal_frames: list[str],
    selected_models: tuple[str, ...],
    reserved_usd: Decimal,
    expected_event_counts: Mapping[str, int] | None = None,
    expected_run_status_counts: Mapping[str, int] | None = None,
    expected_question_kind: str | None = None,
    expected_interrupt_ui: str | None = None,
    terminal_answer_required: bool = True,
    expected_task_count: int | None = None,
    max_provider_calls: int | None = None,
    observed_provider_call_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    from skail.runtime.presentation import model_content_to_text, present_lead_answer

    if export.get("schema_version") != 2:
        raise ValueError("live verification requires session export schema version 2")
    runs = export.get("runs")
    events = export.get("events")
    provider_calls = export.get("provider_calls")
    attempts = export.get("attempts")
    if not all(isinstance(value, list) for value in (runs, events, provider_calls, attempts)):
        raise ValueError("session export is missing runs, events, provider_calls, or attempts")

    event_counts = Counter(str(event.get("type")) for event in events if isinstance(event, dict))
    event_ids = [
        event["event_id"]
        for event in events
        if isinstance(event, dict) and isinstance(event.get("event_id"), str)
    ]
    duplicate_event_ids = sorted(
        event_id for event_id, count in Counter(event_ids).items() if count > 1
    )
    completions = [
        event
        for event in events
        if isinstance(event, dict) and event.get("type") == "run.completed"
    ]
    completion_counts = Counter(
        event["run_id"] for event in completions if isinstance(event.get("run_id"), str)
    )
    run_statuses = {
        run["run_id"]: run.get("status")
        for run in runs
        if isinstance(run, dict) and isinstance(run.get("run_id"), str)
    }
    run_status_counts = Counter(
        str(run.get("status")) for run in runs if isinstance(run, dict)
    )
    event_count_mismatches = {
        name: {"expected": expected, "actual": event_counts[name]}
        for name, expected in (expected_event_counts or {}).items()
        if event_counts[name] != expected
    }
    run_status_count_mismatches = {
        name: {"expected": expected, "actual": run_status_counts[name]}
        for name, expected in (expected_run_status_counts or {}).items()
        if run_status_counts[name] != expected
    }
    question_events = [
        event
        for event in events
        if isinstance(event, dict) and event.get("type") == "user.question"
    ]
    question_ids = {
        event["payload"].get("interrupt_id")
        for event in question_events
        if isinstance(event.get("payload"), dict)
        and isinstance(event["payload"].get("interrupt_id"), str)
    }
    question_option_sets = [
        tuple(event["payload"].get("options", ()))
        for event in question_events
        if isinstance(event.get("payload"), dict)
    ]
    question_kind_matches = (
        expected_question_kind is None
        or bool(question_events)
        and all(
            not options if expected_question_kind == "free_form" else bool(options)
            for options in question_option_sets
        )
    )
    uncorrelated_interrupts = []
    for event in events:
        if not isinstance(event, dict) or event.get("type") not in {
            "user.answer",
            "user.cancellation",
        }:
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            uncorrelated_interrupts.append(str(event.get("event_id", "unknown")))
            continue
        interrupt_id = payload.get("interrupt_id")
        kind = payload.get("kind")
        if event["type"] == "user.answer" or kind == "question":
            if interrupt_id not in question_ids:
                uncorrelated_interrupts.append(str(event.get("event_id", "unknown")))
        elif kind == "approval" and not isinstance(interrupt_id, str):
            uncorrelated_interrupts.append(str(event.get("event_id", "unknown")))
    completed_run_ids = {
        run_id for run_id, status in run_statuses.items() if status == "completed"
    }
    missing_completions = sorted(
        run_id for run_id in completed_run_ids if completion_counts[run_id] == 0
    )
    unexpected_completions = sorted(
        run_id
        for run_id, count in completion_counts.items()
        if count and run_statuses.get(run_id) != "completed"
    )
    duplicate_completions = sorted(
        run_id for run_id, count in completion_counts.items() if count > 1
    )
    cancel_sequence_by_run: dict[str, int] = {}
    for event in events:
        if (
            isinstance(event, dict)
            and event.get("type") == "run.cancelled"
            and isinstance(event.get("run_id"), str)
            and isinstance(event.get("sequence"), int)
        ):
            run_id = event["run_id"]
            cancel_sequence_by_run[run_id] = max(
                event["sequence"], cancel_sequence_by_run.get(run_id, 0)
            )
    model_started_after_cancel = sorted(
        {
            event["run_id"]
            for event in events
            if isinstance(event, dict)
            and event.get("type") == "model.started"
            and isinstance(event.get("run_id"), str)
            and event["run_id"] in cancel_sequence_by_run
            and isinstance(event.get("sequence"), int)
            and event["sequence"] > cancel_sequence_by_run.get(event["run_id"], -1)
        }
    )
    normalized_frames = [" ".join(frame.split()) for frame in terminal_frames]
    lowercase_frames = [frame.casefold() for frame in normalized_frames]
    if expected_interrupt_ui == "question_free_form":
        interrupt_ui_matches = any(
            "your answer is needed" in frame
            and "answer" in frame
            and "cancel run" in frame
            and "approve" not in frame
            for frame in lowercase_frames
        )
    elif expected_interrupt_ui == "question_fixed_choice":
        interrupt_ui_matches = any(
            "your answer is needed" in frame
            and "options:" in frame
            and "answer" in frame
            and "cancel run" in frame
            and "approve" not in frame
            for frame in lowercase_frames
        )
    elif expected_interrupt_ui == "approval":
        interrupt_ui_matches = any(
            "approval required" in frame
            and "approve a" in frame
            and "reject r" in frame
            and "cancel run" not in frame
            for frame in lowercase_frames
        )
    else:
        interrupt_ui_matches = True
    answer_matches: dict[str, list[bool | None]] = {}
    for event in completions:
        run_id = event.get("run_id")
        payload = event.get("payload")
        output = payload.get("output") if isinstance(payload, dict) else None
        if not terminal_answer_required:
            found = None
        else:
            answer = present_lead_answer(model_content_to_text(output))
            normalized_answer = " ".join(answer.split())
            found = bool(normalized_answer) and any(
                normalized_answer in frame for frame in normalized_frames
            )
        if isinstance(run_id, str):
            answer_matches.setdefault(run_id, []).append(found)
    terminal_answer_matches = {
        run_id: None if all(match is None for match in matches)
        else bool(matches) and all(match is True for match in matches)
        for run_id, matches in answer_matches.items()
    }
    call_ids = [
        call["call_id"]
        for call in provider_calls
        if isinstance(call, dict) and isinstance(call.get("call_id"), str)
    ]
    duplicate_call_ids = sorted(
        call_id for call_id, count in Counter(call_ids).items() if count > 1
    )
    calls_by_run = Counter(
        call.get("run_id")
        for call in provider_calls
        if isinstance(call, dict) and isinstance(call.get("run_id"), str)
    )
    over_limit_call_runs = sorted(
        run_id for run_id, count in calls_by_run.items() if count > 32
    )
    missing_observed_call_ids = sorted(set(observed_provider_call_ids) - set(call_ids))
    allowed_models = set(selected_models)
    unselected_models = sorted(
        {
            f"{call.get('provider')}:{call.get('model')}"
            for call in provider_calls
            if isinstance(call, dict)
            and f"{call.get('provider')}:{call.get('model')}" not in allowed_models
        }
    )
    known_cost = Decimal("0")
    cost_unresolved = False
    for call in provider_calls:
        if not isinstance(call, dict) or call.get("cost_usd") is None:
            cost_unresolved = True
            continue
        try:
            amount = Decimal(str(call["cost_usd"]))
        except Exception:
            cost_unresolved = True
            continue
        if not amount.is_finite() or amount < 0:
            cost_unresolved = True
            continue
        known_cost += amount
    cost_within_reservation = not cost_unresolved and known_cost <= reserved_usd
    attempts_per_task = Counter(
        attempt.get("task_id")
        for attempt in attempts
        if isinstance(attempt, dict) and isinstance(attempt.get("task_id"), str)
    )
    over_attempted_tasks = sorted(
        task_id for task_id, count in attempts_per_task.items() if count > 2
    )
    task_count_mismatch = (
        expected_task_count is not None and len(export.get("tasks", [])) != expected_task_count
    )
    provider_call_limit_exceeded = (
        max_provider_calls is not None and len(provider_calls) > max_provider_calls
    )
    failed_checks: list[str] = []
    for label, failures in (
        ("duplicate_event_ids", duplicate_event_ids),
        ("duplicate_completion_run_ids", duplicate_completions),
        ("missing_completion_run_ids", missing_completions),
        ("unexpected_completion_run_ids", unexpected_completions),
        ("model_started_after_cancel", model_started_after_cancel),
        ("duplicate_call_ids", duplicate_call_ids),
        ("missing_observed_provider_call_ids", missing_observed_call_ids),
        ("unselected_model_calls", unselected_models),
        ("over_attempted_tasks", over_attempted_tasks),
        ("over_limit_call_runs", over_limit_call_runs),
        ("uncorrelated_interrupt_events", uncorrelated_interrupts),
        ("event_count_mismatches", event_count_mismatches),
        ("run_status_count_mismatches", run_status_count_mismatches),
        ("interrupt_ui_mismatch", [] if interrupt_ui_matches else [expected_interrupt_ui]),
        (
            "terminal_answer_mismatch_run_ids",
            sorted(
                run_id
                for run_id, matched in terminal_answer_matches.items()
                if matched is False
            ),
        ),
    ):
        if failures:
            failed_checks.append(label)
    if not cost_within_reservation:
        failed_checks.append("cost_unresolved_or_over_reservation")
    if not question_kind_matches:
        failed_checks.append("question_kind_mismatch")
    if task_count_mismatch:
        failed_checks.append("task_count_mismatch")
    if provider_call_limit_exceeded:
        failed_checks.append("provider_call_limit_exceeded")
    return {
        "status": "failed" if failed_checks else "passed",
        "event_counts": {
            name: event_counts[name]
            for name in ("user.question", "user.answer", "user.cancellation")
            if event_counts[name]
        },
        "run_statuses": run_statuses,
        "run_status_counts": dict(run_status_counts),
        "run_status_count_mismatches": run_status_count_mismatches,
        "event_count_mismatches": event_count_mismatches,
        "question_kind_matches": question_kind_matches,
        "interrupt_ui_matches": interrupt_ui_matches,
        "question_option_sets": [list(options) for options in question_option_sets],
        "uncorrelated_interrupt_events": uncorrelated_interrupts,
        "completion_event_count": len(completions),
        "completion_counts": dict(completion_counts),
        "duplicate_completion_run_ids": duplicate_completions,
        "missing_completion_run_ids": missing_completions,
        "unexpected_completion_run_ids": unexpected_completions,
        "model_started_after_cancel": model_started_after_cancel,
        "duplicate_event_ids": duplicate_event_ids,
        "provider_call_count": len(provider_calls),
        "provider_call_counts_by_run": dict(calls_by_run),
        "over_limit_call_runs": over_limit_call_runs,
        "provider_call_limit_exceeded": provider_call_limit_exceeded,
        "duplicate_call_ids": duplicate_call_ids,
        "observed_provider_call_ids": list(observed_provider_call_ids),
        "missing_observed_provider_call_ids": missing_observed_call_ids,
        "unselected_model_calls": unselected_models,
        "over_attempted_tasks": over_attempted_tasks,
        "task_count": len(export.get("tasks", [])),
        "expected_task_count": expected_task_count,
        "task_count_mismatch": task_count_mismatch,
        "terminal_answer_matches": terminal_answer_matches,
        "local_token_cost_usd": None if cost_unresolved else format(known_cost, "f"),
        "reserved_usd": format(reserved_usd, "f"),
        "cost_within_reservation": cost_within_reservation,
        "failed_checks": failed_checks,
    }


def _workspace_manifest(workspace: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for path in sorted(workspace.rglob("*")):
        relative = path.relative_to(workspace).as_posix()
        if path.is_symlink():
            manifest[relative] = "symlink"
        elif path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            manifest[relative] = digest.hexdigest()
    return manifest


def _changed_paths(before: Mapping[str, str], after: Mapping[str, str]) -> list[str]:
    return sorted(
        path
        for path in before.keys() | after.keys()
        if before.get(path) != after.get(path)
    )


def _verify_workspace_expectations(
    workspace: Path,
    before: Mapping[str, str],
    after: Mapping[str, str],
    expectations: Mapping[str, Any],
) -> dict[str, Any]:
    changed_paths = _changed_paths(before, after)
    expected_paths = expectations.get("changed_paths")
    paths_match = (
        expected_paths is None or changed_paths == sorted(expected_paths)
    )
    file_matches: dict[str, bool] = {}
    for relative, expected_content in expectations.get("file_contents", {}).items():
        path = (workspace / relative).resolve()
        try:
            path.relative_to(workspace.resolve())
        except ValueError:
            file_matches[relative] = False
            continue
        try:
            file_matches[relative] = (
                path.is_file() and path.read_text(encoding="utf-8") == expected_content
            )
        except (OSError, UnicodeError):
            file_matches[relative] = False
    failed = not paths_match or any(not match for match in file_matches.values())
    return {
        "status": "failed" if failed else "passed",
        "changed_paths": changed_paths,
        "expected_changed_paths": expected_paths,
        "changed_paths_match": paths_match,
        "file_content_matches": file_matches,
    }


def _require_file_absent(workspace: Path, relative: str) -> None:
    path = (workspace / relative).resolve()
    try:
        path.relative_to(workspace.resolve())
    except ValueError as exc:
        raise ValueError("asserted file path escapes the workspace") from exc
    if path.exists():
        raise RuntimeError(f"workspace path already exists before approval: {relative}")


def _export_latest_session(
    home: Path, evidence_dir: Path, secrets: tuple[str, ...]
) -> tuple[str, dict[str, Any]]:
    from skail.sessions.export import SessionExporter
    from skail.sessions.journal import Journal

    journal = Journal(home / ".skail" / "journal.sqlite")
    sessions = journal.list_sessions()
    if not sessions:
        raise RuntimeError("live TUI produced no persisted session")
    if len(sessions) != 1:
        raise RuntimeError("isolated live TUI home contains more than one session")
    session_id = str(sessions[0].session_id)
    export = SessionExporter(journal=journal).export(session_id)
    scrubbed = _redact_value(export, secrets)
    _write_json(evidence_dir / "session-export.json", scrubbed)
    if not isinstance(scrubbed, dict):
        raise TypeError("session exporter returned an invalid root value")
    return session_id, scrubbed
@contextmanager
def _campaign_lock(path: Path) -> Iterator[None]:
    if not path.is_absolute():
        raise ValueError("campaign ledger path must be absolute")
    path = path.resolve()
    output_root = (ROOT / "out" / "live-agentic").resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        try:
            path.relative_to(output_root)
        except ValueError as exc:
            raise ValueError(
                "campaign ledger must be outside the checkout or under out/live-agentic"
            ) from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f"{path.name}.lock")
    try:
        lock = lock_path.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise ValueError(
            "campaign ledger is already in use; live scenarios must run serially"
        ) from exc
    try:
        yield
    finally:
        lock.close()
        lock_path.unlink(missing_ok=True)


def _reserve_campaign(path: Path, spec: LiveSpec, evidence_dir: Path) -> None:
    with _campaign_lock(path):
        _reserve_campaign_locked(path, spec, evidence_dir)


def _reserve_campaign_locked(path: Path, spec: LiveSpec, evidence_dir: Path) -> None:
    if not path.is_absolute():
        raise ValueError("campaign ledger path must be absolute")
    path = path.resolve()
    output_root = (ROOT / "out" / "live-agentic").resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        try:
            path.relative_to(output_root)
        except ValueError as exc:
            raise ValueError(
                "campaign ledger must be outside the checkout or under out/live-agentic"
            ) from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        ledger = json.loads(path.read_text(encoding="utf-8"))
        if Decimal(str(ledger.get("cap_usd"))) != CAMPAIGN_CAP_USD:
            raise ValueError("campaign ledger cap does not match the approved USD 3.00 cap")
    else:
        ledger = {
            "schema_version": 1,
            "cap_usd": format(CAMPAIGN_CAP_USD, "f"),
            "runs": [],
        }
    runs = ledger.get("runs")
    if not isinstance(runs, list):
        raise ValueError("campaign ledger runs must be an array")
    if any(isinstance(item, dict) and item.get("status") == "running" for item in runs):
        raise ValueError("campaign contains an unfinished run; settle it before the next scenario")
    if any(
        item.get("scenario_id") == spec.scenario_id
        for item in runs
        if isinstance(item, dict)
    ):
        raise ValueError("scenario_id was already reserved in this campaign")
    reserved = Decimal("0")
    for item in runs:
        if not isinstance(item, dict):
            raise ValueError("campaign ledger entries must be objects")
        amount = Decimal(str(item["reserved_usd"]))
        settled = item.get("settled_usd")
        if settled is not None:
            amount = Decimal(str(settled))
            if not amount.is_finite() or amount < 0 or amount > Decimal(str(item["reserved_usd"])):
                raise ValueError("settled campaign cost must be within its reservation")
        reserved += amount
    if reserved + spec.campaign_reserve_usd > CAMPAIGN_CAP_USD:
        raise ValueError("scenario budget would exceed the approved USD 3.00 campaign cap")
    runs.append(
        {
            "scenario_id": spec.scenario_id,
            "reserved_usd": format(spec.campaign_reserve_usd, "f"),
            "status": "running",
            "evidence_dir": str(evidence_dir),
            "started_at": datetime.now(UTC).isoformat(),
        }
    )
    _write_json(path, ledger)


def _finish_campaign(
    path: Path, scenario_id: str, status: str, settled_usd: Decimal | None = None
) -> None:
    with _campaign_lock(path):
        _finish_campaign_locked(path, scenario_id, status, settled_usd)


def _finish_campaign_locked(
    path: Path, scenario_id: str, status: str, settled_usd: Decimal | None
) -> None:
    ledger = json.loads(path.read_text(encoding="utf-8"))
    for run in ledger["runs"]:
        if run["scenario_id"] == scenario_id:
            run["status"] = status
            run["finished_at"] = datetime.now(UTC).isoformat()
            if settled_usd is not None:
                reserved = Decimal(str(run["reserved_usd"]))
                if not settled_usd.is_finite() or settled_usd < 0 or settled_usd > reserved:
                    raise ValueError("settled campaign cost exceeds its reservation")
                run["settled_usd"] = format(settled_usd, "f")
                run["settlement_basis"] = "schema-v2 session export local token cost"
            _write_json(path, ledger)
            return
    raise RuntimeError("campaign reservation disappeared")


def run_scenario(spec: LiveSpec, evidence_dir: Path, campaign_ledger: Path) -> int:
    try:
        evidence_dir = _evidence_path(evidence_dir)
    except (OSError, ValueError) as exc:
        print(f"LIVE BLOCKED: evidence path rejected ({type(exc).__name__})", file=sys.stderr)
        return 2
    credentials = read_allowlisted_env(ROOT / ".env")
    if not credentials:
        preflight = {"status": "blocked", "reason": "no allowlisted credential in .env"}
        (evidence_dir / "preflight.json").write_text(
            json.dumps(preflight, indent=2) + "\n", encoding="utf-8"
        )
        print("LIVE BLOCKED: no allowlisted provider credential was found in .env")
        return 2
    secrets = tuple(credentials.values())
    try:
        _catalog_preflight(credentials, spec, evidence_dir)
    except Exception as exc:
        _write_json(
            evidence_dir / "preflight.json",
            {"status": "blocked", "reason": redact(str(exc), secrets)},
        )
        print("LIVE BLOCKED: selected roster or current pricing preflight failed", file=sys.stderr)
        return 2
    try:
        _reserve_campaign(campaign_ledger, spec, evidence_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _write_json(
            evidence_dir / "preflight.json",
            {"status": "blocked", "reason": redact(str(exc), secrets)},
        )
        print("LIVE BLOCKED: campaign budget or ledger check failed", file=sys.stderr)
        return 2
    timeline: list[dict[str, Any]] = []
    session: PTYSession | None = None
    failure: str | None = None
    fixture_trust_returncode: int | None = None
    before_manifest: dict[str, str] = {}
    after_manifest: dict[str, str] = {}
    exported_session_id: str | None = None
    verification: dict[str, Any] = {"status": "unavailable"}
    started_at = datetime.now(UTC).isoformat()
    home_context = tempfile.TemporaryDirectory(prefix="skail-live-pty-home-")
    home = Path(home_context.name)
    try:
        before_manifest = _workspace_manifest(spec.workspace)
        environment = _child_environment(credentials, home, evidence_dir, spec)
        write_user_config(home, spec)
        trust = subprocess.run(
            [sys.executable, "-m", "skail", "--approve-project"],
            cwd=spec.workspace,
            env=environment,
            capture_output=True,
            text=True,
        )
        fixture_trust_returncode = trust.returncode
        if trust.returncode != 0:
            raise RuntimeError(
                "disposable fixture trust failed: "
                f"{redact(trust.stderr or trust.stdout, secrets)}"
            )
        session = PTYSession(
            spec, environment, journal_path=home / ".skail" / "journal.sqlite"
        )
        for index, step in enumerate(spec.steps, start=1):
            provider_call: dict[str, str] | None = None
            run_observation: dict[str, Any] | None = None
            if step.action == "wait_for":
                screen = session.wait_for(step.value, step.timeout_seconds)
            elif step.action == "wait_for_provider_call":
                provider_call = session.wait_for_provider_call(
                    step.value, step.timeout_seconds
                )
                screen = session.capture.text
            elif step.action == "wait_for_run_status":
                run_observation = session.wait_for_run_status(
                    step.value, step.timeout_seconds, step.minimum_runs
                )
                screen = session.capture.text
            elif step.action == "assert_file_absent":
                _require_file_absent(spec.workspace, step.value)
                screen = session.capture.text
            elif step.action == "send_text":
                session.send_text(step.value)
                screen = session.capture.text
            else:
                session.send_key(step.value)
                session.drain_for(0.12)
                screen = session.capture.text
            timeline.append(
                {
                    "step": index,
                    "action": step.action,
                    "value": step.value,
                    "screen": screen,
                    "provider_call": provider_call,
                    "run_observation": run_observation,
                }
            )
        session.drain_for(0.25)
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
    finally:
        if session is not None:
            try:
                session.close()
            except Exception as exc:
                failure = failure or f"{type(exc).__name__}: PTY cleanup failed"
            timeline.append(
                {
                    "step": "final",
                    "action": "capture",
                    "value": "final screen after draining PTY EOF",
                    "screen": session.capture.text,
                }
            )
            transcript = session.capture.transcript
            final_screen = session.capture.text
        else:
            transcript = ""
            final_screen = ""
        try:
            after_manifest = _workspace_manifest(spec.workspace)
            if session is None:
                raise RuntimeError("live TUI did not start")
            exported_session_id, exported = _export_latest_session(home, evidence_dir, secrets)
            verification = verify_session_export(
                exported,
                terminal_frames=[
                    str(frame["screen"])
                    for frame in timeline
                    if isinstance(frame, dict) and isinstance(frame.get("screen"), str)
                ],
                selected_models=spec.selected_models,
                reserved_usd=spec.campaign_reserve_usd,
                expected_event_counts=spec.expectations.get("event_counts"),
                expected_run_status_counts=spec.expectations.get("run_status_counts"),
                expected_question_kind=spec.expectations.get("question_kind"),
                expected_interrupt_ui=spec.expectations.get("interrupt_ui"),
                terminal_answer_required=spec.expectations.get(
                    "terminal_answer_required", True
                ),
                expected_task_count=spec.expectations.get("task_count"),
                max_provider_calls=spec.expectations.get("max_provider_calls"),
                observed_provider_call_ids=tuple(
                    step["provider_call"]["call_id"]
                    for step in timeline
                    if isinstance(step, dict)
                    and isinstance(step.get("provider_call"), dict)
                    and isinstance(step["provider_call"].get("call_id"), str)
                ),
            )
            verification["workspace"] = _verify_workspace_expectations(
                spec.workspace, before_manifest, after_manifest, spec.expectations
            )
            if verification["workspace"]["status"] == "failed":
                verification["status"] = "failed"
                verification["failed_checks"].append("workspace_expectations")
            if verification["status"] == "failed":
                failure = failure or (
                    "independent evidence verification failed: "
                    + ", ".join(verification["failed_checks"])
                )
        except Exception as exc:
            failure = failure or f"{type(exc).__name__}: independent evidence verification failed"
            verification = {
                "status": "failed",
                "error": redact(str(exc), secrets),
            }
        summary = {
            "schema_version": 1,
            "scenario_id": spec.scenario_id,
            "status": "failed" if failure else "captured",
            "started_at": started_at,
            "finished_at": datetime.now(UTC).isoformat(),
            "argv": list(spec.argv),
            "workspace": str(spec.workspace),
            "source_root": str(ROOT),
            "fixture_trust_returncode": fixture_trust_returncode,
            "session_id": exported_session_id,
            "terminal": {"backend": "winpty", "rows": spec.rows, "columns": spec.columns},
            "provider_credential_names": sorted(credentials),
            "budget_usd": format(spec.budget_usd, "f"),
            "campaign_reserve_usd": format(spec.campaign_reserve_usd, "f"),
            "selected_models": list(spec.selected_models),
            "lead_model": spec.lead_model,
            "capability_profiles": [
                {
                    "provider": profile["provider"],
                    "model": profile["model"],
                    "source": profile["source"],
                    "as_of": profile["as_of"],
                    "trusted": profile["trusted"],
                    "provenance": profile["provenance"],
                }
                for profile in spec.capability_profiles
            ],
            "failure": failure,
            "verification": verification,
        }
        summary = _redact_value(summary, secrets)
        (evidence_dir / "run.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (evidence_dir / "terminal.ansi.txt").write_text(
            redact(transcript, secrets), encoding="utf-8"
        )
        (evidence_dir / "terminal.screen.txt").write_text(
            redact(final_screen, secrets), encoding="utf-8"
        )
        (evidence_dir / "steps.json").write_text(
            json.dumps(_redact_value(timeline, secrets), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _write_json(evidence_dir / "workspace-before.json", before_manifest)
        _write_json(evidence_dir / "workspace-after.json", after_manifest)
        local_cost = verification.get("local_token_cost_usd")
        settled_cost = Decimal(local_cost) if isinstance(local_cost, str) else None
        _finish_campaign(
            campaign_ledger,
            spec.scenario_id,
            "failed" if failure else "captured",
            settled_cost,
        )
        home_context.cleanup()
    print(f"LIVE {'FAILED' if failure else 'CAPTURED'}: evidence={evidence_dir}")
    return 1 if failure else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture one isolated live Skail TUI scenario")
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--campaign-ledger", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        document = json.loads(args.spec.read_text(encoding="utf-8"))
        spec = validate_spec(document, campaign_cap=CAMPAIGN_CAP_USD)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"LIVE BLOCKED: invalid scenario setup ({type(exc).__name__})", file=sys.stderr)
        return 2
    return run_scenario(spec, args.evidence_dir, args.campaign_ledger)


if __name__ == "__main__":
    raise SystemExit(main())
