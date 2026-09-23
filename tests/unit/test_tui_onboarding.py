"""Phase 1 onboarding ladder tests (draft sections 8.3, 13.2-13.3)."""

from __future__ import annotations

from pathlib import Path

from skail.config.onboarding import (
    OnboardingReceipt,
    load_onboarding_receipt,
    save_onboarding_receipt,
)
from skail.tui.onboarding import (
    KEY_ENTRY_COPY,
    NON_TTY_USAGE_ERROR,
    PROVIDER_CHOOSER_COPY,
    READY_RECEIPT_TEMPLATE,
    STEP_ORDER,
    TRUST_RECEIPT_RESTRICTED,
    TRUST_RECEIPT_TRUSTED,
    VALIDATING_COPY,
    VALIDATION_FAILURE_COPY,
    VALIDATION_SUCCESS_COPY,
    WELCOME_COPY,
    BootstrapCredentials,
    OnboardingState,
    has_env_credentials,
    mask_key,
    provider_key_prompt,
    ready_receipt,
    trust_copy,
    validation_success,
)


def test_step_order_is_five_step_ladder() -> None:
    assert STEP_ORDER == ("welcome", "provider", "trust", "theme", "ready")


def test_welcome_copy_is_exact() -> None:
    assert "Welcome to Skail." in WELCOME_COPY
    assert "Connect a provider" in WELCOME_COPY


def test_provider_chooser_copy_lists_only_live_providers() -> None:
    assert "CHOOSE A PROVIDER" in PROVIDER_CHOOSER_COPY
    assert "LLM Gateway" in PROVIDER_CHOOSER_COPY
    assert "OpenAI" in PROVIDER_CHOOSER_COPY
    assert "Anthropic" in PROVIDER_CHOOSER_COPY
    assert "Fake provider" not in PROVIDER_CHOOSER_COPY


def test_key_entry_copy_never_written() -> None:
    assert "never written to" in KEY_ENTRY_COPY
    for location in ("session", "transcript", "event stream", "logs"):
        assert location in KEY_ENTRY_COPY


def test_validation_copies_are_exact() -> None:
    assert VALIDATING_COPY == "Validating…"
    assert VALIDATION_FAILURE_COPY == (
        "Validation failed. Check the key and network access, then retry."
    )
    assert validation_success("llmgateway") == (
        "Provider validated. LLM Gateway is ready."
    )
    assert VALIDATION_SUCCESS_COPY == "Provider validated. {provider} is ready."


def test_trust_copy_names_resolved_path_and_boundaries() -> None:
    copy = trust_copy("/repo/workspace")
    assert "TRUST THIS FOLDER?" in copy
    assert "/repo/workspace" in copy
    assert "Trust does not bypass tool approvals" in copy
    assert "[T] Trust this folder" in copy
    assert "[R] Restricted mode" in copy
    assert TRUST_RECEIPT_TRUSTED.startswith("Workspace trusted: ")
    assert TRUST_RECEIPT_RESTRICTED == "Workspace opened in restricted mode."


def test_ready_receipt_contains_resume_command() -> None:
    receipt = ready_receipt(
        provider="llmgateway",
        trusted=True,
        theme="dark",
        mode="quality",
        session_id="01JABC",
    )
    assert receipt == READY_RECEIPT_TEMPLATE.format(
        provider="LLM Gateway",
        workspace_state="trusted",
        theme="Dark",
        mode="Quality",
        session_id="01JABC",
    )
    assert "skail -r 01JABC" in receipt
    assert "[Enter] Open cockpit" in receipt


def test_mask_key_is_fixed_length() -> None:
    assert mask_key("") == ""
    assert mask_key("short") == "•" * 42
    assert mask_key("x" * 100) == "•" * 42


def test_provider_key_prompt_labels() -> None:
    assert provider_key_prompt("llmgateway") == "LLM Gateway API key"
    assert provider_key_prompt("openai") == "OpenAI API key"
    assert provider_key_prompt("anthropic") == "Anthropic API key"


def test_bootstrap_credentials_in_memory_only() -> None:
    creds = BootstrapCredentials(provider="llmgateway")
    assert not creds.has_key()
    creds.set_key("secret-key-material")
    assert creds.has_key()
    assert creds.reveal() == "secret-key-material"
    assert "secret-key-material" not in repr(creds)
    assert "<redacted>" in repr(creds)
    creds.clear()
    assert not creds.has_key()
    assert creds.reveal() == ""


def test_onboarding_state_advance_and_back_clamp() -> None:
    state = OnboardingState()
    assert state.step == "welcome"
    for expected in ("provider", "trust", "theme", "ready"):
        state.advance()
        assert state.step == expected
    state.advance()
    assert state.step == "ready"
    for expected in ("theme", "trust", "provider", "welcome"):
        state.go_back()
        assert state.step == expected
    state.go_back()
    assert state.step == "welcome"


def test_device_onboarding_receipt_persists_only_non_secret_choices(tmp_path: Path) -> None:
    path = tmp_path / "onboarding.json"
    receipt = OnboardingReceipt(
        completed=True,
        provider="openai",
        selected_model="openai:gpt-4o-mini",
        enabled_models=("openai:gpt-4o-mini",),
        theme="pistachio-night",
    )

    save_onboarding_receipt(receipt, path=path)
    loaded = load_onboarding_receipt(path=path)

    assert loaded == receipt
    raw = path.read_text(encoding="utf-8")
    assert "api_key" not in raw.lower()
    assert "secret" not in raw.lower()


def test_has_env_credentials_precedence() -> None:
    assert not has_env_credentials({})
    assert has_env_credentials({"LLMGATEWAY_API_KEY": "x"})
    assert has_env_credentials({"OPENAI_API_KEY": "x"})
    assert has_env_credentials({"ANTHROPIC_API_KEY": "x"})
    assert not has_env_credentials({"LLMGATEWAY_API_KEY": ""})


def test_non_tty_usage_error_is_exact() -> None:
    assert NON_TTY_USAGE_ERROR == (
        "skail: interactive mode requires a TTY.\n"
        'Use `skail -p "<prompt>"` for headless execution, `skail --jsonl` for\n'
        "machine-readable output, or run `skail` in an interactive terminal."
    )
    assert "ready" not in NON_TTY_USAGE_ERROR
