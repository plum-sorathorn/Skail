from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from rudder import __version__
from rudder.cli.commands import (
    handle_auth,
    handle_config,
    handle_models,
    handle_sessions,
    handle_smoke,
)
from rudder.cli.exit_codes import (
    EXIT_FAILURE,
    EXIT_OK,
    EXIT_USAGE,
)
from rudder.cli.render import (
    render_jsonl_event,
    render_print_stderr,
    render_print_stdout,
)
from rudder.config.paths import (
    default_checkpoints_path,
    default_journal_path,
    sessions_dir,
    user_data_dir,
)
from rudder.config.trust import ProjectTrustStore
from rudder.domain.events import EventEnvelope, LifecyclePayload
from rudder.domain.ids import SessionId, new_event_id, new_run_id
from rudder.domain.security import ProjectTrustLevel, identify_workspace
from rudder.domain.sessions import SessionRecord
from rudder.sessions.checkpoints import CheckpointStore
from rudder.sessions.journal import Journal
from rudder.sessions.service import SessionService

REMOVED_ALIASES = frozenset(
    {"proxy", "serve", "oma", "daemon", "plugin", "slm", "--proxy", "--port", "--host"}
)


KNOWN_SUBCOMMANDS = frozenset({"auth", "models", "sessions", "config", "smoke"})
OPTIONS_WITH_ARG = frozenset({
    "--mode",
    "--model",
    "--lead-model",
    "--agent-model",
    "--budget",
    "--max-agents",
    "--delegation",
    "--workspace",
    "-r",
    "--resume",
    "-o",
    "--output",
})


