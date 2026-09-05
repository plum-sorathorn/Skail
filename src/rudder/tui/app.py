from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from rudder import __version__
from rudder.agents.lead import DelegationMode, LeadControls
from rudder.domain.events import EventEnvelope, UserPayload
from rudder.domain.ids import SessionId, new_event_id, new_run_id, new_session_id
from rudder.domain.routing import RoutingMode
from rudder.runtime.interrupts import QuestionStore
from rudder.runtime.run_controller import RunController
from rudder.sessions.journal import SessionSnapshot
from rudder.sessions.service import SessionService
from rudder.tools.approvals import ApprovalChoice, ApprovalStore
from rudder.tools.execution import CommandRequest
from rudder.tui.commands import dispatch_slash_command
from rudder.tui.projection import InterruptItem, TranscriptItem, TuiProjection
from rudder.tui.widgets.agents import AgentRail
from rudder.tui.widgets.budget import BudgetView
from rudder.tui.widgets.chat import ChatTranscript
from rudder.tui.widgets.composer import PromptComposer
from rudder.tui.widgets.interrupts import InterruptWidget
from rudder.tui.widgets.route import RouteView


class RudderApp(App[int]):
    """Main Textual interactive application for Rudder harness."""

    TITLE = f"Rudder {__version__}"
    CSS = """
    Screen {
        layout: vertical;
        background: $background;
    }
    #main-container {
        width: 100%;
        height: 1fr;
    }
    #chat-container {
        width: 60%;
        height: 100%;
        border-right: solid $primary;
    }
    #sidebar-container {
        width: 40%;
        height: 100%;
    }
    #interrupt-container {
        width: 100%;
        height: auto;
    }
    .narrow #chat-container {
        width: 100%;
        border-right: none;
    }
    .narrow #sidebar-container {
        display: none;
    }
    #status-strip {
        width: 100%;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", priority=True),
        Binding("ctrl+b", "view_budget", "Budget"),
        Binding("ctrl+a", "view_agents", "Agents"),
        Binding("ctrl+r", "view_route", "Route"),
        Binding("ctrl+t", "view_chat", "Chat"),
        Binding("f1", "show_help", "Help"),
    ]

    def __init__(
        self,
        projection: TuiProjection | None = None,
        background_supported: bool = False,
        controller: RunController | None = None,
        session_service: SessionService | None = None,
        session_id: SessionId | None = None,
        approval_store: ApprovalStore | None = None,
        question_store: QuestionStore | None = None,
        initial_prompt: str | None = None,
        max_children: int = 3,
        delegation: DelegationMode = "auto",
        initial_snapshot: SessionSnapshot | None = None,
    ) -> None:
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
        self.simulated: bool = False
        self._active_worker: Any = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(self._render_status_strip(), id="status-strip")
        with Horizontal(id="main-container"):
            with Vertical(id="chat-container"):
                yield ChatTranscript(id="chat-transcript")
                yield Container(id="interrupt-container")
            with Vertical(id="sidebar-container"):
                with TabbedContent(initial="tab-agents", id="tabs"):
                    with TabPane("Agents", id="tab-agents"):
                        yield AgentRail(id="agent-rail")
                    with TabPane("Route", id="tab-route"):
                        yield RouteView(id="route-view")
                    with TabPane("Budget", id="tab-budget"):
                        yield BudgetView(id="budget-view")
        yield PromptComposer(id="prompt-composer")
        yield Footer()

    def on_mount(self) -> None:
        if self.controller is not None:
            self.controller.event_observer = self.apply_event
        if self.initial_snapshot is not None:
            self.projection.apply_snapshot(self.initial_snapshot)
        if self.controller is not None and self.controller.pending_interrupt is not None:
            self._set_interrupt(
                self.controller.pending_interrupt,
                run_id=str(self.initial_snapshot.runs[-1].run_id)
                if self.initial_snapshot and self.initial_snapshot.runs
                else "restored",
            )
        self.update_views()
        self._check_screen_width()
        if self.initial_prompt:
            self.on_prompt_composer_prompt_submitted(
                PromptComposer.PromptSubmitted(self.initial_prompt)
            )

    def on_resize(self) -> None:
        self._check_screen_width()

    def _check_screen_width(self) -> None:
        container = self.query_one("#main-container")
        if self.size.width < 100:
            container.add_class("narrow")
        else:
            container.remove_class("narrow")

    def _render_status_strip(self) -> Text:
        f = self.projection.footer_data
        text = Text()
        text.append(f"Model: {f.lead_model} ", style="bold cyan")
        text.append(f"| Mode: {f.routing_mode} ", style="green")
        text.append(f"| Cost: ${f.session_cost_usd:.4f}", style="yellow")
        if f.budget_limit_usd is not None:
            text.append(f" / ${f.budget_limit_usd:.2f}", style="dim yellow")
        text.append(f" | Active Agents: {f.active_agents_count}", style="magenta")
        return text

    def update_views(self) -> None:
        chat = self.query_one("#chat-transcript", ChatTranscript)
        chat.update_items(self.projection.transcript_items)

        rail = self.query_one("#agent-rail", AgentRail)
        rail.update_items(
            self.projection.agent_rail_items,
            focused_id=self.projection.focused_agent_id,
        )

        route_view = self.query_one("#route-view", RouteView)
        route_view.update_routes(
            self.projection.route_items,
            selected_task_id=self.projection.focused_agent_id,
        )

        budget_view = self.query_one("#budget-view", BudgetView)
        budget_view.update_budget(self.projection.budget_item)

        status_strip = self.query_one("#status-strip", Static)
        status_strip.update(self._render_status_strip())

        # Update interrupt container
        interrupt_container = self.query_one("#interrupt-container", Container)
        interrupt_container.remove_children()
        if self.projection.pending_interrupt:
            interrupt_container.mount(InterruptWidget(self.projection.pending_interrupt))

    def apply_snapshot(self, snapshot: SessionSnapshot) -> None:
        self.projection.apply_snapshot(snapshot)
        self.update_views()

    def apply_event(self, event: EventEnvelope) -> None:
        self.projection.apply_event(event)
        self.update_views()

    async def _execute_prompt(self, text: str) -> None:
        if self.controller is None:
            return
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
        except (KeyboardInterrupt, asyncio.CancelledError):
            self.projection.transcript_items.append(
                TranscriptItem(
                    id=f"cancel-{len(self.projection.transcript_items)}",
                    role="system",
                    title="Cancelled",
                    content="Execution cancelled.",
                )
            )
        except Exception as exc:
            self.projection.transcript_items.append(
                TranscriptItem(
                    id=f"err-{len(self.projection.transcript_items)}",
                    role="error",
                    title="Execution Error",
                    content=str(exc),
                )
            )
        finally:
            self.update_views()

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
        except Exception as exc:
            self.projection.transcript_items.append(
                TranscriptItem(
                    id=f"err-{len(self.projection.transcript_items)}",
                    role="error",
                    title="Resume Error",
                    content=str(exc),
                )
            )
        finally:
            self.update_views()

    def _apply_run_result(self, result: Any) -> None:
        if result.pending_interrupt:
            self._set_interrupt(result.pending_interrupt, run_id=str(result.run_id))
        else:
            self.projection.pending_interrupt = None
        if result.output:
            self.projection.transcript_items.append(
                TranscriptItem(
                    id=f"lead-{len(self.projection.transcript_items)}",
                    role="lead",
                    title="Rudder Response",
                    content=result.output,
                )
            )

    def _set_interrupt(self, payload: dict[str, Any], *, run_id: str) -> None:
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

    # User input handling
    def on_prompt_composer_prompt_submitted(
        self, event: PromptComposer.PromptSubmitted
    ) -> None:
        text = event.text
        if text.startswith("/"):
            result = dispatch_slash_command(
                text,
                self.projection,
                background_supported=self.background_supported,
            )
            if result.command == "config" and self.controller is not None:
                result.output_message = json.dumps(
                    self.controller.redaction.scrub(self.controller.config_snapshot),
                    sort_keys=True,
                )
            elif result.command == "trust" and self.controller is not None:
                trusted = bool(self.controller.config_snapshot.get("project_trusted", False))
                result.output_message = (
                    "Project is trusted." if trusted else "Project is untrusted."
                )
            if result.action == "quit":
                if self._active_worker is not None:
                    self._active_worker.cancel()
                if self.session_service is not None and self.session_id is not None:
                    self.session_service.journal.update_session_status(
                        session_id=str(self.session_id), status="idle"
                    )
                self.exit(0)
                return
            if result.action == "view" and result.target_view:
                tabs = self.query_one("#tabs", TabbedContent)
                tab_id = f"tab-{result.target_view}"
                if tab_id in ("tab-agents", "tab-route", "tab-budget"):
                    tabs.active = tab_id
            elif result.action == "cancel":
                if self._active_worker is not None:
                    self._active_worker.cancel()
                    self._active_worker = None
            elif (
                result.action == "resume"
                and self.session_service is not None
            ):
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
                from rudder.sessions.compaction import (
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

        # Ordinary prompt submitted
        self.projection.transcript_items.append(
            TranscriptItem(
                id=f"user-{len(self.projection.transcript_items)}",
                role="user",
                title="User Prompt",
                content=text,
            )
        )
        self.update_views()
        if self.controller is not None:
            previous = self._active_worker
            if previous is not None and not previous.is_finished:
                self.projection.transcript_items.append(
                    TranscriptItem(
                        id=f"queue-{len(self.projection.transcript_items)}",
                        role="system",
                        title="Follow-up queued",
                        content="This prompt will run after the active foreground request.",
                    )
                )
                self._active_worker = self.run_worker(
                    self._execute_follow_up(previous, text), exclusive=False
                )
            else:
                self._active_worker = self.run_worker(
                    self._execute_prompt(text), exclusive=False
                )

    # Interrupt handling
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
            self._active_worker = self.run_worker(
                self._resume_prompt(event.response), exclusive=True
            )
            self.update_views()
            return
        if self.question_store is not None:
            try:
                self.question_store.answer(
                    event.approval_id, event.response, graph_id="lead"
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
                        str(pending.payload["question_id"]), graph_id="lead"
                    )
                except Exception:
                    pass
            self.controller.reject_interrupted()
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

    def on_agent_rail_agent_selected(self, event: AgentRail.AgentSelected) -> None:
        self.projection.focus_agent(event.task_id)
        tabs = self.query_one("#tabs", TabbedContent)
        tabs.active = "tab-route"
        self.update_views()

    # Keybinding actions
    def action_view_budget(self) -> None:
        self.query_one("#tabs", TabbedContent).active = "tab-budget"

    def action_view_agents(self) -> None:
        self.query_one("#tabs", TabbedContent).active = "tab-agents"

    def action_view_route(self) -> None:
        self.query_one("#tabs", TabbedContent).active = "tab-route"

    def action_view_chat(self) -> None:
        self.query_one("#composer-input").focus()

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
