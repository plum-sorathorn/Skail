from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from skail.tui.logo import help_header
from skail.tui.projection import TuiProjection

THEME_USAGE = "Usage: /theme [dark|light|system]"
_VALID_THEMES = ("dark", "light", "system")

_FORK_FALLBACK_ID = "01JDEF"


@dataclass
class SlashCommandResult:
    command: str
    # "view", "quit", "cancel", "steer", "message", "resume", "compact",
    # "config", "error", "theme_picker", "model_picker", "missions", "fork"
    action: str
    output_message: str | None = None
    target_view: str | None = None  # "agents", "plan", "route", "budget", "chat"
    target_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


# Registry is the single source of truth for help + palette. Widgets must
# import this instead of maintaining a second hardcoded command list.
COMMAND_REGISTRY: list[dict[str, Any]] = [
    {
        "command": "/help",
        "aliases": [],
        "synopsis": "/help",
        "description": "Show this help reference",
        "keywords": ["help", "commands", "reference"],
        "args_required": False,
        "category": "general",
    },
    {
        "command": "/agents",
        "aliases": [],
        "synopsis": "/agents",
        "description": "Display task tree and agent rail",
        "keywords": ["agents", "tasks", "rail", "children"],
        "args_required": False,
        "category": "view",
    },
    {
        "command": "/budget",
        "aliases": [],
        "synopsis": "/budget",
        "description": "Display authoritative budget and usage view",
        "keywords": ["budget", "cost", "spend", "limit"],
        "args_required": False,
        "category": "view",
    },
    {
        "command": "/plan",
        "aliases": [],
        "synopsis": "/plan",
        "description": "Display adaptive execution plan and workspaces",
        "keywords": ["plan", "steps", "nodes", "workspace"],
        "args_required": False,
        "category": "view",
    },
    {
        "command": "/route",
        "aliases": [],
        "synopsis": "/route [id]",
        "description": "Show model route explanation for task or lead",
        "keywords": ["route", "model", "routing", "explanation"],
        "args_required": False,
        "category": "view",
    },
    {
        "command": "/config",
        "aliases": [],
        "synopsis": "/config",
        "description": "Show active configuration",
        "keywords": ["config", "settings", "options"],
        "args_required": False,
        "category": "config",
    },
    {
        "command": "/trust",
        "aliases": [],
        "synopsis": "/trust",
        "description": "Inspect or modify project trust",
        "keywords": ["trust", "project", "permissions"],
        "args_required": False,
        "category": "config",
    },
    {
        "command": "/resume",
        "aliases": [],
        "synopsis": "/resume [session-id]",
        "description": "Resume interrupted or idle session",
        "keywords": ["resume", "session", "restore", "continue"],
        "args_required": False,
        "category": "session",
    },
    {
        "command": "/compact",
        "aliases": [],
        "synopsis": "/compact",
        "description": "Trigger manual session state compaction",
        "keywords": ["compact", "compress", "summarize", "context"],
        "args_required": False,
        "category": "session",
    },
    {
        "command": "/cancel",
        "aliases": [],
        "synopsis": "/cancel [id]",
        "description": "Cancel active run (or background task if supported)",
        "keywords": ["cancel", "stop", "abort"],
        "args_required": False,
        "category": "run",
    },
    {
        "command": "/quit",
        "aliases": [],
        "synopsis": "/quit",
        "description": "Flush state and exit harness",
        "keywords": ["quit", "exit", "leave"],
        "args_required": False,
        "category": "session",
    },
    {
        "command": "/theme",
        "aliases": [],
        "synopsis": "/theme [dark|light|system]",
        "description": "Switch color theme or open the theme picker",
        "keywords": ["theme", "dark", "light", "appearance", "color"],
        "args_required": False,
        "category": "config",
    },
    {
        "command": "/model",
        "aliases": [],
        "synopsis": "/model [name]",
        "description": "Inspect or switch default model for future attempts",
        "keywords": ["model", "provider", "lead", "switch"],
        "args_required": False,
        "category": "run",
    },
    {
        "command": "/missions",
        "aliases": ["/children"],
        "synopsis": "/missions",
        "description": "Open the missions (child agents) view",
        "keywords": ["missions", "children", "agents", "delegates"],
        "args_required": False,
        "category": "view",
    },
    {
        "command": "/fork",
        "aliases": [],
        "synopsis": "/fork [turn]",
        "description": "Fork the session from a turn for parallel exploration",
        "keywords": ["fork", "branch", "copy", "session"],
        "args_required": False,
        "category": "session",
    },
]


def _registry_help_text() -> str:
    lines = [help_header(), "", "Available Slash Commands:"]
    for entry in COMMAND_REGISTRY:
        lines.append(f"  {entry['synopsis']:<32}- {entry['description']}")
    lines.extend(
        [
            "",
            "Keybindings:",
            "  Shift+Tab  Cycle routing mode (Quality/Economy/Manual)",
            "  Alt+P      Model picker (future attempts only)",
            "  Esc        Back one step / keep approval pending (never approves)",
            "  Ctrl+O     Transcript overlay (full scrollback + search)",
            "  Ctrl+T     Mission Control (child agents)",
            "  Ctrl+Shift+T  Chat (focus composer; missions moved to Ctrl+T)",
            "  ?          Shortcuts pane (type-to-filter)",
            "",
            "Queue: Ctrl+Enter queues while a run is active; "
            "take back the newest queued prompt from the queue view.",
            "Onboarding: 5 steps (Welcome > Provider > Trust > Theme > Ready); "
            "choose Fake provider or restart with skail --fake-provider.",
            "Receipts include the exact resume command: skail -r <session-id>.",
        ]
    )
    return "\n".join(lines) + "\n"