def find_subcommand(raw_args: Sequence[str]) -> str | None:
    i = 0
    while i < len(raw_args):
        arg = raw_args[i]
        if arg in OPTIONS_WITH_ARG:
            i += 2
            continue
        if any(arg.startswith(f"{opt}=") for opt in OPTIONS_WITH_ARG):
            i += 1
            continue
        if arg.startswith("-"):
            i += 1
            continue
        return arg if arg in KNOWN_SUBCOMMANDS else None
    return None


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--version", action="version", version=f"rudder {__version__}")

    # Output modes
    parser.add_argument(
        "-p",
        "--print",
        dest="print_mode",
        action="store_true",
        help="non-interactive print mode: emit final response to stdout, diagnostics to stderr",
    )
    parser.add_argument(
        "--json",
        dest="json_mode",
        action="store_true",
        help="non-interactive JSONL mode: emit versioned EventEnvelope objects to stdout",
    )

    # Session flags
    parser.add_argument(
        "-c",
        "--continue",
        dest="continue_session",
        action="store_true",
        help="continue the latest session",
    )
    parser.add_argument(
        "-r",
        "--resume",
        dest="resume_session",
        nargs="?",
        const="",
        default=None,
        help="resume a specific session ID or the latest session",
    )
    parser.add_argument(
        "--no-session",
        dest="no_session",
        action="store_true",
        help="run without persisting session state",
    )

    # Routing, models, and budgets
    parser.add_argument(
        "--mode",
        dest="routing_mode",
        choices=["auto", "economy", "quality", "manual"],
        default=None,
        help="routing mode",
    )
    parser.add_argument(
        "--model",
        dest="default_model",
        default=None,
        help="default provider:model override",
    )
    parser.add_argument(
        "--lead-model",
        dest="lead_model",
        default=None,
        help="lead agent provider:model override",
    )
    parser.add_argument(
        "--agent-model",
        dest="agent_models",
        action="append",
        default=[],
        help="profile-bound model override: PROFILE=PROVIDER:MODEL",
    )
    parser.add_argument("--budget", dest="budget", default=None, help="run budget in USD")
    parser.add_argument(
        "--max-agents",
        dest="max_agents",
        type=int,
        choices=[1, 2, 3],
        default=None,
        help="maximum concurrent child agents (1-3)",
    )
    parser.add_argument(
        "--delegation",
        dest="delegation",
        choices=["auto", "ask", "off"],
        default=None,
        help="delegation control policy",
    )
    parser.add_argument(
        "--workspace",
        dest="workspace_mode",
        choices=["shared", "worktree"],
        default=None,
        help="workspace concurrency mode",
    )

    # Project trust
    parser.add_argument(
        "--approve-project",
        dest="approve_project",
        action="store_true",
        help="mark current project as trusted",
    )
    parser.add_argument(
        "--deny-project",
        dest="deny_project",
        action="store_true",
        help="mark current project as denied",
    )
    parser.add_argument(
        "--fake-provider",
        dest="fake_provider",
        action="store_true",
        help="use deterministic offline fake provider",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the full CLI parser including subparsers for help/inspection."""
    parser = argparse.ArgumentParser(
        prog="rudder",
        description="Rudder - a native budget-aware multi-agent coding harness.",
    )
    _add_common_options(parser)

    # Subcommands
    subparsers = parser.add_subparsers(dest="subcommand")

    # auth
    auth_parser = subparsers.add_parser("auth", help="manage and check provider credentials")
    auth_sub = auth_parser.add_subparsers(dest="auth_action")
    auth_sub.add_parser("status", help="check status of provider credentials")
    auth_sub.add_parser("check", help="verify provider credentials and reachability")

    # models
    models_parser = subparsers.add_parser("models", help="inspect models and profiles")
    models_sub = models_parser.add_subparsers(dest="models_action")
    models_sub.add_parser("list", help="list models and profiles")
    models_show = models_sub.add_parser("show", help="show model or profile details")
    models_show.add_argument("model_name", nargs="?", default=None)

    # sessions
    sessions_parser = subparsers.add_parser("sessions", help="manage and inspect sessions")
    sessions_sub = sessions_parser.add_subparsers(dest="sessions_action")
    sessions_sub.add_parser("list", help="list stored sessions")
    sessions_show = sessions_sub.add_parser("show", help="show session summary")
    sessions_show.add_argument("session_id", nargs="?", default=None)
    sessions_exp = sessions_sub.add_parser("export", help="export session record")
    sessions_exp.add_argument("session_id")
    sessions_exp.add_argument("--output", "-o", default=None, help="output file path")
    sessions_arch = sessions_sub.add_parser("archive", help="archive a session")
    sessions_arch.add_argument("session_id")
    sessions_res = sessions_sub.add_parser("resume", help="resume an interrupted/idle session")
    sessions_res.add_argument("session_id")

    # config
    config_parser = subparsers.add_parser("config", help="inspect configuration")
    config_sub = config_parser.add_subparsers(dest="config_action")
    config_sub.add_parser("show", help="display resolved layered configuration")
    config_sub.add_parser("path", help="display configuration file paths")

    # smoke
    smoke_parser = subparsers.add_parser("smoke", help="run offline package smoke check")
    smoke_parser.add_argument("--fake-provider", action="store_true", default=False)

    return parser


def build_run_parser() -> argparse.ArgumentParser:
    """Build the run parser for root prompt execution without subcommands."""
    parser = argparse.ArgumentParser(
        prog="rudder",
        description="Rudder - a native budget-aware multi-agent coding harness.",
    )
    _add_common_options(parser)
    parser.add_argument("prompt", nargs="*", help="prompt or task description for Rudder")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)

    # 1. Reject removed AutoConduck aliases and options immediately
    for token in raw_args:
        if token.lower() in REMOVED_ALIASES:
            render_print_stderr(
                f"Error: '{token}' is removed and not supported in Rudder. "
                "Rudder launches the harness directly without proxies or daemons."
            )
            return EXIT_USAGE

    subcmd = find_subcommand(raw_args)
    if subcmd is not None or "-h" in raw_args or "--help" in raw_args:
        parser = build_parser()
    else:
        parser = build_run_parser()

    try:
        args = parser.parse_args(raw_args)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else EXIT_USAGE
        return EXIT_USAGE if code != 0 else EXIT_OK

    if not hasattr(args, "prompt"):
        args.prompt = []
    if not hasattr(args, "subcommand"):
        args.subcommand = None

    # 2. Check for conflicting flags
    if args.print_mode and args.json_mode:
        render_print_stderr("Error: cannot specify both --print and --json.")
        return EXIT_USAGE

    if args.approve_project and args.deny_project:
        render_print_stderr("Error: cannot specify both --approve-project and --deny-project.")
        return EXIT_USAGE

    # 3. Handle project trust operations
    if args.approve_project or args.deny_project:
        workspace = Path.cwd()
        identity = identify_workspace(workspace)
        trust_store = ProjectTrustStore(user_data_dir() / "trust.sqlite")
        if args.approve_project:
            trust_store.set_level(identity, ProjectTrustLevel.TRUSTED)
            render_print_stdout(f"Project at {workspace} is now TRUSTED.")
        else:
            trust_store.set_level(identity, ProjectTrustLevel.DENIED)
            render_print_stdout(f"Project at {workspace} is now DENIED.")
        return EXIT_OK

    workspace = Path.cwd()

    # 4. Handle stateless subcommands before journal/checkpoint storage init
    if args.subcommand == "smoke":
        return handle_smoke(args)
    if args.subcommand == "config":
        return handle_config(args, workspace)
    if args.subcommand == "auth":
        return handle_auth(args)
    if args.subcommand == "models":
        return handle_models(args)

    # 5. Storage and session initialization
    if args.no_session:
        import tempfile
        temp_dir = Path(tempfile.mkdtemp(prefix="rudder-ephemeral-"))
        journal = Journal(temp_dir / "journal.sqlite")
        checkpoints = CheckpointStore(temp_dir / "checkpoints.sqlite")
        s_dir = temp_dir / "sessions"
    else:
        journal = Journal(default_journal_path())
        checkpoints = CheckpointStore(default_checkpoints_path())
        s_dir = sessions_dir()

    journal.migrate()
    checkpoints.initialize()
    session_service = SessionService(
        journal=journal,
        checkpoints=checkpoints,
        sessions_dir=s_dir,
    )

    if args.subcommand == "sessions":
        return handle_sessions(args, session_service, journal)

    # 6. Check prompt or session resumption
    prompt_text = " ".join(args.prompt).strip()
    if not prompt_text and not args.continue_session and args.resume_session is None:
        if args.print_mode or args.json_mode:
            render_print_stderr("Error: prompt required in non-interactive print or JSONL mode.")
            return EXIT_USAGE
        if sys.stdin.isatty():
            from rudder.tui.app import RudderApp
            app = RudderApp()
            return app.run() or EXIT_OK
        # Non-interactive without prompt
        render_print_stdout(f"Rudder {__version__} interactive harness ready.")
        render_print_stdout("Use 'rudder [PROMPT]' or slash commands. Type '/quit' to exit.")
        return EXIT_OK

    if not args.print_mode and not args.json_mode and sys.stdin.isatty():
        from rudder.tui.app import RudderApp
        from rudder.tui.projection import TranscriptItem
        app = RudderApp()
        if prompt_text:
            app.projection.transcript_items.append(
                TranscriptItem(
                    id=f"user-{len(app.projection.transcript_items)}",
                    role="user",
                    title="User Prompt",
                    content=prompt_text,
                )
            )
        return app.run() or EXIT_OK

    # Resolve active session
    if args.resume_session is not None:
        target_sid = args.resume_session
        if not target_sid:
            sessions = session_service.list_sessions()
            if not sessions:
                render_print_stderr("Error: no existing session to resume.")
                return EXIT_FAILURE
            target_sid = sessions[0].session_id
        resume_result = session_service.resume_session(target_sid)
        if not resume_result.ok:
            render_print_stderr(
                f"Error resuming session {target_sid}: {resume_result.recovery_error}"
            )
            return EXIT_FAILURE
        session_record = resume_result.session
    elif args.continue_session:
        sessions = session_service.list_sessions()
        if not sessions:
            render_print_stderr("Error: no existing session to continue.")
            return EXIT_FAILURE
        session_record = sessions[0]
    else:
        session_record = session_service.create_session(
            title=prompt_text[:50] or "New Session",
        )

    # 7. Execute instruction
    return asyncio.run(
        _execute_instruction(
            prompt=prompt_text,
            session=session_record,
            journal=journal,
            workspace=workspace,
            args=args,
        )
    )


async def _execute_instruction(
    *,
    prompt: str,
    session: SessionRecord,
    journal: Journal,
    workspace: Path,
    args: argparse.Namespace,
) -> int:
    from rudder.agents.lead import LeadControls
    from rudder.providers.fake import DeterministicFakeChatModel
    from rudder.runtime.run_controller import RunController

    lead_model_name = args.lead_model or args.default_model or "lead-model"
    child_model_name = args.default_model or "implementer-model"

    lead_fake = DeterministicFakeChatModel(
        model_name=lead_model_name,
        response_text=f"Rudder completed task: {prompt}",
    )
    models = {
        lead_model_name: lead_fake,
        "lead-model": lead_fake,
        "implementer-model": lead_fake,
        "fake:fast-model": lead_fake,
        "fake:smart-model": lead_fake,
    }

    budget_usd = Decimal(str(args.budget)) if args.budget else Decimal("10.00")
    controls = LeadControls(
        model=args.lead_model,
        max_children=args.max_agents or 3,
        delegation=args.delegation or "auto",
    )

    run_id = new_run_id()
    controller = RunController(
        session_id=SessionId(session.session_id),
        workspace=workspace,
        journal=journal,
        models=models,
        default_lead_model=lead_model_name,
        default_child_model=child_model_name,
        budget_limit_usd=budget_usd,
    )

    session_id_val = SessionId(session.session_id)

    if args.json_mode:
        start_event = EventEnvelope(
            event_id=new_event_id(),
            session_id=session_id_val,
            run_id=run_id,
            sequence=1,
            type="run.started",
            payload=LifecyclePayload(status="started"),
        )
        render_jsonl_event(start_event)

    try:
        result = await controller.run_instruction(prompt, controls=controls)
    except Exception as exc:
        if args.json_mode:
            fail_event = EventEnvelope(
                event_id=new_event_id(),
                session_id=session_id_val,
                run_id=run_id,
                sequence=2,
                type="run.failed",
                payload=LifecyclePayload(status="failed"),
            )
            render_jsonl_event(fail_event)
        render_print_stderr(f"Execution failed: {exc}")
        return EXIT_FAILURE

    # Output rendering
    if args.json_mode:
        # Emit terminal event
        terminal_event = EventEnvelope(
            event_id=new_event_id(),
            session_id=session_id_val,
            run_id=run_id,
            sequence=2,
            type="run.completed",
            payload=LifecyclePayload(status="completed"),
        )
        render_jsonl_event(terminal_event)
    elif args.print_mode:
        render_print_stderr(f"[INFO] Run {result.run_id} completed successfully.")
        render_print_stdout(result.output)
    else:
        render_print_stdout(result.output)

    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
