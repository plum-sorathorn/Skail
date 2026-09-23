"""Phase 1 semantic shell and boot separation for SkailApp.

Interactive sessions mount the shell immediately; provider/model
construction happens in a Textual worker after the shell is visible.
Headless paths never touch this module.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Input, Static, TabbedContent, TabPane

from skail import __version__
from skail.agents.lead import DelegationMode, LeadControls
from skail.config.onboarding import (
    OnboardingReceipt,
    load_onboarding_receipt,
    save_onboarding_receipt,
)
from skail.domain.events import EventEnvelope, UserPayload
from skail.domain.ids import SessionId, new_event_id, new_run_id, new_session_id
from skail.domain.routing import RoutingMode
from skail.providers.credentials import (
    CredentialStore,
    CredentialStoreUnavailable,
    KeyringCredentialStore,
)
from skail.runtime.interrupts import QuestionStore
from skail.runtime.presentation import present_lead_answer
from skail.sessions.journal import SessionSnapshot
from skail.sessions.service import SessionService
from skail.tools.approvals import ApprovalChoice, ApprovalStore
from skail.tools.execution import CommandRequest
from skail.tui.commands import COMMAND_REGISTRY, dispatch_slash_command
from skail.tui.logo import COMPACT_MARK
from skail.tui.onboarding import (
    VALIDATION_FAILURE_COPY,
    BootstrapCredentials,
    OnboardingState,
    has_env_credentials,
)
from skail.tui.projection import InterruptItem, TranscriptItem, TuiProjection
from skail.tui.theme import (
    ThemeName,
    ThemeTokens,
    as_dict,
    budget_token_for_ratio,
    detect_system_preference,
    get_theme,
    lookup,
    reduced_motion_enabled,
    resolve_system_theme,
)
from skail.tui.widgets.agents import AgentRail
from skail.tui.widgets.budget import BudgetLedger, BudgetView
from skail.tui.widgets.chat import ActivitySpinner, ChatTranscript
from skail.tui.widgets.composer import PromptComposer
from skail.tui.widgets.footer import AtelierFooter
from skail.tui.widgets.interrupts import InterruptWidget
from skail.tui.widgets.onboarding import OnboardingPanel
from skail.tui.widgets.plan import PlanView
from skail.tui.widgets.route import RouteView

AppState = Literal[
    "onboarding",
    "initializing",
    "selection_required",
    "ready",
    "error",
    "quitting",
]

ACTION_REGISTRY: dict[str, dict[str, str]] = {
    "quit": {"binding": "ctrl+c", "description": "Quit", "group": "Session"},
    "view_chat": {
        "binding": "ctrl+shift+t",
        "description": "Chat (focus composer)",
        "group": "Navigation",
    },
    "show_help": {"binding": "f1", "description": "Help", "group": "Session"},
    "transcript_overlay": {
        "binding": "ctrl+o",
        "description": "Transcript",
        "group": "Display",
    },
    "shortcuts_overlay": {
        "binding": "?",
        "description": "Shortcuts",
        "group": "Display",
    },
    "theme_picker": {"binding": "alt+t", "description": "Theme picker", "group": "Display"},
    "missions_overlay": {"binding": "ctrl+t", "description": "Missions", "group": "Agents"},
    "agent_detail": {"binding": "enter", "description": "Agent detail", "group": "Agents"},
    "agent_missions": {"binding": "m", "description": "Mission Control", "group": "Agents"},
    "cycle_panels": {
        "binding": "shift+tab",
        "description": "Cycle panels (composer stays focused)",
        "group": "Navigation",
    },
    "model_picker": {"binding": "alt+p", "description": "Model picker", "group": "Run"},
    "composer_submit": {"binding": "enter", "description": "Send prompt", "group": "Composer"},
    "composer_queue": {
        "binding": "ctrl+enter",
        "description": "Queue prompt",
        "group": "Composer",
    },
    "approve": {"binding": "y", "description": "Approve", "group": "Approvals"},
    "deny": {"binding": "n", "description": "Reject", "group": "Approvals"},
}

_PROVIDER_ENV_VARS = {
    "llmgateway": "LLMGATEWAY_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}

_READY_COPY = "Describe the outcome you want, paste an error, or type /help."
_RUNTIME_ERROR_COPY = (
    "RUNTIME COULD NOT START\n\nYour session is safe. No agent run was started.\n"
    "Review provider settings or retry initialization.\n\n[R] Retry   [S] Setup   [Q] Quit"
)

def clean_lead_output(output: str) -> str:
    """Render the user-facing answer without flattening verification evidence."""
    return present_lead_answer(output)


def format_masthead(version: str, provider_label: str | None, clock: str) -> str:
    """Return the ATELIER masthead row: letterspaced wordmark, version, provider, clock."""
    wordmark = COMPACT_MARK
    provider = f"  {provider_label}" if provider_label else ""
    return f"{wordmark}  {version}{provider}"


_DATELINE_METER_CELLS = 10

_MODE_TOKENS = {"quality": "modeQuality", "economy": "modeEconomy", "manual": "modeManual"}


def render_dateline(
    model: str,
    mode: str,
    cost: str,
    ratio: float | None,
    active: int,
    running: int,
    queued: int,
    badge: str | None = None,
    badge_token: str = "textMuted",
    active_mode: str = "direct",
    narrow: bool = False,
) -> str:
    """Return the ATELIER dateline: MODEL / MODE / SPEND / AGENTS in token markup.

    With ``narrow=True`` the markup wraps into two rows joined by a newline:
    row 1 = MODEL/MODE (plus badge) + ``●N running``; row 2 = SPEND + meter +
    ``N queued`` (mock narrow frame, plan §8.3).
    """
    if ratio is None:
        pct = "0.0"
        fill = 0
        fill_token = "budgetEmpty"
    else:
        pct = f"{ratio * 100:.1f}"
        fill = min(_DATELINE_METER_CELLS, round(ratio * _DATELINE_METER_CELLS))
        fill_token = budget_token_for_ratio(ratio)
    rest = _DATELINE_METER_CELLS - fill
    mode_token = _MODE_TOKENS.get(mode, "modeQuality")
    segments: list[str] = []
    if badge:
        segments.append(f"[{badge_token}]{badge}[/]")
    segments.append(
        f"[textFaint]MODEL[/] [text]{model}[/] [textFaint]·  MODE[/] [{mode_token}]{mode}[/]"
    )
    if active_mode != "direct":
        segments.append(f"[delegation][[{active_mode}][/]")
    segments.append(
        f"[textFaint]·  SPEND[/] [text]{cost}[/] [{fill_token}]{'▓' * fill}[/]"
        f"[budgetEmpty]{'░' * rest}[/] {pct}%"
    )
    segments.append(
        f"[textFaint]·  AGENTS[/] [agentOne]●{active}[/] "
        f"[textMuted]{running} running · {queued} queued[/]"
    )
    if narrow:
        # §8.3 narrow: row 1 = MODEL/MODE (+badge, delegation) + ●N running;
        # row 2 = SPEND + meter + queued (AGENTS label rides with queued).
        head = [*segments[:-2], f"[agentOne]●{active}[/] [textMuted]{running} running[/]"]
        tail = segments[-2] + f" [textFaint]·  AGENTS[/] [textMuted]{queued} queued[/]"
        return " ".join(head) + "\n" + tail
    return " ".join(segments)


def render_transcript_header(run_id: str | None, event_count: int, pinned: bool) -> str:
    """Return the ATELIER transcript header: letterspaced TRANSCRIPT + faint run state."""
    left = "T R A N S C R I P T"
    segments: list[str] = []
    if run_id:
        segments.append(f"run-{run_id}")
    segments.append(f"{event_count} events")
    if pinned:
        segments.append("pinned")
    right = " · ".join(segments)
    return f"{left}  [textFaint]{right}[/]"


_MARGIN_DRAWER_KEYS = ("⇧TAB",)


def render_margin_drawer(active_tab: str) -> str:
    """Return the narrow #margin-drawer: letterspaced active tab + faint kbd chips."""
    label = " ".join(active_tab.upper())
    chips = "  ".join(
        f"[on $surfaceRaised] [textFaint]{key}[/] [/]" for key in _MARGIN_DRAWER_KEYS
    )
    return f"[text]{label}[/]  [textFaint]…[/]  {chips}"


