"""Five-step onboarding ladder for first-run interactive sessions.

Steps: welcome -> provider -> trust -> theme -> ready. Key material lives
only in :class:`BootstrapCredentials` (in-memory, redacted repr) and is
never placed in reactive state, snapshots, events, transcripts, or logs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

OnboardingStep = Literal["welcome", "provider", "trust", "theme", "ready"]

STEP_ORDER: tuple[OnboardingStep, ...] = (
    "welcome",
    "provider",
    "trust",
    "theme",
    "ready",
)

WELCOME_COPY = (
    "Welcome to Skail.\n"
    "\n"
    "Connect a provider, choose your models, and confirm workspace access."
)

PROVIDER_CHOOSER_COPY = (
    "CHOOSE A PROVIDER\n"
    "\n"
    "● LLM Gateway\n"
    "  OpenAI\n"
    "  Anthropic\n"
    "\n"
    "Use ↑/↓ to choose, then enter a key and validate it."
)

PROVIDER_OPTIONS: tuple[str, ...] = ("llmgateway", "openai", "anthropic")

KEY_ENTRY_COPY = (
    "The key is held in memory for this process and is never written to the\n"
    "session, transcript, event stream, or logs."
)

VALIDATING_COPY = "Validating…"
VALIDATION_SUCCESS_COPY = "Provider validated. {provider} is ready."
VALIDATION_FAILURE_COPY = (
    "Validation failed. Check the key and network access, then retry."
)

TRUST_COPY_TEMPLATE = (
    "TRUST THIS FOLDER?\n"
    "\n"
    "{workspace}\n"
    "\n"
    "Trusted folders may allow approved shell and filesystem operations within\n"
    "the configured workspace boundary. Trust does not bypass tool approvals,\n"
    "secret redaction, or workspace writer locks.\n"
    "\n"
    "[T] Trust this folder\n"
    "[R] Restricted mode\n"
    "[B] Back"
)

TRUST_RECEIPT_TRUSTED = "Workspace trusted: {workspace}"
TRUST_RECEIPT_RESTRICTED = "Workspace opened in restricted mode."

READY_RECEIPT_TEMPLATE = (
    "READY\n"
    "\n"
    "Provider     {provider}\n"
    "Workspace    {workspace_state}\n"
    "Theme        {theme}\n"
    "Mode         {mode}\n"
    "Session      {session_id}\n"
    "\n"
    "Resume this session later with:\n"
    "skail -r {session_id}\n"
    "\n"
    "[Enter] Open cockpit"
)

NON_TTY_USAGE_ERROR = (
    "skail: interactive mode requires a TTY.\n"
    'Use `skail -p "<prompt>"` for headless execution, `skail --jsonl` for\n'
    "machine-readable output, or run `skail` in an interactive terminal."
)


@dataclass
class BootstrapCredentials:
    """Narrow in-memory holder for an onboarding-entered API key."""

    provider: str = ""
    _key: str = field(default="", repr=False)

    def set_key(self, key: str) -> None:
        """Store key material in process memory only."""
        self._key = key

    def reveal(self) -> str:
        """Return key material to the runtime factory only."""
        return self._key

    def has_key(self) -> bool:
        """Whether key material is present."""
        return bool(self._key)

    def clear(self) -> None:
        """Drop key material once runtime construction has consumed it."""
        self._key = ""

    def __repr__(self) -> str:  # pragma: no cover - trivial redaction guard
        return f"BootstrapCredentials(provider={self.provider!r}, key=<redacted>)"


@dataclass
class OnboardingState:
    """Serializable-safe onboarding progress; never carries key material."""

    step: OnboardingStep = "welcome"
    provider: str = "llmgateway"
    workspace: str = ""
    trusted: bool | None = None
    theme: str = "system"
    mode: str = "Quality"
    session_id: str = ""
    validation_error: str | None = None
    validating: bool = False

    def advance(self) -> None:
        """Move one step forward, clamping at the final step."""
        index = STEP_ORDER.index(self.step)
        if index < len(STEP_ORDER) - 1:
            self.step = STEP_ORDER[index + 1]

    def go_back(self) -> None:
        """Move one step back, clamping at the first step."""
        index = STEP_ORDER.index(self.step)
        if index > 0:
            self.step = STEP_ORDER[index - 1]


def mask_key(key: str) -> str:
    """Return a fixed-length mask regardless of key length."""
    if not key:
        return ""
    return "•" * 42


def provider_key_prompt(provider: str) -> str:
    """Heading for the masked key entry for a live provider."""
    label = {
        "llmgateway": "LLM Gateway",
        "openai": "OpenAI",
        "anthropic": "Anthropic",
    }.get(provider, provider)
    return f"{label} API key"


def provider_display_name(provider: str) -> str:
    """Human-readable provider name for receipts."""
    return {
        "llmgateway": "LLM Gateway",
        "openai": "OpenAI",
        "anthropic": "Anthropic",
    }.get(provider, provider)


def trust_copy(workspace: str | Path) -> str:
    """Trust-step copy naming the exact resolved workspace path."""
    return TRUST_COPY_TEMPLATE.format(workspace=str(workspace))


def ready_receipt(
    *,
    provider: str,
    trusted: bool | None,
    theme: str,
    mode: str,
    session_id: str,
) -> str:
    """Ready-step receipt including the exact `skail -r <SESSION>` command."""
    workspace_state = "trusted" if trusted else "restricted"
    return READY_RECEIPT_TEMPLATE.format(
        provider=provider_display_name(provider),
        workspace_state=workspace_state,
        theme=theme.capitalize(),
        mode=mode.capitalize(),
        session_id=session_id,
    )


def validation_success(provider: str) -> str:
    """Success copy after async provider validation."""
    return VALIDATION_SUCCESS_COPY.format(provider=provider_display_name(provider))


def has_env_credentials(
    env: dict[str, str] | None = None,
    *,
    env_vars: tuple[str, ...] | None = None,
) -> bool:
    """Whether any supported provider key is present in the environment."""
    import os

    source = env if env is not None else os.environ
    names = env_vars or ("LLMGATEWAY_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
    return any(
        source.get(var)
        for var in names
    )
