from __future__ import annotations

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from rudder import __version__
from rudder.domain.events import EventEnvelope, UserPayload
from rudder.domain.ids import new_event_id, new_run_id, new_session_id
from rudder.sessions.journal import SessionSnapshot
from rudder.tui.commands import dispatch_slash_command
from rudder.tui.projection import TranscriptItem, TuiProjection
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
    ) -> None:
        super().__init__()
        self.projection = projection or TuiProjection()
        self.background_supported = background_supported
        self.simulated: bool = False

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
        self.update_views()
        self._check_screen_width()

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
            if result.action == "quit":
                self.exit(0)
                return
            if result.action == "view" and result.target_view:
                tabs = self.query_one("#tabs", TabbedContent)
                tab_id = f"tab-{result.target_view}"
                if tab_id in ("tab-agents", "tab-route", "tab-budget"):
                    tabs.active = tab_id
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

    # Interrupt handling
    def on_interrupt_widget_approved(self, event: InterruptWidget.Approved) -> None:
        answer_ev = EventEnvelope(
            event_id=new_event_id(),
            session_id=new_session_id(),
            run_id=new_run_id(),
            sequence=len(self.projection.transcript_items) + 1,
            type="user.answer",
            payload=UserPayload(action="answer", content=event.response),
        )
        self.projection.pending_interrupt = None
        self.apply_event(answer_ev)

    def on_interrupt_widget_rejected(self, event: InterruptWidget.Rejected) -> None:
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