class SkailApp(App[int]):
    """Main Textual interactive application for Skail harness."""

    TITLE = f"{COMPACT_MARK} Skail {__version__}"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen {
        layout: vertical;
        background: $surface;
        color: $text;
    }
    Screen.theme-light {
        background: $surface;
        color: $text;
    }
    #main-container {
        width: 100%;
        height: 1fr;
    }
    #chat-container {
        width: 1fr;
        height: 100%;
        padding-right: 2;
    }
    #transcript-header {
        width: 100%;
        height: 1;
        padding: 0 1;
        border-bottom: solid $border;
        color: $textMuted;
    }
    #activity-spinner {
        display: none;
        width: 100%;
        height: 1;
        padding: 0 1;
        color: $accent;
    }
    #sidebar-container {
        width: 39;
        height: 100%;
        padding-left: 2;
    }
    .hairline {
        width: 1;
        height: 100%;
        background: $border;
    }
    .narrow .hairline {
        display: none;
    }
    .narrow #hairline {
        display: none;
    }
    #tabs {
        height: 1fr;
        background: $surface;
    }
    #tabs ContentSwitcher,
    #tabs TabPane {
        height: 1fr;
    }
    #tabs Tabs {
        background: $surface;
    }
    #tabs Tab {
        color: $textFaint;
        background: $surface;
        padding: 0 1;
    }
    #tabs Tab.-active {
        color: $text;
        background: $surface;
        text-style: bold;
    }
    #tabs .underline--bar {
        color: $accent;
    }
    #interrupt-container {
        width: 100%;
        height: auto;
    }
    .narrow #chat-container {
        width: 100%;
        border-right: none;
        padding-right: 0;
    }
    .narrow #sidebar-container {
        display: none;
    }
    .wide #chat-container {
        width: 1fr;
    }
    .wide #sidebar-container {
        display: block;
    }
    #margin-drawer {
        display: none;
        width: 100%;
        height: 1;
        padding: 0 1;
        background: $surface;
        color: $textMuted;
    }
    .narrow #margin-drawer {
        display: block;
    }
    .narrow #dateline {
        height: 2;
    }
    .narrow .msg-clock {
        display: none;
    }
    .narrow .msg-role {
        width: 11;
    }
    .reduced-motion * {
        transition: none;
    }
    #dateline {
        width: 100%;
        height: 1;
        padding: 0 1;
        background: $surface;
        border-bottom: solid $border;
        color: $textMuted;
    }
    #masthead {
        width: 100%;
        height: 1;
        padding: 0 1;
        background: $surface;
        color: $text;
    }
    .rule-strong {
        height: 1;
        border-bottom: double $borderStrong;
    }
    Screen:focus-within {
        outline: solid $focusRing;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", priority=True),
        Binding("ctrl+t", "missions_overlay", "Missions (Ctrl+T)"),
        Binding("ctrl+shift+t", "view_chat", "Chat"),
        Binding("ctrl+o", "transcript_overlay", "Transcript (Ctrl+O)"),
        Binding("question_mark", "shortcuts_overlay", "Shortcuts (?)"),
        Binding("alt+t", "theme_picker", "Theme"),
        Binding("alt+p", "model_picker", "Model"),
        Binding("ctrl+space", "model_picker_toggle", show=False, priority=True),
        Binding("ctrl+shift+a", "model_picker_toggle_all", show=False, priority=True),
        Binding("shift+tab", "cycle_panels", "Cycle panels", priority=True),
        Binding("f1", "show_help", "Help"),
    ]

    def __init__(
        self,
        projection: TuiProjection | None = None,
        background_supported: bool = False,
        controller: Any | None = None,
        session_service: SessionService | None = None,
        session_id: SessionId | None = None,
        approval_store: ApprovalStore | None = None,
        question_store: QuestionStore | None = None,
        initial_prompt: str | None = None,
        max_children: int = 3,
        delegation: DelegationMode = "auto",
        initial_snapshot: SessionSnapshot | None = None,
        runtime_factory: Callable[[], Any] | None = None,
        bootstrap: dict[str, Any] | None = None,
        journal: Any | None = None,
        checkpoints: Any | None = None,
        redaction: Any | None = None,
        profile_models: dict[str, str] | None = None,
        theme_name: ThemeName = "system",
        reduced_motion: bool | None = None,
    ) -> None:
        self.bootstrap: dict[str, Any] = dict(bootstrap or {})
        onboarding_path_value = self.bootstrap.get("onboarding_path")
        try:
            self.onboarding_receipt = (
                load_onboarding_receipt(path=Path(onboarding_path_value))
                if onboarding_path_value
                else OnboardingReceipt()
            )
        except ValueError:
            self.onboarding_receipt = OnboardingReceipt()
        persisted_theme = (
            self.onboarding_receipt.theme
            if self.onboarding_receipt.completed
            else theme_name
        )
        self.current_theme_name: ThemeName = persisted_theme  # type: ignore[assignment]
        if persisted_theme == "system":
            self.current_tokens = resolve_system_theme(
                detect_system_preference()
            )[0]
        else:
            self.current_tokens = get_theme(persisted_theme)  # type: ignore[arg-type]
        super().__init__()
        self.projection = projection or TuiProjection()
        self.background_supported = background_supported
        self.controller = controller
        self.session_service = session_service
        self.session_id = session_id
        self.approval_store = approval_store
        self.question_store = question_store
        self.initial_prompt = initial_prompt
        self.max_children = max_children
        self.delegation = delegation
        self.initial_snapshot = initial_snapshot
        self.runtime_factory = runtime_factory
        self.journal = journal
        self.checkpoints = checkpoints
        self.redaction = redaction
        self.profile_models = profile_models or {}
        self.simulated: bool = False
        self._active_worker: Any = None
        self._run_active = False
        self._pending_prompts: deque[str] = deque()
        self._mounted: bool = False
        self.app_state: AppState = "ready"
        self.startup_error: str | None = None
        self.onboarding_state = OnboardingState(
            step=(
                "ready"
                if self.onboarding_receipt.completed
                and bool(self.bootstrap.get("project_trusted", False))
                else "trust"
                if self.onboarding_receipt.completed
                else "welcome"
            ),
            provider=(
                self.onboarding_receipt.provider
                if self.onboarding_receipt.completed
                else str(self.bootstrap.get("provider", "llmgateway"))
            ),
            workspace=str(self.bootstrap.get("workspace", "")),
            session_id=str(self.bootstrap.get("session_id", "")),
            theme=persisted_theme,
        )
        self._enabled_models: set[str] = (
            set(self.onboarding_receipt.enabled_models)
            if self.onboarding_receipt.completed
            else set()
        )
        self.onboarding_credentials = BootstrapCredentials()
        self._previous_theme: str = self.onboarding_state.theme
        self.reduced_motion = reduced_motion_enabled(reduced_motion)
        self._overlay_stack: list[str] = []
        self._focus_before_overlay: Any = None
        if self.controller is not None:
            self.controller.subscribe_events(self.apply_event)
            self.app_state = "ready"
        elif self.runtime_factory is not None:
            if self.onboarding_receipt.completed and not bool(
                self.bootstrap.get("project_trusted", False)
            ):
                self.app_state = "onboarding"
            elif self.onboarding_receipt.completed and bool(
                self.bootstrap.get("project_trusted", False)
            ) and self._provider_credential_available():
                self.app_state = "initializing"
            elif has_env_credentials(
                env_vars=tuple(self.bootstrap.get("credential_envs", ())) or None
            ):
                self.app_state = "initializing"
            else:
                self.app_state = "onboarding"

    def compose(self) -> ComposeResult:
        yield Static(id="masthead")
        yield Static(id="rule-strong", classes="rule-strong")
        yield Static(self._render_status_strip(), id="dateline")
        with Horizontal(id="main-container"):
            with Vertical(id="chat-container"):
                yield Static(id="transcript-header")
                yield ActivitySpinner("RUNNING", id="activity-spinner")
                yield ChatTranscript(id="chat-transcript")
            yield Static(id="hairline", classes="hairline")
            with Vertical(id="sidebar-container"):
                with TabbedContent(initial="tab-agents", id="tabs"):
                    with TabPane("Agents", id="tab-agents"):
                        yield AgentRail(id="agent-rail")
                    with TabPane("Plan", id="tab-plan"):
                        yield PlanView(id="plan-view")
                    with TabPane("Route", id="tab-route"):
                        yield RouteView(id="route-view")
                    with TabPane("Budget", id="tab-budget"):
                        yield BudgetView(id="budget-view")
                yield BudgetLedger(id="budget-ledger")
        yield Static(render_margin_drawer("Agents"), id="margin-drawer")
        yield Container(id="interrupt-container")
        yield PromptComposer(id="prompt-composer")
        yield AtelierFooter(id="app-footer")

    def on_mount(self) -> None:
        self._mounted = True
        self.set_interval(1.0, self._tick_masthead)
        self.apply_theme(self.current_theme_name)
        try:
            self.query_one("#app-footer", AtelierFooter).set_bindings(
                [
                    (binding.key, binding.description)
                    for binding in self.BINDINGS
                    if isinstance(binding, Binding)
                ]
            )
        except Exception:
            pass
        if self.initial_snapshot is not None:
            self.projection.apply_snapshot(self.initial_snapshot)
        if self.controller is not None and self.controller.pending_interrupt is not None:
            self._set_interrupt(
                self.controller.pending_interrupt,
                run_id=str(self.initial_snapshot.runs[-1].run_id)
                if self.initial_snapshot and self.initial_snapshot.runs
                else "restored",
            )
        if self.app_state == "onboarding":
            self._mount_onboarding()
        elif self.app_state == "initializing":
            self.update_views()
            self._start_runtime_worker()
        else:
            self.update_views()
        self._make_panels_passive()
        self._check_screen_width()
        if self.initial_prompt and self.app_state == "ready":
            self.on_prompt_composer_prompt_submitted(
                PromptComposer.PromptSubmitted(self.initial_prompt)
            )

    def on_resize(self) -> None:
        self._check_screen_width()

    def _check_screen_width(self) -> None:
        try:
            container = self.query_one("#main-container")
        except Exception:
            return
        narrow = self.size.width < 100
        if narrow:
            container.add_class("narrow")
            container.remove_class("wide")
        else:
            container.add_class("wide")
            container.remove_class("narrow")
        try:
            screen = container.screen
        except Exception:
            return
        was_narrow = screen.has_class("narrow")
        if narrow:
            screen.add_class("narrow")
            screen.remove_class("wide")
        else:
            screen.add_class("wide")
            screen.remove_class("narrow")
        # §8.3: the hidden/shown state must be observable via Widget.visible, which in
        # Textual 1.0.0 tracks the visibility flag, not the TCSS display rule.
        try:
            self.query_one("#hairline").visible = not narrow
            self.query_one("#sidebar-container").visible = not narrow
            self.query_one("#margin-drawer").visible = narrow
        except Exception:
            pass
        if narrow != was_narrow and self._mounted:
            # Narrow flips the #dateline markup (1 <-> 2 rows); re-render it now.
            try:
                self.query_one("#dateline", Static).update(self._render_status_strip())
            except Exception:
                pass
        try:
            self.query_one("#app-footer", AtelierFooter).narrow = narrow
        except Exception:
            pass

    def _make_panels_passive(self) -> None:
        """Keep the composer as the only focus owner on the main screen."""
        try:
            tabs = self.query_one("#tabs", TabbedContent)
            tabs.can_focus = False
            tabs.can_focus_children = False
            tabs_widget = tabs.query_one("Tabs")
            tabs_widget.can_focus = False
            tabs_widget.disabled = True
        except Exception:
            pass

    # -- theme -----------------------------------------------------------
    def get_css_variables(self) -> dict[str, str]:
        """Expose semantic theme tokens as Textual CSS variables."""
        base = super().get_css_variables()
        tokens = getattr(self, "current_tokens", None)
        if tokens is None:
            try:
                tokens = get_theme("dark")
            except KeyError:
                return base
        for name, value in as_dict(tokens).items():
            base[f"--{name}"] = value
            base[name] = value
        try:
            base["focusRing"] = lookup(tokens, "focusRing")
        except KeyError:
            pass
        return base

    def apply_theme(self, name: ThemeName) -> ThemeTokens:
        """Apply a theme by name; system falls back to Dark and says so."""
        self.current_theme_name = name
        if name == "system":
            tokens, _ = resolve_system_theme(detect_system_preference())
        else:
            tokens = get_theme(name)
        self.current_tokens = tokens
        if self._mounted:
            try:
                screen = self.screen
                screen.remove_class("theme-dark")
                screen.remove_class("theme-light")
                screen.add_class(
                    "theme-dark" if tokens is get_theme("dark") else "theme-light"
                )
                if self.reduced_motion:
                    screen.add_class("reduced-motion")
                else:
                    screen.remove_class("reduced-motion")
            except Exception:
                pass
            try:
                self.refresh_css()
            except Exception:
                pass
        return tokens

    def preview_theme(self, name: ThemeName) -> ThemeTokens:
        """Live preview without committing the onboarding selection."""
        return self.apply_theme(name)

    def restore_theme(self) -> ThemeTokens:
        """Restore the previously committed theme (Escape in picker)."""
        return self.apply_theme(self._previous_theme)  # type: ignore[arg-type]

    # -- overlay stack scaffold ------------------------------------------
    def open_overlay(self, name: str) -> None:
        """Push an overlay name, remembering focus for later restore."""
        try:
            self._focus_before_overlay = self.focused
        except Exception:
            self._focus_before_overlay = None
        if name not in self._overlay_stack:
            self._overlay_stack.append(name)

    def close_overlay(self, name: str | None = None) -> None:
        """Pop an overlay and restore the previously focused widget."""
        if not self._overlay_stack:
            return
        closing: str | None
        if name is None:
            closing = self._overlay_stack.pop()
        elif name in self._overlay_stack:
            self._overlay_stack.remove(name)
            closing = name
        else:
            return
        if closing is not None:
            try:
                if self.screen_stack and len(self.screen_stack) > 1:
                    self.pop_screen()
            except Exception:
                pass
        self._focus_before_overlay = None
        self._restore_composer_focus()

    def _restore_composer_focus(self) -> None:
        try:
            self.query_one("#composer-input").focus()
        except Exception:
            pass

    # -- boot / runtime worker -------------------------------------------
    def _start_runtime_worker(self) -> None:
        self.app_state = "initializing"
        self.run_worker(self._initialize_runtime(), exclusive=True)

    async def _initialize_runtime(self) -> None:
        if self.runtime_factory is None:
            return
        try:
            factory = self.runtime_factory
            runtime_models = await asyncio.to_thread(factory)
            self._attach_runtime_models(runtime_models)
        except Exception as exc:
            self._enter_error_state(self._sanitize_startup_error(exc))

    def _attach_runtime_models(self, runtime_models: Any) -> None:
        from skail.runtime.run_controller import RunController

        self.runtime_models = runtime_models
        models, lead_model_name, child_model_name = runtime_models
        assert self.journal is not None, "journal required for runtime attach"
        assert self.checkpoints is not None, "checkpoints required for runtime attach"
        assert self.redaction is not None, "redaction required for runtime attach"
        workspace = Path(str(self.bootstrap.get("workspace", Path.cwd())))
        budget_raw = self.bootstrap.get("budget", None)
        budget_usd = Decimal(str(budget_raw)) if budget_raw is not None else None
        controller = RunController(
            session_id=self.session_id or new_session_id(),
            workspace=workspace,
            journal=self.journal,
            checkpoints=self.checkpoints,
            redaction=self.redaction,
            models=models,
            default_lead_model=lead_model_name,
            default_child_model=child_model_name,
            budget_limit_usd=budget_usd,
            budget_warning_percent=self.bootstrap.get("budget_warning_percent", 80),
            approvals=self.approval_store,
            question_store=self.question_store,
            project_trusted=bool(self.bootstrap.get("project_trusted", False)),
            profile_models=self.profile_models,
            providers=runtime_models.providers,
            candidates_fn=(
                runtime_models.routing_snapshot if bool(runtime_models.candidates) else None
            ),
            catalog_revision=(
                runtime_models.catalog.revision
                if bool(runtime_models.candidates)
                else "catalog-v1"
            ),
            config_snapshot=(
                runtime_models.config.model_dump(mode="json")
                if bool(runtime_models.candidates)
                else None
            ),
            workspace_mode=self.bootstrap.get("workspace_mode", "shared"),
        )
        self.controller = controller
        controller.subscribe_events(self.apply_event)
        if lead_model_name != "auto":
            self.projection.set_future_model(lead_model_name)
        resume_target = self.bootstrap.get("resume_session", None)
        if resume_target is not None:
            controller.restore_interrupted()
        self.onboarding_credentials.clear()
        selection_required = bool(
            getattr(runtime_models, "selection_required", False)
            or not self._enabled_models
        )
        self.app_state = "selection_required" if selection_required else "ready"
        self.startup_error = None
        self._remove_onboarding_panel()
        self._append_system_message(
            "Choose a model" if selection_required else "Ready",
            (
                self._lead_failure_message(runtime_models)
                if selection_required
                else _READY_COPY
            ),
        )
        if bool(getattr(runtime_models, "catalog_degraded", False)):
            self._append_system_message(
                "Catalog fallback",
                "Using the last valid local catalog; refresh will retry on the next startup.",
            )
        self.update_views()
        if selection_required:
            if self.initial_prompt:
                self._pending_prompts.append(self.initial_prompt)
                self._restore_composer_draft(self.initial_prompt)
            self.action_model_picker()
            return
        if self.initial_prompt:
            self._start_prompt(self.initial_prompt)
        while self._pending_prompts:
            self._start_prompt(self._pending_prompts.popleft(), record=False)

    def _enter_error_state(self, detail: str) -> None:
        secret = self.onboarding_credentials.reveal()
        if secret:
            detail = detail.replace(secret, "<redacted>")
        self.app_state = "error"
        self.startup_error = detail
        self._append_system_message("Startup error", _RUNTIME_ERROR_COPY + f"\nDetail: {detail}")
        if self._pending_prompts:
            self._restore_composer_draft(self._pending_prompts[-1])
        self.update_views()

    @staticmethod
    def _lead_failure_message(runtime_models: Any) -> str:
        failure = getattr(runtime_models, "lead_failure", None)
        if failure is None:
            return "Select an accessible lead model that meets the hard requirements."
        from skail.routing.selector import describe_route_failure

        return describe_route_failure(failure)

    def _restore_composer_draft(self, text: str) -> None:
        try:
            composer = self.query_one("#prompt-composer", PromptComposer)
            composer.restore_draft(text)
        except Exception:
            pass

    def _sanitize_startup_error(self, exc: BaseException) -> str:
        message = str(exc)[:300] or exc.__class__.__name__
        for secret in (self.onboarding_credentials.reveal(),):
            if secret:
                message = message.replace(secret, "<redacted>")
        return message

    def retry_startup(self) -> None:
        """Retry recoverable runtime initialization from the error screen."""
        self.startup_error = None
        self._start_runtime_worker()

    def _record_user_prompt(self, text: str) -> None:
        self.projection.transcript_items.append(
            TranscriptItem(
                id=f"user-{len(self.projection.transcript_items)}",
                role="user",
                title="User Prompt",
                content=text,
            )
        )

    def _queue_initializing_prompt(self, text: str) -> None:
        self._record_user_prompt(text)
        self._pending_prompts.append(text)
        self.projection.transcript_items.append(
            TranscriptItem(
                id=f"queue-init-{len(self.projection.transcript_items)}",
                role="system",
                title="Queued while starting",
                content=(
                    "Runtime initialization is in progress. "
                    "This prompt will run when Skail is ready."
                ),
            )
        )
        self._restore_composer_draft(text)
        self.update_views()

    def _start_prompt(self, text: str, *, record: bool = True) -> None:
        """Start a prompt on the attached controller, preserving FIFO follow-ups."""
        if self.app_state == "selection_required":
            self._record_user_prompt(text)
            self._pending_prompts.append(text)
            self._restore_composer_draft(text)
            self._append_system_message(
                "Choose a model",
                "Select an accessible model before running this prompt.",
            )
            self.update_views()
            return
        if self.projection.pending_interrupt is not None:
            self._restore_composer_draft(text)
            self._append_system_message(
                "Interrupt pending",
                "Resolve the pending question or approval before starting a new run. "
                "This prompt was not sent, and the interrupt remains pending.",
            )
            self.update_views()
            return
        if self.controller is None:
            if self.runtime_factory is not None or self.app_state in {"initializing", "error"}:
                self._queue_initializing_prompt(text)
            else:
                self._record_user_prompt(text)
                self.update_views()
            return
        if record:
            self._record_user_prompt(text)
            self.update_views()
        previous = self._active_worker
        if previous is not None and not previous.is_finished:
            self._run_active = True
            self.projection.queue_followup(text)
            self.projection.transcript_items.append(
                TranscriptItem(
                    id=f"queue-{len(self.projection.transcript_items)}",
                    role="system",
                    title="Follow-up queued",
                    content="This prompt will run after the active foreground request.",
                )
            )
            self.update_views()
        else:
            self._run_active = True
            self._active_worker = self.run_worker(
                self._execute_prompt(text), exclusive=False
            )
            self.update_views()

    def _start_next_queued_prompt(self) -> None:
        if self.app_state == "quitting":
            self.projection.queue.clear()
            self._run_active = False
            return
        if self.app_state != "ready":
            return
        if self.projection.pending_interrupt is not None or not self._run_active:
            return
        if not self.projection.queue:
            self._run_active = False
            return
        text = self.projection.queue.pop(0)
        previous = self._active_worker
        if previous is not None and not previous.is_finished:
            self._active_worker = self.run_worker(
                self._execute_follow_up(previous, text), exclusive=False
            )
        else:
            self._active_worker = self.run_worker(
                self._execute_prompt(text), exclusive=False
            )

    # -- onboarding -------------------------------------------------------
    def _mount_onboarding(self) -> None:
        self.update_views()
        try:
            self.query_one("#prompt-composer").visible = False
        except Exception:
            pass
        try:
            container = self.query_one("#interrupt-container", Container)
            if not container.query("OnboardingPanel"):
                panel = OnboardingPanel(
                    self.onboarding_state,
                    self.onboarding_credentials,
                    workspace=str(self.bootstrap.get("workspace", "")),
                    session_id=str(self.bootstrap.get("session_id", "")),
                )
                container.mount(panel)
                panel.focus()
        except Exception:
            pass

    def _remove_onboarding_panel(self) -> None:
        try:
            for panel in self.query("OnboardingPanel"):
                panel.remove()
        except Exception:
            pass
        try:
            composer = self.query_one("#prompt-composer")
            composer.visible = True
            self.query_one("#composer-input").focus()
        except Exception:
            pass

    def _refresh_onboarding_panel(self) -> None:
        try:
            for panel in self.query("OnboardingPanel"):
                if isinstance(panel, OnboardingPanel):
                    panel.refresh_step()
        except Exception:
            pass

    def onboarding_confirm(self) -> None:
        """Enter key in onboarding: continue or activate the step action."""
        step = self.onboarding_state.step
        if step == "welcome":
            self.onboarding_state.advance()
            self._refresh_onboarding_panel()
        elif step == "provider":
            key = self.onboarding_credentials.reveal()
            if len(key.strip()) >= 8:
                self.validate_onboarding_key()
            else:
                try:
                    for panel in self.query("OnboardingPanel"):
                        key_input = panel.query_one("#onboarding-key", Input)
                        key_input.focus()
                except Exception:
                    self.validate_onboarding_key()
        elif step == "trust":
            if self.onboarding_state.trusted is None:
                self.onboarding_state.trusted = False
            self.onboarding_state.advance()
            self._refresh_onboarding_panel()
        elif step == "theme":
            self._previous_theme = self.onboarding_state.theme
            self.onboarding_state.advance()
            self._refresh_onboarding_panel()
        elif step == "ready":
            self._save_onboarding_receipt(completed=True)
            self._remove_onboarding_panel()
            self._start_runtime_worker()

    def onboarding_back(self) -> None:
        """Escape in onboarding: go back one step, restoring theme preview."""
        if self.onboarding_state.step == "theme":
            self.restore_theme()
        self.onboarding_state.go_back()
        self._refresh_onboarding_panel()

    def onboarding_trust_folder(self) -> None:
        """T key: trust the exact resolved workspace."""
        self.onboarding_state.trusted = True
        self.onboarding_state.advance()
        self._refresh_onboarding_panel()

    def onboarding_restricted_mode(self) -> None:
        """R key: continue in restricted mode."""
        self.onboarding_state.trusted = False
        self.onboarding_state.advance()
        self._refresh_onboarding_panel()

    def validate_onboarding_key(self) -> None:
        """V key: async validation with loading state and sanitized errors."""
        if self.onboarding_state.validating:
            return
        self.onboarding_state.validating = True
        self.onboarding_state.validation_error = None
        self._refresh_onboarding_panel()
        self.run_worker(self._validate_key_async(), exclusive=True)

    async def _validate_key_async(self) -> None:
        await asyncio.sleep(0)
        key = self.onboarding_credentials.reveal()
        self.onboarding_state.validating = False
        if len(key.strip()) >= 8:
            if self._store_onboarding_key():
                self.onboarding_state.validation_error = None
                self.onboarding_state.advance()
        else:
            self.onboarding_state.validation_error = VALIDATION_FAILURE_COPY
        self._refresh_onboarding_panel()
        self.update_views()

    def _credential_store(self) -> CredentialStore:
        configured = self.bootstrap.get("credential_store")
        return configured if configured is not None else KeyringCredentialStore()

    def _provider_credential_available(self) -> bool:
        import os

        provider = self.onboarding_state.provider
        env_var = _PROVIDER_ENV_VARS.get(provider)
        if not env_var:
            return False
        if os.environ.get(env_var):
            return True
        try:
            return bool(self._credential_store().get(provider, env_var))
        except CredentialStoreUnavailable:
            return False

    def _store_onboarding_key(self) -> bool:
        provider = self.onboarding_state.provider
        env_var = _PROVIDER_ENV_VARS.get(provider)
        key = self.onboarding_credentials.reveal()
        if not env_var or not key:
            self.onboarding_state.validation_error = VALIDATION_FAILURE_COPY
            return False
        try:
            self._credential_store().set(provider, env_var, key)
        except CredentialStoreUnavailable:
            self.onboarding_state.validation_error = (
                f"Secure credential storage is unavailable. Set {env_var} in the environment, "
                "then retry."
            )
            return False
        return True

    def _save_onboarding_receipt(self, *, completed: bool) -> None:
        onboarding_path_value = self.bootstrap.get("onboarding_path")
        if not onboarding_path_value:
            return
        selected = self.projection.model_for_future() or "auto"
        enabled = tuple(sorted(getattr(self, "_enabled_models", set())))
        receipt = OnboardingReceipt(
            completed=completed,
            provider=self.onboarding_state.provider,
            selected_model=selected,
            enabled_models=enabled,
            theme=self.onboarding_state.theme,
        )
        save_onboarding_receipt(
            receipt,
            path=Path(onboarding_path_value) if onboarding_path_value else None,
        )
        self.onboarding_receipt = receipt

    # -- rendering --------------------------------------------------------
    def _render_status_strip(self) -> str:
        """Return the ATELIER dateline markup for the current application state."""
        f = self.projection.footer_data
        ratio: float | None = None
        if f.budget_limit_usd is not None and f.budget_limit_usd > 0:
            ratio = min(1.0, float(f.session_cost_usd / f.budget_limit_usd))
        cost = f"${f.session_cost_usd:.4f}"
        if f.budget_limit_usd is not None:
            cost = f"{cost} / ${f.budget_limit_usd:.2f}"
        running = 0
        queued = 0
        for child in self.projection.children_view():
            if child.status == "running":
                running += 1
            elif child.status == "queued":
                queued += 1
        badge: str | None = None
        badge_token = "textMuted"
        if self.app_state == "onboarding":
            badge, badge_token = "PROVIDER not configured", "approval"
        elif self.app_state == "initializing":
            badge, badge_token = "STARTING", "textMuted"
        elif self.app_state == "selection_required":
            badge, badge_token = "CHOOSE MODEL", "approval"
        elif self.app_state == "error":
            badge, badge_token = "SETUP FAILED", "error"
        try:
            narrow = self.screen.has_class("narrow")
        except Exception:
            narrow = False
        return render_dateline(
            model=f.lead_model,
            mode=f.routing_mode,
            cost=cost,
            ratio=ratio,
            active=f.active_agents_count,
            running=running,
            queued=queued,
            badge=badge,
            badge_token=badge_token,
            active_mode=f.active_mode,
            narrow=narrow,
        )

    def render_masthead(self) -> str:
        """Render the ATELIER masthead: wordmark, version, provider, clock."""
        provider = self.onboarding_state.provider or None
        clock = datetime.now().strftime("%H:%M:%S")
        return format_masthead(__version__, provider, clock)

    def _refresh_masthead(self) -> None:
        try:
            self.query_one("#masthead", Static).update(self.render_masthead())
        except NoMatches:
            pass

    def _tick_masthead(self) -> None:
        if self.reduced_motion:
            return
        self._refresh_masthead()

    def _refresh_transcript_header(self) -> None:
        """Feed #transcript-header (plan §5.4): run id, event count, pin state."""
        try:
            chat = self.query_one("#chat-transcript", ChatTranscript)
            run_id: str | None = None
            if self.initial_snapshot and self.initial_snapshot.runs:
                run_id = str(self.initial_snapshot.runs[-1].run_id)
            pinned = chat._pinned
            header = self.query_one("#transcript-header", Static)
            header.update(
                render_transcript_header(run_id, len(self.projection.transcript_items), pinned)
            )
        except NoMatches:
            pass

    def _refresh_activity_indicator(self) -> None:
        try:
            indicator = self.query_one("#activity-spinner", ActivitySpinner)
        except NoMatches:
            return
        if self.app_state == "initializing":
            label = "STARTING"
        elif self.projection.pending_interrupt is not None:
            label = "WAITING"
        elif self._run_active:
            label = "RUNNING"
        elif self.projection.queue:
            label = "QUEUED"
        else:
            indicator.display = False
            return
        indicator.spinner_label = label
        indicator.display = True
        indicator.update(f"{label} …")

    def _append_system_message(self, title: str, content: str) -> None:
        self.projection.transcript_items.append(
            TranscriptItem(
                id=f"sys-{title.lower()}-{len(self.projection.transcript_items)}",
                role="system",
                title=title,
                content=content,
            )
        )

    def update_views(self) -> None:
        if not self._mounted:
            return

        self._refresh_activity_indicator()

        try:
            chat = self.query_one("#chat-transcript", ChatTranscript)
            chat.update_items(self.projection.transcript_items)
            self._refresh_transcript_header()
        except Exception:
            pass

        try:
            rail = self.query_one("#agent-rail", AgentRail)
            children = self.projection.children_view()
            if children:
                rail.update_children(children, focused_id=self.projection.focused_agent_id)
            else:
                rail.update_items(
                    self.projection.agent_rail_items,
                    focused_id=self.projection.focused_agent_id,
                )
        except Exception:
            pass

        try:
            plan_view = self.query_one("#plan-view", PlanView)
            plan_view.update_plan(
                self.projection.plan_items,
                plan_id=self.projection.current_plan_id,
                revision=self.projection.current_plan_revision,
                integrations=self.projection.workspace_integrations,
                plan_state=self.projection.plan_state,
                receipts=self.projection.receipts,
            )
        except Exception:
            pass

        try:
            route_view = self.query_one("#route-view", RouteView)
            route_view.update_routes(
                self.projection.route_items,
                selected_task_id=self.projection.focused_agent_id,
            )
        except Exception:
            pass

        try:
            budget_view = self.query_one("#budget-view", BudgetView)
            budget_view.update_budget(self.projection.budget_item)
        except Exception:
            pass

        try:
            ledger = self.query_one("#budget-ledger", BudgetLedger)
            ledger.update_budget(self.projection.budget_item)
        except Exception:
            pass

        try:
            self._refresh_masthead()
        except Exception:
            pass

        try:
            from skail.tui.widgets.composer import PromptComposer as _Composer

            composer = self.query_one("#prompt-composer", _Composer)
            composer.set_run_active(self._run_active)
            composer.set_queue(self.projection.queue)
            # Feed slash palette from the command registry (names +
            # descriptions/keywords) so ghost completion stays in sync.
            names: list[str] = []
            descriptions: dict[str, str] = {}
            keywords: dict[str, list[str]] = {}
            for entry in COMMAND_REGISTRY:
                raw = str(entry.get("command", "")).lstrip("/").lower()
                if not raw:
                    continue
                names.append(raw)
                descriptions[raw] = str(entry.get("description", ""))
                kw = entry.get("keywords", [])
                keywords[raw] = [str(k) for k in kw] if isinstance(kw, list) else []
                for alias in entry.get("aliases", []) or []:
                    alias_name = str(alias).lstrip("/").lower()
                    if alias_name and alias_name not in names:
                        names.append(alias_name)
                        descriptions[alias_name] = str(entry.get("description", ""))
                        keywords[alias_name] = list(keywords[raw])
            composer.registry = names
            composer.descriptions = descriptions
            composer.keywords = keywords
        except Exception:
            pass

        try:
            dateline = self.query_one("#dateline", Static)
            dateline.update(self._render_status_strip())
        except Exception:
            pass

        try:
            interrupt_container = self.query_one("#interrupt-container", Container)
            if self.projection.pending_interrupt:
                if not interrupt_container.query("InterruptWidget"):
                    interrupt_container.mount(InterruptWidget(self.projection.pending_interrupt))
            else:
                for widget in interrupt_container.query("InterruptWidget"):
                    widget.remove()
        except Exception:
            pass
        if self.app_state == "onboarding":
            self._refresh_onboarding_panel()

    def apply_snapshot(self, snapshot: SessionSnapshot) -> None:
        self.projection.apply_snapshot(snapshot)
        if self._mounted:
            self.update_views()

    def apply_event(self, event: EventEnvelope) -> None:
        self.projection.apply_event(event)
        if self._mounted:
            self.update_views()

    async def _execute_prompt(self, text: str) -> None:
        if self.controller is None:
            return
        self._announce_cancelled_plan_inactive()
        controls = LeadControls(
            model=self.projection.footer_data.lead_model
            if self.projection.footer_data.lead_model != "auto"
            else None,
            max_children=self.max_children,
            delegation=self.delegation,
            routing_mode=RoutingMode(self.projection.footer_data.routing_mode),
        )
        try:
            result = await self.controller.run_instruction(text, controls=controls)
            self._apply_run_result(result)
            result_status = getattr(result, "status", "completed")
            if result.pending_interrupt is None and result_status != "completed":
                self._clear_queued_prompts(f"Run ended {result_status}:")
        except (KeyboardInterrupt, asyncio.CancelledError):
            self._clear_queued_prompts("Foreground run cancelled:")
            self.projection.transcript_items.append(
                TranscriptItem(
                    id=f"cancel-{len(self.projection.transcript_items)}",
                    role="system",
                    title="Cancelled",
                    content="Execution cancelled.",
                )
            )
        except Exception as exc:
            self._clear_queued_prompts("Foreground run failed:")
            self.projection.transcript_items.append(
                TranscriptItem(
                    id=f"err-{len(self.projection.transcript_items)}",
                    role="error",
                    title="Execution Error",
                    content=str(exc),
                )
            )
        finally:
            if self.projection.pending_interrupt is None:
                self._start_next_queued_prompt()
            self.update_views()

    def _announce_cancelled_plan_inactive(self) -> None:
        controller = self.controller
        journal = self.journal or getattr(controller, "journal", None)
        session_id = self.session_id or getattr(controller, "session_id", None)
        if journal is None or session_id is None:
            return
        try:
            snapshot = journal.get_session_snapshot(str(session_id))
            if not snapshot.runs:
                return
            previous = snapshot.runs[-1]
            if previous.status != "cancelled" or not journal.plans_for_run(previous.run_id):
                return
        except Exception:
            return
        self._append_system_message(
            "Starting a new run",
            "The previous run was cancelled; its plan is inactive. "
            "This instruction starts a fresh run.",
        )

    async def _execute_follow_up(self, previous: Any, text: str) -> None:
        try:
            await previous.wait()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        await self._execute_prompt(text)

    async def _resume_prompt(self, answer: str) -> None:
        if self.controller is None:
            return
        try:
            result = await self.controller.resume_interrupted(answer)
            self._apply_run_result(result)
            result_status = getattr(result, "status", "completed")
            if result.pending_interrupt is None and result_status != "completed":
                self._clear_queued_prompts(f"Run ended {result_status}:")
        except Exception as exc:
            self._clear_queued_prompts("Resumed run failed:")
            self.projection.transcript_items.append(
                TranscriptItem(
                    id=f"err-{len(self.projection.transcript_items)}",
                    role="error",
                    title="Resume Error",
                    content=str(exc),
                )
            )
        finally:
            if self.projection.pending_interrupt is None:
                self._start_next_queued_prompt()
            self.update_views()

    def _refresh_budget_from_journal(self) -> None:
        controller = self.controller
        journal = self.journal or getattr(controller, "journal", None)
        session_id = self.session_id or getattr(controller, "session_id", None)
        if journal is None or session_id is None:
            return
        try:
            snapshot = journal.get_session_snapshot(str(session_id))
        except Exception:
            return
        self.projection.apply_budget_snapshot(snapshot)

    def _clear_queued_prompts(self, reason: str) -> int:
        queued = len(self.projection.queue)
        self.projection.queue.clear()
        if queued:
            prompt_word = "prompt" if queued == 1 else "prompts"
            self._append_system_message(
                "Queue cleared",
                f"{reason} {queued} queued {prompt_word} discarded. Submit them again when ready.",
            )
        return queued

    def _cancel_foreground_run(self) -> None:
        self._clear_queued_prompts("Foreground cancellation:")
        worker = self._active_worker
        if worker is not None and not worker.is_finished:
            worker.cancel()
        else:
            self._run_active = False
        self.update_views()

    def _begin_shutdown(self) -> None:
        if self.app_state == "quitting":
            return
        self.app_state = "quitting"
        self._run_active = False
        self._clear_queued_prompts("Application shutdown:")
        if self._active_worker is not None:
            try:
                self._active_worker.cancel()
            except Exception:
                pass
        if self.session_service is not None and self.session_id is not None:
            try:
                self.session_service.journal.update_session_status(
                    session_id=str(self.session_id), status="idle"
                )
            except Exception:
                pass
        self.update_views()

    def on_unmount(self, event: Any) -> None:
        """Drop queued work if Textual is closed by the host window lifecycle."""
        _ = event
        self._begin_shutdown()

    def exit(
        self,
        result: Any = None,
        return_code: int = 0,
        message: Any = None,
    ) -> None:
        """Apply queue and worker shutdown before Textual exits the event loop."""
        self._begin_shutdown()
        super().exit(result, return_code=return_code, message=message)

    def _apply_run_result(self, result: Any) -> None:
        if result.pending_interrupt:
            self._set_interrupt(result.pending_interrupt, run_id=str(result.run_id))
        else:
            self.projection.pending_interrupt = None
        self._refresh_budget_from_journal()
        if result.output:
            answer = clean_lead_output(result.output)
        else:
            answer = ""
        if answer:
            self.projection.transcript_items.append(
                TranscriptItem(
                    id=f"lead-{len(self.projection.transcript_items)}",
                    role="lead",
                    title="Skail Response",
                    content=answer,
                )
            )
            return
        if result.pending_interrupt is not None:
            return
        status = getattr(result, "status", "completed")
        outcomes = {
            "blocked": (
                "Execution blocked",
                "Review the run's budget, safety, or interaction requirements before retrying.",
            ),
            "failed": (
                "Execution failed",
                "Review the run events and error details before retrying.",
            ),
            "cancelled": ("Execution cancelled", "No final answer was produced."),
            "completed": (
                "No user-facing answer",
                "The run produced no final answer. Review the recorded run events for context.",
            ),
        }
        title, content = outcomes.get(
            str(status),
            ("Execution ended", f"The run ended with status {status}. Review its recorded events."),
        )
        self._append_system_message(title, content)

    def _set_interrupt(self, payload: dict[str, Any], *, run_id: str) -> None:
        payload = dict(payload)
        payload.setdefault("session_id", str(self.session_id or ""))
        payload.setdefault("run_id", run_id)
        journal = self.journal or getattr(self.controller, "journal", None)
        if "plan_id" not in payload and journal is not None:
            try:
                plans = journal.plans_for_run(run_id)
                if plans:
                    payload["plan_id"] = plans[-1].plan_id
            except Exception:
                pass
        approval_id = str(payload.get("question_id") or f"command:{run_id}")
        question = str(
            payload.get("prompt")
            or " ".join(
                [str(payload.get("command", "command")), *payload.get("arguments", ())]
            )
        )
        self.projection.pending_interrupt = InterruptItem(
            approval_id=approval_id,
            task_id=payload.get("task_id"),
            question=question,
            payload=payload,
        )

    def _question_graph_id(self, payload: dict[str, Any]) -> str:
        explicit = payload.get("graph_id")
        if isinstance(explicit, str) and explicit:
            return explicit
        session_id = payload.get("session_id") or self.session_id
        run_id = payload.get("run_id")
        if session_id and run_id:
            task_id = payload.get("task_id") or "lead"
            return f"{session_id}:{run_id}:{task_id}"
        return "lead"

    def on_prompt_composer_prompt_submitted(
        self, event: PromptComposer.PromptSubmitted
    ) -> None:
        text = event.text
        if text.startswith("/"):
            background_capable = self._background_commands_supported()
            result = dispatch_slash_command(
                text,
                self.projection,
                background_supported=background_capable,
                available_models=self._accessible_model_ids(),
            )
            if result.command == "config" and self.controller is not None:
                result.output_message = json.dumps(
                    self.controller.redaction.scrub(self.controller.config_snapshot),
                    sort_keys=True,
                )
            elif result.command == "config":
                result.output_message = json.dumps(
                    {
                        "app_state": self.app_state,
                        "workspace": self.bootstrap.get("workspace"),
                        "provider": self.onboarding_state.provider or None,
                        "routing_mode": self.projection.footer_data.routing_mode,
                        "source": "bootstrap",
                    },
                    sort_keys=True,
                )
            if result.command == "trust":
                snapshot = (
                    self.controller.config_snapshot
                    if self.controller is not None
                    else self.bootstrap
                )
                trusted = bool(snapshot.get("project_trusted", False))
                result.output_message = (
                    "Project is trusted." if trusted else "Project is untrusted."
                )
            if result.action == "quit":
                self._begin_shutdown()
                self.exit(0)
                return
            if result.action == "view" and result.target_view:
                tabs = self.query_one("#tabs", TabbedContent)
                tab_id = f"tab-{result.target_view}"
                if tab_id in ("tab-agents", "tab-plan", "tab-route", "tab-budget"):
                    tabs.active = tab_id
            elif result.action == "cancel":
                if result.target_id:
                    self.request_child_cancel(result.target_id)
                else:
                    self._cancel_foreground_run()
            elif result.action == "steer":
                controller = self.controller
                request_steer = getattr(controller, "request_steer", None)
                if callable(request_steer):
                    request_steer(result.target_id, str(result.payload.get("message", "")))
            elif result.action == "resume" and self.session_service is not None:
                selected_id = result.target_id or (
                    str(self.session_id) if self.session_id is not None else None
                )
                if selected_id is None:
                    sessions = self.session_service.list_sessions()
                    selected_id = sessions[0].session_id if sessions else None
                resume_res = (
                    self.session_service.resume_session(selected_id)
                    if selected_id is not None
                    else None
                )
                if resume_res is not None and resume_res.ok and resume_res.session is not None:
                    self.session_id = SessionId(resume_res.session.session_id)
                    if self.controller is not None:
                        self.controller.session_id = self.session_id
                        self.controller.restore_interrupted()
                    snapshot = self.session_service.journal.get_session_snapshot(
                        resume_res.session.session_id
                    )
                    self.apply_snapshot(snapshot)
            elif (
                result.action == "compact"
                and self.session_service is not None
                and self.session_id is not None
            ):
                from skail.sessions.compaction import (
                    CompactionService,
                    SessionCompactionInput,
                )

                snapshot = self.session_service.journal.get_session_snapshot(
                    str(self.session_id)
                )
                compactor = CompactionService(journal=self.session_service.journal)
                compactor.compact(
                    SessionCompactionInput(
                        session_id=str(self.session_id),
                        objective=snapshot.title,
                    )
                )
                refreshed = self.session_service.journal.get_session_snapshot(
                    str(self.session_id)
                )
                self.apply_snapshot(refreshed)
            elif result.action == "model_picker":
                self.action_model_picker()
            elif result.action == "theme_picker":
                self.action_theme_picker()
            elif result.action == "missions":
                self.action_missions_overlay()

            if "theme" in result.payload:
                self.apply_theme_preview(str(result.payload["theme"]))
            if "model" in result.payload:
                self.set_future_model(str(result.payload["model"]))
            if "routing_mode" in result.payload:
                self.projection.footer_data.routing_mode = str(result.payload["routing_mode"])
                self.update_views()

            if result.output_message:
                self.projection.transcript_items.append(
                    TranscriptItem(
                        id=f"cmd-{len(self.projection.transcript_items)}",
                        role="system",
                        title=f"Command /{result.command}",
                        content=result.output_message,
                    )
                )
            self.update_views()
            return

        self._start_prompt(text)

    def on_prompt_composer_prompt_queued(self, event: PromptComposer.PromptQueued) -> None:
        """Persist the composer queue so refreshes and FIFO execution stay in sync."""
        self._record_user_prompt(event.text)
        self.projection.queue_followup(event.text)
        self._append_system_message(
            "Follow-up queued",
            "This prompt will run after the active foreground request.",
        )
        self.update_views()

    def _background_commands_supported(self) -> bool:
        controller = self.controller
        return bool(
            self.background_supported
            and controller is not None
            and callable(getattr(controller, "request_cancel", None))
            and callable(getattr(controller, "request_steer", None))
        )

    def _accessible_model_ids(self) -> set[str] | None:
        model_ids: set[str] = {"auto"}
        sources: list[Any] = []
        if self.controller is not None:
            sources.append(getattr(self.controller, "models", {}))
        runtime_models = getattr(self, "runtime_models", None)
        if runtime_models is not None:
            sources.append(getattr(runtime_models, "models", {}))
            catalog = getattr(runtime_models, "catalog", None)
            if catalog is not None:
                model_ids.update(
                    f"{provider}:{model}"
                    for provider, model in getattr(catalog, "profiles", {})
                )
        for source in sources:
            if isinstance(source, dict):
                for key in source:
                    model_ids.add(str(key))
        return model_ids if len(model_ids) > 1 else None

    def on_input_changed(self, event: Input.Changed) -> None:
        """Route onboarding key-field edits into memory-only credentials."""
        if event.input.id == "onboarding-key":
            self.onboarding_credentials.set_key(event.value)

    def on_interrupt_widget_approved(self, event: InterruptWidget.Approved) -> None:
        pending = self.projection.pending_interrupt
        if (
            pending is not None
            and pending.payload.get("type") == "command_approval"
            and self.approval_store is not None
        ):
            request = CommandRequest(
                str(pending.payload["command"]),
                tuple(str(value) for value in pending.payload.get("arguments", ())),
                Path(
                    str(
                        pending.payload.get(
                            "cwd",
                            (
                                self.controller.workspace
                                if self.controller is not None
                                else Path.cwd()
                            ),
                        )
                    )
                ),
                session_id=str(pending.payload.get("session_id", "")),
                run_id=str(pending.payload.get("run_id", "")),
                task_id=str(pending.payload.get("task_id", "")),
                action_id=str(pending.payload.get("action_id", "")),
            )
            self.approval_store.decide(request, ApprovalChoice.ALLOW_ONCE)
        if self.controller is not None:
            self.projection.pending_interrupt = None
            self._run_active = True
            self._active_worker = self.run_worker(
                self._resume_prompt(event.response), exclusive=True
            )
            self.update_views()
            return
        if self.question_store is not None:
            try:
                  self.question_store.answer(
                      event.approval_id,
                      event.response,
                      graph_id=self._question_graph_id(pending.payload)
                      if pending is not None
                      else "lead",
                  )
            except Exception:
                pass
        sid = self.session_id or new_session_id()
        answer_ev = EventEnvelope(
            event_id=new_event_id(),
            session_id=sid,
            run_id=new_run_id(),
            sequence=len(self.projection.transcript_items) + 1,
            type="user.answer",
            payload=UserPayload(action="answer", content=event.response),
        )
        self.projection.pending_interrupt = None
        self.apply_event(answer_ev)

    def on_interrupt_widget_rejected(self, event: InterruptWidget.Rejected) -> None:
        if self.controller is not None:
            pending = self.projection.pending_interrupt
            if (
                pending is not None
                and pending.payload.get("question_id")
                and self.question_store is not None
            ):
                try:
                    self.question_store.cancel(
                        str(pending.payload["question_id"]),
                        graph_id=self._question_graph_id(pending.payload),
                    )
                except Exception:
                    pass
            self.controller.reject_interrupted()
        self._clear_queued_prompts("The waiting run was cancelled:")
        self.projection.pending_interrupt = None
        self.projection.transcript_items.append(
            TranscriptItem(
                id=f"rej-{event.approval_id}",
                role="error",
                title="Approval Rejected",
                content="User rejected approval request.",
            )
        )
        self.update_views()

    def on_plan_view_plan_accepted(self, event: PlanView.PlanAccepted) -> None:
        _ = event
        self._resolve_pending_plan("accepted")

    def on_plan_view_plan_rejected(self, event: PlanView.PlanRejected) -> None:
        _ = event
        self._resolve_pending_plan("rejected")

    def on_plan_view_plan_changes_requested(
        self, event: PlanView.PlanChangesRequested
    ) -> None:
        _ = event
        self.projection.note_plan("proposed")
        self.update_views()

    def _resolve_pending_plan(self, decision: str) -> None:
        """Route Accept/Reject through the existing approval/plan path."""
        self.projection.note_plan(decision)
        pending = self.projection.pending_interrupt
        if (
            pending is not None
            and pending.payload.get("type") == "plan_approval"
            and self.question_store is not None
            and pending.payload.get("question_id")
        ):
            try:
                if decision == "accepted":
                    self.question_store.answer(
                        str(pending.payload["question_id"]),
                        "accept",
                        graph_id=self._question_graph_id(pending.payload),
                    )
                else:
                    self.question_store.cancel(
                        str(pending.payload["question_id"]),
                        graph_id=self._question_graph_id(pending.payload),
                    )
            except Exception:
                pass
            self.projection.pending_interrupt = None
        self.update_views()

    def on_agent_rail_agent_selected(self, event: AgentRail.AgentSelected) -> None:
        # Phase 3b: selecting stays in Agents; never jumps to Route.
        self.projection.focus_agent(event.task_id)
        self.update_views()

    def on_agent_rail_agent_detail_requested(
        self, event: AgentRail.AgentDetailRequested
    ) -> None:
        """Enter opens detail: focus the detail region (stays tab-local)."""
        self.projection.focus_agent(event.task_id)
        try:
            self.query_one("#agent-rail", AgentRail).focus()
        except Exception:
            pass
        self.update_views()

    def on_agent_rail_mission_control_requested(
        self, event: AgentRail.MissionControlRequested
    ) -> None:
        self.action_missions_overlay()

    # -- theme preview / future model (overlay hooks) ----------------------
    def apply_theme_preview(self, name: Any) -> Any:
        """Apply a live preview without persisting the selected theme."""
        normalized = str(name).strip().lower()
        if normalized not in (
            "dark", "light", "system", "pistachio-night", "pistachio-paper", "mint-porcelain"
        ):
            normalized = "dark"
        return self.apply_theme(normalized)  # type: ignore[arg-type]

    def commit_theme(self, name: str) -> None:
        normalized = name.strip().lower()
        self.apply_theme_preview(normalized)
        self.onboarding_state.theme = normalized
        self._previous_theme = normalized
        self._save_onboarding_receipt(completed=self.onboarding_receipt.completed)

    def set_future_model(self, name: str) -> None:
        """Select model for FUTURE attempts only; active attempt untouched."""
        self.projection.set_future_model(name)
        if name != "auto" and self.controller is not None:
            self.controller.default_lead_model = name
        if name != "auto" and getattr(self, "runtime_models", None) is not None:
            object.__setattr__(self.runtime_models, "lead_model", name)
        if name != "auto" and ":" in name:
            try:
                from skail.config.persistence import save_user_routing_model

                save_user_routing_model(name)
            except Exception:
                self._append_system_message(
                    "Config warning",
                    "Model selected for this session but could not be persisted.",
                )
        self._save_onboarding_receipt(completed=self.onboarding_receipt.completed)
        if self.app_state == "selection_required" and name != "auto":
            self.app_state = "ready"
            self._append_system_message("Ready", _READY_COPY)
            pending = list(self._pending_prompts)
            self._pending_prompts.clear()
            for prompt in pending:
                self._start_prompt(prompt, record=False)
        self.update_views()

    def set_enabled_models(self, enabled_models: list[str]) -> None:
        """Apply ticked models to routing candidates and persist to config."""
        self._enabled_models = set(enabled_models)
        if hasattr(self, "runtime_models") and self.runtime_models is not None:
            rm = self.runtime_models
            if hasattr(rm, "candidates") and rm.candidates:
                new_cands = []
                for cand in rm.candidates:
                    p = cand.profile
                    is_enabled = (
                        p.model in self._enabled_models
                        or f"{p.provider}:{p.model}" in self._enabled_models
                        or any(m.endswith(f":{p.model}") for m in self._enabled_models)
                    )
                    new_cands.append(cand.model_copy(update={"enabled": is_enabled}))
                object.__setattr__(rm, "candidates", tuple(new_cands))

        # Persist to user config so the user doesn't have to edit config.toml
        provider = self.onboarding_state.provider
        if not provider and hasattr(self, "runtime_models") and self.runtime_models:
            if hasattr(self.runtime_models, "providers") and self.runtime_models.providers:
                provider = next(iter(self.runtime_models.providers.keys()), "default")
        if provider:
            try:
                from skail.config.persistence import save_user_provider_models

                save_user_provider_models(provider, enabled_models)
            except Exception:
                pass

        self._save_onboarding_receipt(completed=self.onboarding_receipt.completed)

        count = len(enabled_models)
        summary = ", ".join(sorted(enabled_models)[:4])
        if count > 4:
            summary += f" +{count - 4} more"
        self._append_system_message(
            "Routing", f"Updated enabled models ({count} ticked): {summary}"
        )
        self.update_views()


    def request_child_cancel(self, child_id: str) -> None:
        """Forward a confirmed child-cancel request to the controller."""
        controller = self.controller
        if controller is not None and hasattr(controller, "request_cancel"):
            try:
                controller.request_cancel(child_id)
                return
            except Exception:
                pass
        self.projection.mark_child_status(child_id, "cancelled", "cancel requested")

    def open_system_pager(self, text: str) -> str:
        """Suspend/pager fallback for Ctrl+Shift+O transcript export."""
        from skail.tui.overlays.transcript import NATIVE_SCROLLBACK_UNAVAILABLE

        try:
            with self.suspend():
                import pydoc

                pydoc.pager(text)
        except Exception:
            pass
        return NATIVE_SCROLLBACK_UNAVAILABLE

    def action_view_budget(self) -> None:
        self._activate_tab("tab-budget", "Budget")

    def action_view_agents(self) -> None:
        self._activate_tab("tab-agents", "Agents")

    def _activate_tab(self, tab: str, label: str) -> None:
        """Switch #tabs and keep #margin-drawer in sync (§6.1/§8.3).

        Textual 1.0.0 delivers no TabActivated for programmatic activation, so the
        drawer is fed synchronously from the same single source as the activation.
        """
        self.query_one("#tabs", TabbedContent).active = tab
        try:
            self.query_one("#margin-drawer", Static).update(render_margin_drawer(label))
        except Exception:
            pass

    def action_view_plan(self) -> None:
        self._activate_tab("tab-plan", "Plan")

    def action_view_route(self) -> None:
        self._activate_tab("tab-route", "Route")

    def on_tabbed_content_activated(self, event: TabbedContent.TabActivated) -> None:
        """Feed #margin-drawer: single source of the active tab name (§6.1/§8.3)."""
        try:
            drawer = self.query_one("#margin-drawer", Static)
        except Exception:
            return
        # ContentTab.label_text is a `str` property in Textual 1.0 (not Tab's method).
        drawer.update(render_margin_drawer(event.tab.label_text))

    def action_view_chat(self) -> None:
        try:
            self.query_one("#composer-input").focus()
        except Exception:
            pass

    def action_transcript_overlay(self) -> None:
        """Push/pop the transcript overlay with focus restore."""
        if "transcript" in self._overlay_stack:
            self.close_overlay("transcript")
            return
        self.open_overlay("transcript")
        try:
            from skail.tui.overlays.transcript import TranscriptOverlay

            chat = self.query_one("#chat-transcript", ChatTranscript)
            try:
                scroll_y = int(chat.scroll_y)
            except Exception:
                scroll_y = 0
            self.push_screen(
                TranscriptOverlay(list(self.projection.transcript_items), scroll_y)
            )
        except Exception:
            pass

    def action_shortcuts_overlay(self) -> None:
        """Push/pop the shortcuts overlay with focus restore (no transcript)."""
        if "shortcuts" in self._overlay_stack:
            self.close_overlay("shortcuts")
            return
        self.open_overlay("shortcuts")
        try:
            from skail.tui.overlays.shortcuts import ShortcutsOverlay

            self.push_screen(ShortcutsOverlay(ACTION_REGISTRY))
        except Exception:
            pass

    def action_missions_overlay(self) -> None:
        """Ctrl+T opens Mission Control (missions wins the binding)."""
        if "missions" in self._overlay_stack:
            self.close_overlay("missions")
            return
        self.open_overlay("missions")
        try:
            from skail.tui.overlays.missions import MissionsOverlay

            self.push_screen(MissionsOverlay(self.projection.children_view()))
        except Exception:
            pass

    def action_theme_picker(self) -> None:
        if "theme_picker" in self._overlay_stack:
            self.close_overlay("theme_picker")
            return
        self.open_overlay("theme_picker")
        self._previous_theme = str(self.current_theme_name)
        try:
            from skail.tui.overlays.theme_picker import ThemePickerOverlay

            self.push_screen(ThemePickerOverlay(str(self.current_theme_name)))
        except Exception:
            pass

    def action_model_picker(self) -> None:
        if "model_picker" in self._overlay_stack:
            self.close_overlay("model_picker")
            return
        self.open_overlay("model_picker")
        try:
            from skail.tui.overlays.model_picker import ModelPickerOverlay

            model_set: set[str] = set()
            model_details: dict[str, dict[str, str]] = {}
            if self.profile_models:
                model_set.update(self.profile_models.values())
            if self.controller is not None:
                if hasattr(self.controller, "models") and self.controller.models:
                    model_set.update(self.controller.models.keys())
                if getattr(self.controller, "default_lead_model", None):
                    model_set.add(self.controller.default_lead_model)
                if getattr(self.controller, "default_child_model", None):
                    model_set.add(self.controller.default_child_model)
            if hasattr(self, "runtime_models") and self.runtime_models is not None:
                rm = self.runtime_models
                if hasattr(rm, "models") and rm.models:
                    model_set.update(rm.models.keys())
                if getattr(rm, "lead_model_name", None):
                    model_set.add(rm.lead_model_name)
                if getattr(rm, "child_model_name", None):
                    model_set.add(rm.child_model_name)
                if hasattr(rm, "candidates") and rm.candidates:
                    for cand in rm.candidates:
                        if hasattr(cand, "profile"):
                            model_set.add(f"{cand.profile.provider}:{cand.profile.model}")
                        elif hasattr(cand, "model") and cand.model:
                            model_set.add(cand.model)
                        elif hasattr(cand, "model_name") and cand.model_name:
                            model_set.add(cand.model_name)
                if hasattr(rm, "catalog") and hasattr(rm.catalog, "profiles"):
                    for p, m in rm.catalog.profiles.keys():
                        key = f"{p}:{m}"
                        model_set.add(key)
                        profile = rm.catalog.profiles[(p, m)]
                        model_details[key] = {
                            "provider": p,
                            "routing": (
                                "routing-enabled" if profile.auto_eligible else "manual-only"
                            ),
                            "input": f"in ${profile.input_usd_per_million}/M"
                            if profile.input_usd_per_million is not None
                            else "in unavailable",
                            "output": f"out ${profile.output_usd_per_million}/M"
                            if profile.output_usd_per_million is not None
                            else "out unavailable",
                            "context": f"ctx {profile.context_tokens}"
                            if profile.context_tokens is not None
                            else "ctx unknown",
                        }

            # Provider-specific standard model sets
            active_p: str | None = self.onboarding_state.provider or None
            if not active_p:
                if self.controller and getattr(self.controller, "providers", None):
                    p_keys = list(self.controller.providers.keys())
                    if p_keys:
                        active_p = str(p_keys[0])

            if active_p == "openai":
                model_set.update({
                    "openai:gpt-4o",
                    "openai:gpt-4o-mini",
                    "openai:o1",
                    "openai:o1-mini",
                    "openai:o3-mini",
                })
            elif active_p == "anthropic":
                model_set.update({
                    "anthropic:claude-3-5-sonnet-latest",
                    "anthropic:claude-3-5-haiku-latest",
                    "anthropic:claude-3-opus-latest",
                })
            if self.bootstrap:
                if self.bootstrap.get("lead_model"):
                    model_set.add(str(self.bootstrap["lead_model"]))
                if self.bootstrap.get("default_model"):
                    model_set.add(str(self.bootstrap["default_model"]))
            current = self.projection.model_for_future()
            if current and current != "auto":
                model_set.add(current)
            if not model_set:
                model_set.add("auto")
            models = sorted(model_set)

            # An empty saved selection is intentional: fresh catalogs start unticked.
            enabled_set = set(self._enabled_models)

            self.push_screen(
                ModelPickerOverlay(
                    models,
                    current,
                    enabled=enabled_set,
                    details=model_details,
                )
            )
        except Exception:
            pass

    def action_model_picker_toggle(self) -> None:
        overlay = self.screen_stack[-1] if self.screen_stack else None
        if overlay is not None and hasattr(overlay, "action_toggle_selected"):
            overlay.action_toggle_selected()

    def action_model_picker_toggle_all(self) -> None:
        overlay = self.screen_stack[-1] if self.screen_stack else None
        if overlay is not None and hasattr(overlay, "action_toggle_filtered"):
            overlay.action_toggle_filtered()

    def action_cycle_mode(self) -> None:
        """Cycle routing mode between Quality, Economy, and Manual."""
        current = (self.projection.footer_data.routing_mode or "quality").lower()
        order = ("quality", "economy", "manual")
        try:
            idx = order.index(current)
            next_mode = order[(idx + 1) % len(order)]
        except ValueError:
            next_mode = "quality"
        self.projection.footer_data.routing_mode = next_mode
        try:
            from skail.tui.widgets.composer import PromptComposer, mode_token

            composer = self.query_one("#prompt-composer", PromptComposer)
            composer.composer_mode = next_mode.upper()
            mode_static = composer.query_one("#composer-mode", Static)
            mode_static.update(
                f"MODE [{mode_token(next_mode.upper())}]{next_mode.upper()}[/]"
            )
        except Exception:
            pass
        self.update_views()

    def action_cycle_panels(self) -> None:
        """Cycle passive panels while returning focus to the composer."""
        order = ("tab-agents", "tab-plan", "tab-route", "tab-budget")
        tabs = self.query_one("#tabs", TabbedContent)
        try:
            index = order.index(tabs.active)
        except ValueError:
            index = 0
        self._activate_tab(order[(index + 1) % len(order)], order[(index + 1) % len(order)][4:])
        self._restore_composer_focus()
        self.update_views()

    def on_prompt_composer_mode_cycle_requested(self, event: Any) -> None:
        _ = event
        self.action_cycle_mode()

    def action_show_help(self) -> None:
        result = dispatch_slash_command("/help", self.projection)
        if result.output_message:
            self.projection.transcript_items.append(
                TranscriptItem(
                    id="help-info",
                    role="system",
                    title="Help",
                    content=result.output_message,
                )
            )
            self.update_views()

    async def action_quit(self) -> None:
        self._begin_shutdown()
        self.exit(0)


__all__ = ["ACTION_REGISTRY", "AppState", "SkailApp"]
