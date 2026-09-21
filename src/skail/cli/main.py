from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from skail import __version__
from skail.cli.exit_codes import (
    EXIT_BLOCKED,
    EXIT_CANCELLED,
    EXIT_FAILURE,
    EXIT_OK,
    EXIT_USAGE,
)
from skail.cli.render import (
    render_jsonl_event,
    render_print_stderr,
    render_print_stdout,
)
from skail.config.loader import ConfigValidationError, load_config
from skail.config.paths import (
    default_checkpoints_path,
    default_journal_path,
    project_config_path,
    sessions_dir,
    user_config_path,
    user_data_dir,
)
from skail.config.trust import ProjectTrustStore
from skail.domain.ids import SessionId, new_invocation_id, new_run_id
from skail.domain.routing import RoutingMode
from skail.domain.security import ProjectTrustLevel, identify_workspace
from skail.domain.sessions import SessionRecord
from skail.runtime.interrupts import QuestionStore
from skail.runtime.redaction import RedactionRegistry
from skail.sessions.service import SessionService
from skail.tools.approvals import ApprovalStore

if TYPE_CHECKING:
    from skail.config.models import SkailConfig
    from skail.providers.base import ProviderAdapter
    from skail.providers.catalog import ModelCatalog
    from skail.providers.catalog_sources import CatalogEntry
    from skail.providers.models import ModelProfile
    from skail.routing.assignment import RoutingSnapshot
    from skail.routing.selector import RouteCandidate
    from skail.sessions.checkpoints import CheckpointStore
    from skail.sessions.journal import Journal

REMOVED_ALIASES = frozenset(
    {"proxy", "serve", "oma", "daemon", "plugin", "slm", "--proxy", "--port", "--host"}
)


@dataclass(frozen=True)
class RuntimeModelSet:
    models: dict[str, Any]
    lead_model: str
    child_model: str
    providers: dict[str, ProviderAdapter]
    catalog: ModelCatalog | None = None
    config: SkailConfig | None = None
    redaction: RedactionRegistry | None = None
    candidates: tuple[RouteCandidate, ...] = ()
    selection_required: bool = False
    catalog_degraded: bool = False

    def __iter__(self) -> Iterator[Any]:
        yield self.models
        yield self.lead_model
        yield self.child_model

    def routing_snapshot(self) -> RoutingSnapshot:
        from skail.routing.assignment import RoutingSnapshot, config_revision
        assert self.catalog is not None
        assert self.config is not None
        return RoutingSnapshot(
            catalog_revision=self.catalog.revision,
            config_revision=config_revision(self.config.model_dump(mode="json")),
            health_revision="bootstrap",
            candidates=self.candidates,
        )


def _route_candidate(
    profile: ModelProfile,
    *,
    hard_budget: bool,
    enabled: bool | None = None,
) -> RouteCandidate:
    from skail.routing.estimates import AttemptEstimateInput, estimate_attempt_cost
    from skail.routing.selector import RouteCandidate
    estimate = estimate_attempt_cost(
        AttemptEstimateInput(
            context_tokens=min(profile.context_tokens or 4096, 4096),
            output_tokens=min(profile.max_output_tokens or 2048, 2048),
            expected_calls=2,
            input_usd_per_million=profile.input_usd_per_million,
            output_usd_per_million=profile.output_usd_per_million,
            cached_input_usd_per_million=profile.cached_input_usd_per_million,
        )
    )
    return RouteCandidate(
        profile=profile,
        estimated_cost_usd=estimate.cost_usd,
        estimate_assumptions=estimate.assumptions,
        configured=True,
        healthy=True,
        enabled=(
            (not hard_budget or estimate.cost_usd is not None)
            if enabled is None
            else enabled
        ),
    )


