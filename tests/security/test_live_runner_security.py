from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from scripts.live_check import (
    ALLOWED_CREDENTIALS,
    isolated_environment,
    parse_model_selection,
    read_allowlisted_env,
    redact,
)


def test_live_model_selection_is_unique_and_secret_independent() -> None:
    assert parse_model_selection(" gpt-4o-mini, gpt-4o-mini, gpt-4o ") == (
        "gpt-4o-mini",
        "gpt-4o",
    )
    assert parse_model_selection(None) == ()


def test_live_env_loader_only_returns_allowlisted_values_without_expansion(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "LLMGATEWAY_API_KEY=live-secret\n"
        "NOT_ALLOWED=do-not-read\n"
        "EXPANDED=$LLMGATEWAY_API_KEY\n",
        encoding="utf-8",
    )

    loaded = read_allowlisted_env(env, ALLOWED_CREDENTIALS)

    assert loaded == {"LLMGATEWAY_API_KEY": "live-secret"}


def test_live_diagnostics_redact_full_credentials() -> None:
    assert redact("provider=live-secret", ("live-secret",)) == "provider=[REDACTED]"


def test_live_child_environment_isolated_and_cap_bound(tmp_path: Path) -> None:
    env = isolated_environment(
        {"LLMGATEWAY_API_KEY": "secret"},
        tmp_path / "home",
        tmp_path / "evidence",
        cap=Decimal("1.00"),
    )

    assert env["LLMGATEWAY_API_KEY"] == "secret"
    assert env["HOME"] == str(tmp_path / "home")
    assert env["SKAIL_LIVE_MAX_COST_USD"] == "1.00"
    assert "NOT_ALLOWED" not in env
