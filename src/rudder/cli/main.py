from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from rudder import __version__
from rudder.cli.commands import (
    handle_auth,
    handle_config,
    handle_models,
    handle_sessions,
    handle_smoke,
)
from rudder.cli.exit_codes import (
    EXIT_BLOCKED,
    EXIT_CANCELLED,
    EXIT_FAILURE,
    EXIT_OK,
    EXIT_USAGE,
)
from rudder.cli.render import (
    render_jsonl_event,
    render_print_stderr,
    render_print_stdout,
)
from rudder.config.loader import ConfigValidationError, load_config
from rudder.config.models import RudderConfig
from rudder.config.paths import (
    default_checkpoints_path,
    default_journal_path,
    project_config_path,
    sessions_dir,
    user_config_path,
    user_data_dir,
)
from rudder.config.trust import ProjectTrustStore
from rudder.domain.ids import SessionId, new_run_id
from rudder.domain.routing import RoutingMode
from rudder.domain.security import ProjectTrustLevel, identify_workspace
from rudder.domain.sessions import SessionRecord
from rudder.providers.credentials import EnvironmentCredentialResolver
from rudder.providers.errors import ProviderConfigurationError
from rudder.runtime.interrupts import QuestionStore
from rudder.runtime.redaction import RedactionRegistry
from rudder.sessions.checkpoints import CheckpointStore
from rudder.sessions.journal import Journal
from rudder.sessions.service import SessionService
from rudder.tools.approvals import ApprovalStore

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
        "--jsonl",
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


def _build_storage(
    *,
    no_session: bool,
    redaction: RedactionRegistry,
    ephemeral_dir: Path | None = None,
) -> tuple[Journal, CheckpointStore, Path]:
    if no_session:
        if ephemeral_dir is None:
            import tempfile

            ephemeral_dir = Path(tempfile.mkdtemp(prefix="rudder-ephemeral-"))
        journal_path = ephemeral_dir / "journal.sqlite"
        checkpoints_path = ephemeral_dir / "checkpoints.sqlite"
        session_path = ephemeral_dir / "sessions"
    else:
        journal_path = default_journal_path()
        checkpoints_path = default_checkpoints_path()
        session_path = sessions_dir()
    return (
        Journal(journal_path, redactor=redaction),
        CheckpointStore(checkpoints_path, redactor=redaction),
        session_path,
    )


