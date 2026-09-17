"""Onboarding cockpit widgets for first-run interactive sessions.

Draft source: docs/skail/TUI_REVAMP_DRAFT.md sections 8.2-8.3.
Pure copy/state lives in :mod:`skail.tui.onboarding`; this module only
renders it. Key material is never rendered, logged, or stored here beyond
a fixed-length mask.
"""

from __future__ import annotations

from rich.text import Text
from textual.binding import Binding
from textual.widgets import Input, Static

from skail.tui.onboarding import (
    KEY_ENTRY_COPY,
    PROVIDER_OPTIONS,
    VALIDATING_COPY,
    WELCOME_COPY,
    BootstrapCredentials,
    OnboardingState,
    mask_key,
    provider_display_name,
    provider_key_prompt,
    ready_receipt,
    trust_copy,
)

_FAKE_HINT = "For local evaluation without credentials, choose Fake provider"


class OnboardingPanel(Static):
    """Setup-cockpit panel rendering the current onboarding step."""

    can_focus = True

    BINDINGS = [
        Binding("enter", "onboarding_confirm", "Continue"),
        Binding("escape", "onboarding_back", "Back"),
        Binding("f", "onboarding_fake", "Fake provider"),
        Binding("t", "onboarding_trust", "Trust folder"),
        Binding("r", "onboarding_restricted", "Restricted mode"),
        Binding("b", "onboarding_back", "Back"),
        Binding("v", "onboarding_validate", "Validate"),
    ]

    def __init__(
        self,
        state: OnboardingState,
        credentials: BootstrapCredentials | None = None,
        renderable: str = "",
        workspace: str = "",
        session_id: str = "",
        name: str | None = None,
        id: str | None = "onboarding-panel",
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(
            renderable, name=name, id=id, classes=classes, disabled=disabled
        )
        self.onboarding = state
        self.credentials = credentials or BootstrapCredentials()
        self.workspace = workspace
        self.session_id = session_id

    def render_step(self) -> Text:
        """Render the active step as plain text (no secrets, no hex)."""
        step = self.onboarding.step
        text = Text()
        text.append(f"SETUP  {self._ladder_line()}\n\n", style="bold")
        if step == "welcome":
            text.append(WELCOME_COPY + "\n")
            text.append("\n[Enter] Continue   [F] Fake provider   [Ctrl+C] Quit")
        elif step == "provider":
            text.append(self._provider_copy() + "\n")
        elif step == "trust":
            text.append(trust_copy(self.workspace or ".") + "\n")
        elif step == "theme":
            text.append(self._theme_copy() + "\n")
        else:
            text.append(self._ready_copy() + "\n")
            text.append("\n[Enter] Open cockpit")
        return text

    def _ladder_line(self) -> str:
        order = ("welcome", "provider", "trust", "theme", "ready")
        labels = ("1 Welcome", "2 Provider", "3 Trust", "4 Theme", "5 Ready")
        parts = []
        for name, label in zip(order, labels, strict=True):
            marker = "●" if name == self.onboarding.step else "∙"
            parts.append(f"{marker} {label}")
        return "  ".join(parts)

    def _provider_copy(self) -> str:
        lines = ["CHOOSE A PROVIDER", ""]
        for option in PROVIDER_OPTIONS:
            marker = "●" if option == self.onboarding.provider else " "
            lines.append(f"{marker} {provider_display_name(option)}")
        lines.append("")
        if self.onboarding.provider == "fake":
            lines.append(_FAKE_HINT)
            lines.append("or restart with: skail --fake-provider")
            lines.append("")
            lines.append("[Enter] Continue   [B] Back")
            return "\n".join(lines)
        lines.append("")
        lines.append(provider_key_prompt(self.onboarding.provider))
        lines.append("")
        masked = mask_key(self.credentials.reveal())
        lines.append(f"Key: {masked or '(not entered)'}")
        lines.append("")
        lines.append(KEY_ENTRY_COPY)
        lines.append("")
        if self.onboarding.validating:
            lines.append(VALIDATING_COPY)
        elif self.onboarding.validation_error:
            lines.append(self.onboarding.validation_error)
            lines.append("")
            lines.append("[V] Retry   [B] Back")
        else:
            lines.append("[V] Validate   [B] Back")
        return "\n".join(lines)

    def _theme_copy(self) -> str:
        lines = ["THEME", ""]
        for option in ("dark", "light", "system"):
            marker = "●" if option == self.onboarding.theme else " "
            lines.append(f"{marker} {option.capitalize()}")
        lines.append("")
        lines.append("Preview")
        lines.append("surface  text  accent  approval  error  agents")
        lines.append("")
        lines.append("Enter apply   Esc restore previous")
        return "\n".join(lines)

    def _ready_copy(self) -> str:
        return ready_receipt(
            provider=self.onboarding.provider,
            trusted=self.onboarding.trusted,
            theme=self.onboarding.theme,
            mode=self.onboarding.mode,
            session_id=self.session_id or "new",
        )

    def refresh_step(self) -> None:
        """Re-render after external state changes and sync the key field."""
        self.update(self.render_step())
        self._sync_key_input()

    def _sync_key_input(self) -> None:
        has_input = self._key_input() is not None
        if self.onboarding.step == "provider" and self.onboarding.provider != "fake":
            if not has_input:
                self.mount(Input(password=True, id="onboarding-key"))
        elif has_input:
            input_widget = self._key_input()
            if input_widget is not None:
                input_widget.remove()

    def _key_input(self) -> Input | None:
        try:
            return self.query_one("#onboarding-key", Input)
        except Exception:
            return None

    def on_mount(self) -> None:
        self.update(self.render_step())
        self._sync_key_input()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "onboarding-key":
            self.credentials.set_key(event.value)
            self.update(self.render_step())

    def _app_action(self, name: str) -> None:
        action = getattr(self.app, name, None)
        if callable(action):
            action()

    def action_onboarding_confirm(self) -> None:
        self._app_action("onboarding_confirm")

    def action_onboarding_back(self) -> None:
        self._app_action("onboarding_back")

    def action_onboarding_fake(self) -> None:
        self._app_action("onboarding_choose_fake")

    def action_onboarding_trust(self) -> None:
        self._app_action("onboarding_trust_folder")

    def action_onboarding_restricted(self) -> None:
        self._app_action("onboarding_restricted_mode")

    def action_onboarding_validate(self) -> None:
        self._app_action("validate_onboarding_key")


__all__ = ["OnboardingPanel"]