def _run_discovery(
    adapter: ProviderAdapter,
    *,
    timeout_seconds: float = 15.0,
) -> tuple[CatalogEntry, ...]:
    """Run an async provider discovery call from both sync and async bootstrap paths."""
    async def discover() -> tuple[CatalogEntry, ...]:
        return await asyncio.wait_for(
            adapter.discover_models(), timeout=timeout_seconds
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(discover())
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(discover())).result()


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
    parser.add_argument("--version", action="version", version=f"skail {__version__}")

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
        prog="skail",
        description="Skail - a native budget-aware multi-agent coding harness.",
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
        prog="skail",
        description="Skail - a native budget-aware multi-agent coding harness.",
    )
    _add_common_options(parser)
    parser.add_argument("prompt", nargs="*", help="prompt or task description for Skail")
    return parser


def _build_storage(
    *,
    no_session: bool,
    redaction: RedactionRegistry,
    ephemeral_dir: Path | None = None,
) -> tuple[Journal, CheckpointStore, Path]:
    from skail.sessions.checkpoints import CheckpointStore
    from skail.sessions.journal import Journal
    if no_session:
        if ephemeral_dir is None:
            import tempfile

            ephemeral_dir = Path(tempfile.mkdtemp(prefix="skail-ephemeral-"))
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


def _apply_run_config(args: argparse.Namespace, config: SkailConfig) -> None:
    args.provider_configs = config.providers
    args.effective_config = config
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

    # 1. Reject removed Skail aliases and options immediately
    for token in raw_args:
        if token.lower() in REMOVED_ALIASES:
            render_print_stderr(
                f"Error: '{token}' is removed and not supported in Skail. "
                "Skail launches the harness directly without proxies or daemons."
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

    # Imported lazily so --help/--version avoid loading the command dispatch.
    from skail.cli.commands import (
        handle_auth,
        handle_config,
        handle_models,
        handle_sessions,
        handle_smoke,
    )

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
    # 4. Handle stateless subcommands before journal/checkpoint storage init
    if args.subcommand == "smoke":
        return handle_smoke(args)
    if args.subcommand == "config":
        return handle_config(
            args,
            workspace,
            project_trusted=trusted,
            resolved_config=resolved_config,
        )
    if args.subcommand == "auth":
        return handle_auth(args, resolved_config=resolved_config)
    if args.subcommand == "models":
        return handle_models(args, resolved_config=resolved_config)

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

    # 7. Classify interactive-TTY vs headless BEFORE runtime construction.
    headless_requested = bool(args.print_mode or args.json_mode)
    interactive_tty = (
        not headless_requested and sys.stdin.isatty() and sys.stdout.isatty()
    )
    if not prompt_text and not args.continue_session and args.resume_session is None:
        if args.print_mode or args.json_mode:
            render_print_stderr("Error: prompt required in non-interactive print or JSONL mode.")
            return EXIT_USAGE
        if not headless_requested and not interactive_tty:
            from skail.tui.onboarding import NON_TTY_USAGE_ERROR

            render_print_stderr(NON_TTY_USAGE_ERROR)
            return EXIT_FAILURE

    approvals = ApprovalStore(workspace / ".skail" / "approvals.sqlite")
    question_store = QuestionStore(workspace / ".skail" / "questions.sqlite")

    # 8. Interactive TUI execution: mount shell first, build runtime lazily.
    if interactive_tty:
        from skail.tui.app import SkailApp

        def _runtime_factory() -> RuntimeModelSet:
            return _build_runtime_models(args, redaction, prompt_text)

        bootstrap = {
            "workspace": str(workspace),
            "session_id": session_record.session_id,
            "fake_provider": bool(getattr(args, "fake_provider", False)),
            "initial_prompt": prompt_text or None,
            "max_agents": args.max_agents,
            "delegation": args.delegation,
            "budget": args.budget,
            "budget_warning_percent": args.budget_warning_percent,
            "workspace_mode": args.workspace_mode,
            "project_trusted": trusted,
            "resume_session": args.resume_session,
            "credential_envs": tuple(
                provider.api_key_env
                for provider in resolved_config.config.providers.values()
                if provider.api_key_env
            ),
        }
        app = SkailApp(
            session_service=session_service,
            session_id=SessionId(session_record.session_id),
            approval_store=approvals,
            question_store=question_store,
            initial_prompt=prompt_text or None,
            max_children=args.max_agents,
            delegation=args.delegation,
            runtime_factory=_runtime_factory,
            bootstrap=bootstrap,
            journal=journal,
            checkpoints=checkpoints,
            redaction=redaction,
            profile_models=profile_models,
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
            project_trusted=trusted,
        )
    )


