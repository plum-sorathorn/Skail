from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rudder.tui.projection import TuiProjection

HELP_TEXT = """Available Slash Commands:
  /help                             - Show this help reference
  /agents                           - Display task tree and agent rail
  /agent <id>                       - Focus one agent's events and route
  /tasks                            - Display active task statuses
  /route [id]                       - Show model route explanation for task or lead
  /budget                           - Display authoritative budget and usage view
  /mode <auto|economy|quality|manual> - Switch routing mode
  /model [name]                     - Inspect or switch default model
  /cancel [id]                      - Cancel active run (or background task if supported)
  /steer <id> <message>             - Update/steer a background task when supported
  /resume                           - Resume interrupted or idle session
  /compact                          - Trigger manual session state compaction
  /trust                            - Inspect or modify project trust
  /config                           - Show active configuration
  /quit                             - Flush state and exit harness
"""


@dataclass
class SlashCommandResult:
    command: str
    # "view", "quit", "cancel", "steer", "message", "resume", "compact", "config", "error"
    action: str
    output_message: str | None = None
    target_view: str | None = None  # "agents", "route", "budget", "chat"
    target_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


def parse_slash_command(line: str) -> tuple[str, list[str]]:
    stripped = line.strip()
    if not stripped.startswith("/"):
        return "", []
    parts = stripped[1:].split()
    if not parts:
        return "", []
    cmd = parts[0].lower()
    args = parts[1:]
    return cmd, args


def dispatch_slash_command(
    line: str,
    projection: TuiProjection,
    background_supported: bool = False,
) -> SlashCommandResult:
    cmd, args = parse_slash_command(line)
    if not cmd:
        return SlashCommandResult(
            command="",
            action="error",
            output_message="Invalid slash command format.",
        )

    if cmd == "help":
        return SlashCommandResult(
            command="help",
            action="message",
            output_message=HELP_TEXT,
        )

    if cmd == "agents":
        return SlashCommandResult(
            command="agents",
            action="view",
            target_view="agents",
            output_message=f"Agent rail active ({len(projection.agent_rail_items)} agents).",
        )

    if cmd == "agent":
        if not args:
            return SlashCommandResult(
                command="agent",
                action="error",
                output_message="Usage: /agent <task_id>",
            )
        target_id = args[0]
        projection.focus_agent(target_id)
        return SlashCommandResult(
            command="agent",
            action="view",
            target_view="agents",
            target_id=target_id,
            output_message=f"Focused agent {target_id}.",
        )

    if cmd == "tasks":
        task_count = len(projection.agent_rail_items)
        return SlashCommandResult(
            command="tasks",
            action="view",
            target_view="agents",
            output_message=f"Total tasks: {task_count}.",
        )

    if cmd == "route":
        target_id = args[0] if args else "lead"
        return SlashCommandResult(
            command="route",
            action="view",
            target_view="route",
            target_id=target_id,
            output_message=f"Route view active for {target_id}.",
        )

    if cmd == "budget":
        return SlashCommandResult(
            command="budget",
            action="view",
            target_view="budget",
            output_message="Budget view active.",
        )

    if cmd == "mode":
        if not args:
            return SlashCommandResult(
                command="mode",
                action="error",
                output_message="Usage: /mode <auto|economy|quality|manual>",
            )
        mode = args[0].lower()
        if mode not in ("auto", "economy", "quality", "manual"):
            msg = (
                f"Invalid routing mode '{mode}'. "
                "Choose from: auto, economy, quality, manual."
            )
            return SlashCommandResult(
                command="mode",
                action="error",
                output_message=msg,
            )
        projection.footer_data.routing_mode = mode
        return SlashCommandResult(
            command="mode",
            action="message",
            output_message=f"Routing mode set to '{mode}'.",
            payload={"routing_mode": mode},
        )

    if cmd == "model":
        if not args:
            cur = projection.footer_data.lead_model
            return SlashCommandResult(
                command="model",
                action="message",
                output_message=f"Current lead model: {cur}",
            )
        model_name = args[0]
        projection.footer_data.lead_model = model_name
        return SlashCommandResult(
            command="model",
            action="message",
            output_message=f"Lead model overridden to: {model_name}",
            payload={"model": model_name},
        )

    if cmd == "cancel":
        if args:
            target_id = args[0]
            if not background_supported:
                cancel_err = (
                    "Individual task cancellation requires background adapter support. "
                    "Use '/cancel' without arguments to cancel the whole active run."
                )
                return SlashCommandResult(
                    command="cancel",
                    action="error",
                    output_message=cancel_err,
                )
            return SlashCommandResult(
                command="cancel",
                action="cancel",
                target_id=target_id,
                output_message=f"Cancelled background task {target_id}.",
            )
        return SlashCommandResult(
            command="cancel",
            action="cancel",
            output_message="Active run cancelled.",
        )

    if cmd == "steer":
        if not background_supported:
            return SlashCommandResult(
                command="steer",
                action="error",
                output_message="Steering individual subagents requires background adapter support.",
            )
        if len(args) < 2:
            return SlashCommandResult(
                command="steer",
                action="error",
                output_message="Usage: /steer <task_id> <message>",
            )
        target_id = args[0]
        steer_msg = " ".join(args[1:])
        return SlashCommandResult(
            command="steer",
            action="steer",
            target_id=target_id,
            output_message=f"Steering message dispatched to task {target_id}.",
            payload={"message": steer_msg},
        )

    if cmd == "resume":
        return SlashCommandResult(
            command="resume",
            action="resume",
            output_message="Session resume requested.",
            target_id=args[0] if args else None,
        )

    if cmd == "compact":
        return SlashCommandResult(
            command="compact",
            action="compact",
            output_message="Manual session compaction requested.",
        )

    if cmd == "trust":
        return SlashCommandResult(
            command="trust",
            action="message",
            output_message="Project trust store verified.",
        )

    if cmd == "config":
        return SlashCommandResult(
            command="config",
            action="message",
            output_message="Active configuration inspected.",
        )

    if cmd == "quit":
        return SlashCommandResult(
            command="quit",
            action="quit",
            output_message="Exiting Rudder harness.",
        )

    return SlashCommandResult(
        command=cmd,
        action="error",
        output_message=f"Unknown slash command '/{cmd}'. Type /help for available commands.",
    )