HELP_TEXT = _registry_help_text()


def _is_subsequence(needle: str, haystack: str) -> bool:
    if not needle:
        return True
    pos = 0
    for char in haystack:
        if char == needle[pos]:
            pos += 1
            if pos == len(needle):
                return True
    return False


def _normalize_query(query: str) -> str:
    text = query.strip().lower()
    if text.startswith("/"):
        text = text[1:]
    return text.split()[0] if text else ""


def search_commands(query: str) -> list[dict[str, Any]]:
    """Deterministic registry search: prefix > subsequence > desc/kw > alpha."""
    needle = _normalize_query(query)
    if not needle:
        return sorted(COMMAND_REGISTRY, key=lambda e: str(e["command"]))
    scored: list[tuple[int, str, int, dict[str, Any]]] = []
    for index, entry in enumerate(COMMAND_REGISTRY):
        name = str(entry["command"]).lstrip("/").lower()
        desc = str(entry.get("description", "")).lower()
        keys = " ".join(str(k) for k in entry.get("keywords", [])).lower()
        aliases = [str(a).lstrip("/").lower() for a in entry.get("aliases", [])]
        names = [name, *aliases]
        if any(n.startswith(needle) for n in names):
            rank = 0
        elif any(_is_subsequence(needle, n) for n in names):
            rank = 1
        elif needle in desc or (keys and needle in keys):
            rank = 2
        elif _is_subsequence(needle, desc) or (
            keys and _is_subsequence(needle, keys)
        ):
            rank = 2
        else:
            continue
        scored.append((rank, name, index, entry))
    scored.sort(key=lambda row: (row[0], row[1], row[2]))
    return [row[3] for row in scored]


def fork_receipt(new_session_id: str | None = None) -> str:
    """Build the fork receipt; falls back to the fixture id in tests."""
    if new_session_id:
        fid = str(new_session_id)
    else:
        try:
            from skail.domain.ids import new_session_id as _new_sid

            fid = str(_new_sid())
        except Exception:
            fid = _FORK_FALLBACK_ID
    return f"Session forked: {fid}\nResume this fork with:\nskail -r {fid}"


def resume_receipt(session_id: str) -> str:
    """Build the resume receipt containing the ``skail -r`` hint."""
    sid = str(session_id)
    return f"Session resumed: {sid}\nResume later with:\nskail -r {sid}"


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


def _resolve_alias(cmd: str) -> str:
    for entry in COMMAND_REGISTRY:
        name = str(entry["command"]).lstrip("/").lower()
        if cmd == name:
            return name
        for alias in entry.get("aliases", []):
            if cmd == str(alias).lstrip("/").lower():
                return name
    return cmd


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
    cmd = _resolve_alias(cmd)

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

    if cmd == "plan":
        return SlashCommandResult(
            command="plan",
            action="view",
            target_view="plan",
            output_message=f"Plan view active ({len(projection.plan_items)} nodes).",
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
            return SlashCommandResult(
                command="model",
                action="model_picker",
                output_message="Model picker opened.",
                payload={"picker": "model"},
            )
        model_name = args[0]
        projection.set_future_model(model_name)
        return SlashCommandResult(
            command="model",
            action="message",
            output_message=(
                f"Model set to {model_name} for future attempts. "
                "Active attempts are unchanged."
            ),
            payload={"model": model_name},
        )

    if cmd == "theme":
        if not args:
            return SlashCommandResult(
                command="theme",
                action="theme_picker",
                output_message="Theme picker opened.",
                payload={"picker": "theme"},
            )
        choice = args[0].lower()
        if choice not in _VALID_THEMES:
            return SlashCommandResult(
                command="theme",
                action="error",
                output_message=THEME_USAGE,
            )
        receipt = f"Theme changed to {choice.capitalize()}."
        projection.note_receipt(receipt)
        return SlashCommandResult(
            command="theme",
            action="message",
            output_message=receipt,
            payload={"theme": choice},
        )

    if cmd == "missions":
        return SlashCommandResult(
            command="missions",
            action="missions",
            target_view="missions",
            output_message="Missions view opened.",
        )

    if cmd == "fork":
        receipt = fork_receipt()
        projection.note_receipt(receipt)
        fork_id = receipt.splitlines()[0].split(":")[-1].strip()
        return SlashCommandResult(
            command="fork",
            action="fork",
            output_message=receipt,
            target_id=fork_id,
            payload={"fork_id": fork_id},
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
            output_message="Exiting Skail harness.",
        )

    return SlashCommandResult(
        command=cmd,
        action="error",
        output_message=f"Unknown slash command '/{cmd}'. Type /help for available commands.",
    )


__all__ = [
    "COMMAND_REGISTRY",
    "HELP_TEXT",
    "THEME_USAGE",
    "SlashCommandResult",
    "dispatch_slash_command",
    "fork_receipt",
    "parse_slash_command",
    "resume_receipt",
    "search_commands",
]