def _build_runtime_models(
    args: argparse.Namespace,
    redaction: RedactionRegistry,
    prompt: str = "",
) -> RuntimeModelSet:
    from skail.config.models import SkailConfig
    from skail.providers.catalog import ModelCatalog
    from skail.providers.catalog_sources import (
        load_catalog_snapshot,
        save_catalog_cache,
    )
    from skail.providers.credentials import EnvironmentCredentialResolver
    from skail.providers.errors import ProviderConfigurationError
    from skail.providers.fake import DeterministicFakeChatModel
    from skail.providers.models import CapabilityVector, ModelProfile, ProviderSupportLevel

    config = getattr(args, "effective_config", SkailConfig())
    catalog = ModelCatalog.from_entries(
        config.catalog.entries,
        now=datetime.now(UTC),
        price_max_age=timedelta(days=30),
    )
    lead_model_name = args.lead_model or args.default_model or "auto"
    child_model_name = args.default_model or "implementer-model"

    if getattr(args, "fake_provider", False):
        resp = (
            f"Skail completed task: {prompt}"
            if prompt
            else "Skail completed task."
        )
        lead_fake = DeterministicFakeChatModel(
            model_name=lead_model_name,
            response_text=resp,
        )
        lead_key = lead_model_name if ":" in lead_model_name else f"fake:{lead_model_name}"
        child_key = child_model_name if ":" in child_model_name else f"fake:{child_model_name}"
        models = {lead_key: lead_fake, child_key: lead_fake}
        fake_profiles = tuple(
            ModelProfile(
                provider="fake",
                model=key.split(":", 1)[1],
                support_level=ProviderSupportLevel.NATIVE,
                input_usd_per_million=Decimal("1"),
                output_usd_per_million=Decimal("2"),
                context_tokens=128_000,
                max_output_tokens=8_192,
                supports_tools=True,
                supports_structured_output=True,
                capability=CapabilityVector(
                    coding=0.9,
                    reasoning=0.9,
                    tool_reliability=0.9,
                    latency=0.9,
                ),
                auto_eligible=True,
            )
            for key in models
        )
        from skail.providers.fake import FakeProviderAdapter

        return RuntimeModelSet(
            models,
            lead_key,
            child_key,
            {"fake": FakeProviderAdapter(lead_fake)},
            catalog=catalog,
            config=config,
            redaction=redaction,
            candidates=tuple(
                _route_candidate(profile, hard_budget=args.budget is not None)
                for profile in fake_profiles
            ),
        )

    cred_resolver = EnvironmentCredentialResolver(redaction)
    provider_configs = getattr(args, "provider_configs", {})
    candidate_providers = (
        tuple(provider_configs)
        if provider_configs
        else ("llmgateway", "openai", "anthropic")
    )
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

    if selected_provider in {"llmgateway", "devpass"}:
        from skail.config.models import ProviderConfig
        from skail.config.paths import user_data_dir
        from skail.providers.llmgateway import LLMGATEWAY_BASE_URL, LLMGatewayAdapter

        discovery_config = selected_config or ProviderConfig(
            type="openai-compatible",
            base_url=LLMGATEWAY_BASE_URL,
            models=("__catalog_discovery__",),
        )
        if not discovery_config.models:
            discovery_config = discovery_config.model_copy(
                update={"models": ("__catalog_discovery__",)}
            )
        discovery_adapter: ProviderAdapter
        if selected_provider == "devpass":
            from skail.providers.devpass import DevPassAdapter

            discovery_adapter = DevPassAdapter(
                discovery_config,
                api_key=resolved_cred.reveal(),
            )
        else:
            discovery_adapter = LLMGatewayAdapter(
                discovery_config,
                api_key=resolved_cred.reveal(),
            )
        configured_cache_path = getattr(args, "catalog_cache_path", None)
        cache_path = (
            Path(configured_cache_path)
            if configured_cache_path is not None
            else user_data_dir() / "catalog" / f"{selected_provider}.json"
        )
        catalog_endpoint = f"{LLMGATEWAY_BASE_URL}/models"
        catalog_query = {"exclude_deprecated": True}
        degraded_catalog = False
        try:
            discovered_entries = _run_discovery(discovery_adapter)
        except Exception as exc:
            classified = discovery_adapter.classify_error(exc)
            from skail.providers.errors import ProviderErrorKind

            if classified.kind not in {ProviderErrorKind.TRANSIENT, ProviderErrorKind.RATE_LIMIT}:
                raise ProviderConfigurationError(
                    selected_provider,
                    classified.summary,
                ) from exc
            cached_snapshot = load_catalog_snapshot(
                cache_path,
                provider=selected_provider,
                endpoint=catalog_endpoint,
            )
            if cached_snapshot is None:
                raise ProviderConfigurationError(
                    selected_provider,
                    "model discovery failed and no valid catalog cache is available",
                ) from exc
            discovered_entries = cached_snapshot.entries
            degraded_catalog = True
        else:
            if not discovered_entries and not config.catalog.entries:
                raise ProviderConfigurationError(
                    "llmgateway",
                    "the authenticated catalog contains no accessible models",
                )
            save_catalog_cache(
                cache_path,
                discovered_entries,
                provider=selected_provider,
                endpoint=catalog_endpoint,
                query=catalog_query,
            )
        catalog = ModelCatalog.from_entries(
            (*config.catalog.entries, *discovered_entries),
            now=datetime.now(UTC),
            price_max_age=timedelta(days=30),
        )

    if ":" not in lead_model_name:
        configured_models = set(
            provider_configs[selected_provider].models
            if selected_provider in provider_configs
            else ()
        )
        has_configured_overlap = any(
            profile.model in configured_models
            for (provider, _), profile in catalog.profiles.items()
            if provider == selected_provider
        )
        eligible = [
            profile
            for (provider, _), profile in catalog.profiles.items()
            if provider == selected_provider
            and (
                not has_configured_overlap or profile.model in configured_models
            )
            and catalog.is_auto_eligible(profile, hard_budget=args.budget is not None)
        ]
        if not eligible and lead_model_name != "auto":
            raise ProviderConfigurationError(
                selected_provider,
                "no discovered model has trusted capability and pricing evidence "
                "for automatic routing",
            )
        elif eligible:
            lead_model_name = f"{selected_provider}:{eligible[0].model}"
    child_model_name = lead_model_name

    models_dict: dict[str, Any] = {}
    provider_adapters: dict[str, ProviderAdapter] = {}
    if selected_provider in {"llmgateway", "devpass"}:
        from skail.config.models import ProviderConfig
        from skail.providers.base import ModelOptions
        from skail.providers.llmgateway import LLMGATEWAY_BASE_URL, LLMGatewayAdapter

        catalog_profiles = tuple(
            profile
            for (provider, _), profile in catalog.profiles.items()
            if provider == selected_provider
        )
        allowed_models = tuple(profile.model for profile in catalog_profiles)
        if not allowed_models:
            raise ProviderConfigurationError(
                selected_provider,
                "no accessible models are present in the provider catalog",
            )
        actual_model = (
            lead_model_name.split(":", 1)[-1]
            if lead_model_name != "auto"
            else catalog_profiles[0].model
        )
        cfg = selected_config or ProviderConfig(
            type="openai-compatible",
            base_url=LLMGATEWAY_BASE_URL,
            models=allowed_models,
        )
        cfg = cfg.model_copy(update={"models": allowed_models})
        adapter: ProviderAdapter
        if selected_provider == "devpass":
            from skail.providers.devpass import DevPassAdapter

            adapter = DevPassAdapter(cfg, api_key=resolved_cred.reveal())
        else:
            adapter = LLMGatewayAdapter(cfg, api_key=resolved_cred.reveal())
        provider_adapters[selected_provider] = adapter
        if not any(profile.model == actual_model for profile in catalog_profiles):
            raise ProviderConfigurationError(
                selected_provider,
                "requested model is absent from the accessible provider catalog",
            )
        for profile in catalog_profiles:
            models_dict[f"{selected_provider}:{profile.model}"] = adapter.create_model(
                profile, ModelOptions()
            )
        profile = next(profile for profile in catalog_profiles if profile.model == actual_model)
        candidates = tuple(
            _route_candidate(
                item,
                hard_budget=args.budget is not None,
                enabled=(
                    catalog.price_is_current(item)
                    if args.budget is not None
                    else None
                ),
            )
            for item in catalog_profiles
        )
    else:
        from skail.providers.langchain import LangChainModelFactory, LangChainUsageAdapter
        from skail.providers.registry import LangChainProviderRegistry, ProviderRegistration

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
        provider_adapters[selected_provider] = LangChainUsageAdapter(selected_provider)
        try:
            profile = catalog.profile(selected_provider, actual_model)
        except KeyError as exc:
            raise ProviderConfigurationError(
                selected_provider, "model is absent from the configured catalog"
            ) from exc
        models_dict[f"{selected_provider}:{actual_model}"] = chat_model

    if args.default_model is None and lead_model_name != "auto":
        child_model_name = f"{selected_provider}:{actual_model}"
        lead_model_name = f"{selected_provider}:{actual_model}"

    selection_required = lead_model_name == "auto" and not any(
        candidate.profile.auto_eligible for candidate in candidates
    )

    return RuntimeModelSet(
        models_dict,
        lead_model_name,
        child_model_name,
        provider_adapters,
        catalog=catalog,
        config=config,
        redaction=redaction,
        candidates=(
            candidates
            if selected_provider in {"llmgateway", "devpass"}
            else (
                _route_candidate(
                    profile,
                    hard_budget=args.budget is not None,
                    enabled=(
                        catalog.price_is_current(profile)
                        if args.budget is not None
                        else None
                    ),
                ),
            )
        ),
        selection_required=selection_required,
        catalog_degraded=degraded_catalog,
    )


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
    project_trusted: bool = False,
) -> int:
    from skail.agents.lead import LeadControls
    from skail.providers.errors import ProviderConfigurationError
    from skail.runtime.run_controller import RunController

    try:
        runtime_models = _build_runtime_models(
            args, redaction, prompt
        )
        if runtime_models.selection_required:
            render_print_stderr(
                "Model selection required: pass --model PROVIDER:MODEL "
                "or run interactive skail and choose a discovered model."
            )
            return EXIT_FAILURE
        assert runtime_models.catalog is not None
        assert runtime_models.config is not None
        has_bootstrap_candidates = bool(runtime_models.candidates)
        models, lead_model_name, child_model_name = runtime_models
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
    invocation_id = new_invocation_id()
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
        providers=runtime_models.providers,
        candidates_fn=(runtime_models.routing_snapshot if has_bootstrap_candidates else None),
        catalog_revision=(
            runtime_models.catalog.revision if has_bootstrap_candidates else "catalog-v1"
        ),
        config_snapshot=(
            runtime_models.config.model_dump(mode="json")
            if has_bootstrap_candidates
            else None
        ),
        event_observer=render_jsonl_event if args.json_mode else None,
        invocation_id=invocation_id,
        project_trusted=project_trusted,
        workspace_mode=getattr(args, "workspace_mode", "shared"),
    )

    try:
        if getattr(args, "resume_session", None) is not None and controller.restore_interrupted():
            if not prompt:
                render_print_stderr("Execution remains blocked: a resume answer is required.")
                return EXIT_BLOCKED
            result = await controller.resume_interrupted(prompt)
        else:
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