def _parse_agent_models(values: Sequence[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError("--agent-model must use PROFILE=PROVIDER:MODEL")
        profile, model = value.split("=", 1)
        if not profile.strip() or ":" not in model or not all(model.split(":", 1)):
            raise ValueError("--agent-model must use PROFILE=PROVIDER:MODEL")
        parsed[profile.strip()] = model.strip()
    return parsed


def _apply_run_config(args: argparse.Namespace, config: RudderConfig) -> None:
    args.provider_configs = config.providers
    if args.routing_mode is None:
        args.routing_mode = config.routing.mode
    if args.lead_model is None and config.routing.lead_model != "auto":
        args.lead_model = config.routing.lead_model
    if args.budget is None:
        args.budget = config.budget.run_usd
    args.budget_warning_percent = config.budget.warning_percent
    if args.max_agents is None:
        args.max_agents = config.orchestration.max_agents
    if args.delegation is None:
        args.delegation = config.orchestration.delegation
    if args.workspace_mode is None:
        args.workspace_mode = config.orchestration.workspace_mode


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

    identity = identify_workspace(workspace)
    trust_store = ProjectTrustStore(user_data_dir() / "trust.sqlite")
    trusted = trust_store.assess(identity).level is ProjectTrustLevel.TRUSTED
    cli_overrides: dict[str, Any] = {}
    if args.routing_mode is not None:
        cli_overrides["routing.mode"] = args.routing_mode
    if args.lead_model is not None:
        cli_overrides["routing.lead_model"] = args.lead_model
    if args.budget is not None:
        cli_overrides["budget.run_usd"] = args.budget
    if args.max_agents is not None:
        cli_overrides["orchestration.max_agents"] = args.max_agents
    if args.delegation is not None:
        cli_overrides["orchestration.delegation"] = args.delegation
    if args.workspace_mode is not None:
        cli_overrides["orchestration.workspace_mode"] = args.workspace_mode
    try:
        resolved_config = load_config(
            user_path=user_config_path(),
            project_path=project_config_path(workspace),
            project_trusted=trusted,
            cli_overrides=cli_overrides,
        )
        _apply_run_config(args, resolved_config.config)
        profile_models = _parse_agent_models(args.agent_models)
    except (ConfigValidationError, ValueError) as exc:
        render_print_stderr(f"Configuration error: {exc}")
        return EXIT_USAGE
    if args.workspace_mode == "worktree":
        render_print_stderr(
            "Configuration error: worktree mode is not available in the stable foreground runtime."
        )
        return EXIT_USAGE

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
    redaction = RedactionRegistry()
    journal, checkpoints, s_dir = _build_storage(
        no_session=args.no_session,
        redaction=redaction,
    )

    journal.migrate()
    checkpoints.initialize()
    session_service = SessionService(
        journal=journal,
        checkpoints=checkpoints,
        sessions_dir=s_dir,
    )

    if args.subcommand == "sessions":
        return handle_sessions(args, session_service, journal)

    # 6. Resolve active session
    prompt_text = " ".join(args.prompt).strip()
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
        assert resume_result.session is not None
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

    # 7. Check non-interactive prompt requirements
    if not prompt_text and not args.continue_session and args.resume_session is None:
        if args.print_mode or args.json_mode:
            render_print_stderr("Error: prompt required in non-interactive print or JSONL mode.")
            return EXIT_USAGE
        if not sys.stdin.isatty():
            render_print_stdout(f"Rudder {__version__} interactive harness ready.")
            render_print_stdout("Use 'rudder [PROMPT]' or slash commands. Type '/quit' to exit.")
            return EXIT_OK

    approvals = ApprovalStore(workspace / ".rudder" / "approvals.sqlite")
    question_store = QuestionStore(workspace / ".rudder" / "questions.sqlite")

    # 8. Interactive TUI execution
    if not args.print_mode and not args.json_mode and sys.stdin.isatty():
        try:
            models, lead_model_name, child_model_name = _build_runtime_models(
                args, redaction, prompt_text
            )
        except ProviderConfigurationError as exc:
            render_print_stderr(f"Provider configuration error: {exc}")
            return EXIT_FAILURE
        from rudder.runtime.run_controller import RunController
        from rudder.tui.app import RudderApp

        budget_usd = Decimal(str(args.budget)) if args.budget is not None else None
        controller = RunController(
            session_id=SessionId(session_record.session_id),
            workspace=workspace,
            journal=journal,
            checkpoints=checkpoints,
            redaction=redaction,
            models=models,
            default_lead_model=lead_model_name,
            default_child_model=child_model_name,
            budget_limit_usd=budget_usd,
            budget_warning_percent=args.budget_warning_percent,
            approvals=approvals,
            question_store=question_store,
            profile_models=profile_models,
        )
        app = RudderApp(
            controller=controller,
            session_service=session_service,
            session_id=SessionId(session_record.session_id),
            approval_store=approvals,
            question_store=question_store,
            initial_prompt=prompt_text or None,
            max_children=args.max_agents,
            delegation=args.delegation,
        )
        return app.run() or EXIT_OK

    # 9. Non-interactive execution
    return asyncio.run(
        _execute_instruction(
            prompt=prompt_text,
            session=session_record,
            journal=journal,
            checkpoints=checkpoints,
            redaction=redaction,
            approvals=approvals,
            question_store=question_store,
            workspace=workspace,
            args=args,
        )
    )


def _build_runtime_models(
    args: argparse.Namespace,
    redaction: RedactionRegistry,
    prompt: str = "",
) -> tuple[dict[str, Any], str, str]:
    from rudder.providers.fake import DeterministicFakeChatModel

    lead_model_name = args.lead_model or args.default_model or "lead-model"
    child_model_name = args.default_model or "implementer-model"

    if getattr(args, "fake_provider", False):
        resp = (
            f"Rudder completed task: {prompt}"
            if prompt
            else "Rudder completed task."
        )
        lead_fake = DeterministicFakeChatModel(
            model_name=lead_model_name,
            response_text=resp,
        )
        models = {
            lead_model_name: lead_fake,
            child_model_name: lead_fake,
            "lead-model": lead_fake,
            "implementer-model": lead_fake,
            "fake:fast-model": lead_fake,
            "fake:smart-model": lead_fake,
        }
        return models, lead_model_name, child_model_name

    cred_resolver = EnvironmentCredentialResolver(redaction)
    candidate_providers = ("llmgateway", "openai", "anthropic")
    provider_configs = getattr(args, "provider_configs", {})
    resolved_cred = None
    selected_provider = None
    selected_config = None

    if ":" in lead_model_name:
        p_name = lead_model_name.split(":", 1)[0]
        selected_config = provider_configs.get(p_name)
        env_var = selected_config.api_key_env if selected_config is not None else None
        if env_var is None:
            env_var = (
                "LLMGATEWAY_API_KEY"
                if p_name == "llmgateway"
                else "OPENAI_API_KEY"
                if p_name == "openai"
                else "ANTHROPIC_API_KEY"
                if p_name == "anthropic"
                else None
            )
        if env_var and os.environ.get(env_var):
            try:
                resolved_cred = cred_resolver.resolve(p_name, env_var)
                selected_provider = p_name
            except Exception:
                pass
    else:
        for p_name in candidate_providers:
            candidate_config = provider_configs.get(p_name)
            env_var = candidate_config.api_key_env if candidate_config is not None else None
            if env_var is None:
                env_var = (
                    "LLMGATEWAY_API_KEY"
                    if p_name == "llmgateway"
                    else "OPENAI_API_KEY"
                    if p_name == "openai"
                    else "ANTHROPIC_API_KEY"
                    if p_name == "anthropic"
                    else None
                )
            if env_var and os.environ.get(env_var):
                try:
                    resolved_cred = cred_resolver.resolve(p_name, env_var)
                    selected_provider = p_name
                    selected_config = candidate_config
                    break
                except Exception:
                    pass

    if resolved_cred is None or selected_provider is None:
        raise ProviderConfigurationError(
            "default",
            "No provider credentials configured in environment. "
            "Set LLMGATEWAY_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY, "
            "or pass --fake-provider for deterministic offline execution.",
        )

    models_dict: dict[str, Any] = {}
    if selected_provider == "llmgateway":
        from rudder.config.models import ProviderConfig
        from rudder.providers.base import ModelOptions
        from rudder.providers.llmgateway import LLMGATEWAY_BASE_URL, LLMGatewayAdapter
        from rudder.providers.models import ModelProfile

        actual_model = (
            lead_model_name.split(":")[-1] if ":" in lead_model_name else "gpt-4o"
        )
        cfg = selected_config or ProviderConfig(
            type="openai_compatible", base_url=LLMGATEWAY_BASE_URL, models=(actual_model,)
        )
        adapter = LLMGatewayAdapter(cfg, api_key=resolved_cred.reveal())
        profile = ModelProfile(
            provider="llmgateway",
            model=actual_model,
            context_tokens=128000,
            input_usd_per_million=Decimal("0.15"),
            output_usd_per_million=Decimal("0.60"),
        )
        chat_model = adapter.create_model(profile, ModelOptions())
        models_dict[lead_model_name] = chat_model
        models_dict[actual_model] = chat_model
        models_dict[child_model_name] = chat_model
    else:
        from rudder.providers.langchain import LangChainModelFactory
        from rudder.providers.registry import LangChainProviderRegistry, ProviderRegistration

        actual_model = (
            lead_model_name.split(":")[-1]
            if ":" in lead_model_name
            else ("gpt-4o-mini" if selected_provider == "openai" else "claude-3-5-sonnet-latest")
        )
        reg = LangChainProviderRegistry(
            registrations=(
                ProviderRegistration(
                    name=selected_provider,
                    module=f"langchain_{selected_provider}",
                    package=f"langchain-{selected_provider}",
                    extra=selected_provider,
                    contract_tested=True,
                    auto_routing_eligible=True,
                    maintained_ci=True,
                    allowed_options=frozenset(
                        {"api_key", "temperature", "max_tokens", "timeout"}
                    ),
                ),
            )
        )
        factory = LangChainModelFactory(reg)
        chat_model = factory.create(
            provider=selected_provider,
            model=actual_model,
            options={"api_key": resolved_cred.reveal()},
        )
        models_dict[lead_model_name] = chat_model
        models_dict[actual_model] = chat_model
        models_dict[child_model_name] = chat_model

    if args.default_model is None:
        child_model_name = f"{selected_provider}:{actual_model}"
        lead_model_name = f"{selected_provider}:{actual_model}"
        models_dict[lead_model_name] = chat_model

    return models_dict, lead_model_name, child_model_name


async def _execute_instruction(
    *,
    prompt: str,
    session: SessionRecord,
    journal: Journal,
    checkpoints: CheckpointStore,
    redaction: RedactionRegistry,
    approvals: ApprovalStore,
    question_store: QuestionStore,
    workspace: Path,
    args: argparse.Namespace,
) -> int:
    from rudder.agents.lead import LeadControls
    from rudder.runtime.run_controller import RunController

    try:
        models, lead_model_name, child_model_name = _build_runtime_models(
            args, redaction, prompt
        )
    except ProviderConfigurationError as exc:
        render_print_stderr(f"Provider configuration error: {exc}")
        return EXIT_FAILURE

    budget_usd = Decimal(str(args.budget)) if args.budget is not None else None
    controls = LeadControls(
        model=args.lead_model or args.default_model,
        max_children=args.max_agents or 3,
        delegation=args.delegation or "auto",
        routing_mode=RoutingMode(getattr(args, "routing_mode", None) or "auto"),
    )

    run_id = new_run_id()
    controller = RunController(
        session_id=SessionId(session.session_id),
        workspace=workspace,
        journal=journal,
        checkpoints=checkpoints,
        redaction=redaction,
        models=models,
        default_lead_model=lead_model_name,
        default_child_model=child_model_name,
        budget_limit_usd=budget_usd,
        budget_warning_percent=getattr(args, "budget_warning_percent", 80),
        approvals=approvals,
        question_store=question_store,
        profile_models=_parse_agent_models(getattr(args, "agent_models", [])),
        event_observer=render_jsonl_event if args.json_mode else None,
    )

    try:
        result = await controller.run_instruction(prompt, controls=controls, run_id=run_id)
    except (KeyboardInterrupt, asyncio.CancelledError):
        render_print_stderr(f"Execution cancelled on run {run_id}.")
        return EXIT_CANCELLED
    except Exception as exc:
        render_print_stderr(f"Execution failed: {exc}")
        return EXIT_FAILURE

    if result.status == "blocked":
        if args.print_mode:
            render_print_stderr(
                f"Execution blocked on run {result.run_id}: approval, budget, safety policy, "
                "or user interaction prevented execution."
            )
        return EXIT_BLOCKED
    if result.status == "cancelled":
        if args.print_mode:
            render_print_stderr(f"Execution cancelled on run {result.run_id}.")
        return EXIT_CANCELLED
    if result.status == "failed":
        if args.print_mode:
            render_print_stderr(f"Execution failed on run {result.run_id}.")
        return EXIT_FAILURE

    # Output rendering for completed status
    if args.print_mode:
        render_print_stderr(f"[INFO] Run {result.run_id} completed successfully.")
        render_print_stdout(result.output)
    elif not args.json_mode:
        render_print_stdout(result.output)

    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
