from __future__ import annotations

import json
import os
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

from skail.agents.profiles import builtin_profiles
from skail.cli.exit_codes import EXIT_FAILURE, EXIT_OK, EXIT_USAGE
from skail.cli.render import render_print_stderr, render_print_stdout
from skail.config.loader import ResolvedConfig, load_config
from skail.config.paths import (
    catalog_cache_path,
    default_checkpoints_path,
    default_journal_path,
    project_config_path,
    sessions_dir,
    user_config_path,
)
from skail.domain.sessions import SessionStatus
from skail.providers.credentials import (
    CredentialStore,
    CredentialStoreUnavailable,
    KeyringCredentialStore,
)
from skail.sessions.export import SessionExporter
from skail.sessions.journal import Journal
from skail.sessions.service import SessionService


def handle_config(
    args: Namespace,
    workspace: Path,
    *,
    project_trusted: bool = False,
    resolved_config: ResolvedConfig | None = None,
) -> int:
    subaction = getattr(args, "config_action", "show") or "show"
    if subaction == "path":
        render_print_stdout(f"User config: {user_config_path()}")
        render_print_stdout(f"Project config: {project_config_path(workspace)}")
        render_print_stdout(f"Sessions dir: {sessions_dir()}")
        render_print_stdout(f"Journal: {default_journal_path()}")
        render_print_stdout(f"Checkpoints: {default_checkpoints_path()}")
        return EXIT_OK

    if subaction == "show":
        resolved = resolved_config or load_config(
            user_path=user_config_path(),
            project_path=project_config_path(workspace),
            project_trusted=project_trusted,
        )
        data = resolved.config.model_dump(mode="json")
        render_print_stdout(json.dumps(data, indent=2))
        return EXIT_OK

    render_print_stderr(f"unknown config action: {subaction}")
    return EXIT_USAGE


def handle_sessions(
    args: Namespace, session_service: SessionService, journal: Journal
) -> int:
    subaction = getattr(args, "sessions_action", "list") or "list"

    if subaction == "list":
        sessions = session_service.list_sessions()
        if not sessions:
            render_print_stdout("No stored sessions found.")
            return EXIT_OK
        render_print_stdout(f"{'SESSION ID':<38} {'STATUS':<12} {'UPDATED AT':<26} TITLE")
        render_print_stdout("-" * 90)
        for s in sessions:
            render_print_stdout(
                f"{s.session_id:<38} {s.status.value:<12} {s.updated_at.isoformat():<26} {s.title}"
            )
        return EXIT_OK

    session_id = getattr(args, "session_id", None)
    if not session_id:
        render_print_stderr(f"sessions {subaction} requires a session ID")
        return EXIT_USAGE

    if subaction == "show":
        try:
            snapshot = journal.get_session_snapshot(session_id)
        except KeyError:
            render_print_stderr(f"session not found: {session_id}")
            return EXIT_FAILURE
        render_print_stdout(f"Session: {snapshot.session_id} ({snapshot.status})")
        render_print_stdout(f"Title: {snapshot.title}")
        render_print_stdout(f"Runs: {len(snapshot.runs)}, Tasks: {len(snapshot.tasks)}")
        return EXIT_OK

    if subaction == "export":
        exporter = SessionExporter(journal=journal)
        try:
            exported = exporter.export(session_id)
        except KeyError:
            render_print_stderr(f"session not found: {session_id}")
            return EXIT_FAILURE
        out_path = getattr(args, "output", None)
        content = json.dumps(exported, indent=2, ensure_ascii=False)
        if out_path:
            Path(out_path).write_text(content, encoding="utf-8")
            render_print_stdout(f"Exported session {session_id} to {out_path}")
        else:
            render_print_stdout(content)
        return EXIT_OK

    if subaction == "archive":
        try:
            session_service.transition_session(session_id, SessionStatus.ARCHIVED)
            render_print_stdout(f"Session {session_id} archived.")
            return EXIT_OK
        except Exception as exc:
            render_print_stderr(f"failed to archive session {session_id}: {exc}")
            return EXIT_FAILURE

    if subaction == "resume":
        result = session_service.resume_session(session_id)
        if not result.ok:
            render_print_stderr(f"failed to resume session {session_id}: {result.recovery_error}")
            return EXIT_FAILURE
        render_print_stdout(f"Session {session_id} resumed into active state.")
        return EXIT_OK

    render_print_stderr(f"unknown sessions action: {subaction}")
    return EXIT_USAGE


def handle_auth(
    args: Namespace,
    *,
    resolved_config: ResolvedConfig | None = None,
    credential_store: CredentialStore | None = None,
) -> int:
    subaction = getattr(args, "auth_action", "status") or "status"
    references = {
        "llmgateway": "LLMGATEWAY_API_KEY",
        "devpass": "DEVPASS_TOKEN",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }
    if resolved_config is not None:
        for name, provider_config in resolved_config.config.providers.items():
            if provider_config.api_key_env:
                references[name] = provider_config.api_key_env
    store = credential_store or KeyringCredentialStore()
    keys: dict[str, bool] = {}
    for provider_name, reference in references.items():
        available = bool(os.environ.get(reference))
        if not available:
            try:
                available = bool(store.get(provider_name, reference))
            except CredentialStoreUnavailable:
                available = False
        keys[reference] = keys.get(reference, False) or available
    if subaction == "check":
        configured_references = [
            reference for reference, available in keys.items() if available
        ]
        if not configured_references:
            render_print_stdout(
                "No provider credential found in the environment or OS credential store."
            )
        else:
            render_print_stdout(
                f"Credentials detected for: {', '.join(configured_references)}"
            )
        return EXIT_OK

    render_print_stdout("Skail Provider Credentials Status:")
    for name, configured in keys.items():
        status = "CONFIGURED" if configured else "NOT CONFIGURED"
        render_print_stdout(f"  {name:<22}: {status}")
    return EXIT_OK


def handle_models(
    args: Namespace,
    *,
    resolved_config: ResolvedConfig | None = None,
) -> int:
    subaction = getattr(args, "models_action", "list") or "list"
    if subaction == "list":
        profiles = builtin_profiles()
        render_print_stdout("Built-in Agent Profiles:")
        for p in profiles.values():
            render_print_stdout(
                f"  {p.name:<18} [floor: {p.role_floor:.2f}] {p.description}"
            )
        render_print_stdout("\nConfigured Providers and Models:")
        configured_models = [
            f"{provider}:{model}"
            for provider, provider_config in (
                resolved_config.config.providers.items() if resolved_config else ()
            )
            for model in provider_config.models
        ]
        if configured_models:
            for model in configured_models:
                render_print_stdout(f"  {model}")
        else:
            render_print_stdout("  No models selected. Open the model picker to choose models.")
        from skail.providers.catalog_sources import load_catalog_snapshot

        snapshot = load_catalog_snapshot(
            catalog_cache_path(),
            provider="llmgateway",
            endpoint="https://api.llmgateway.io/v1/models",
        )
        if snapshot is None:
            render_print_stdout("\nLLMGateway catalog: unavailable")
        else:
            priced = sum(
                entry.fields.get("input_usd_per_million") is not None
                and entry.fields.get("output_usd_per_million") is not None
                for entry in snapshot.entries
            )
            age = datetime.now(UTC) - snapshot.retrieved_at
            selected = (
                resolved_config.config.routing.lead_model
                if resolved_config is not None
                else "auto"
            )
            render_print_stdout(
                f"\nLLMGateway catalog: {len(snapshot.entries)} models; "
                f"{priced} with prompt/completion pricing; age {age}; "
                f"selected {selected}"
            )
            for entry in snapshot.entries:
                input_price = entry.fields.get("input_usd_per_million", "unavailable")
                output_price = entry.fields.get("output_usd_per_million", "unavailable")
                render_print_stdout(
                    f"  llmgateway:{entry.model}  in ${input_price}/M  out ${output_price}/M"
                )
        return EXIT_OK

    name = getattr(args, "model_name", None)
    if name:
        profiles = builtin_profiles()
        if name in profiles:
            p = profiles[name]
            render_print_stdout(f"Profile: {p.name}")
            render_print_stdout(f"Description: {p.description}")
            render_print_stdout(f"Capability floor: {p.role_floor}")
            render_print_stdout(f"Allowed tools: {', '.join(p.tools)}")
            return EXIT_OK
        from skail.providers.catalog_sources import load_catalog_snapshot

        provider, separator, model = name.partition(":")
        if separator:
            snapshot = load_catalog_snapshot(
                catalog_cache_path(provider),
                provider=provider,
                endpoint=(
                    "https://api.llmgateway.io/v1/models"
                    if provider == "llmgateway"
                    else None
                ),
            )
            if snapshot is not None:
                for entry in snapshot.entries:
                    if entry.model == model:
                        render_print_stdout(f"Model: {name}")
                        render_print_stdout(f"Source: {entry.source.value}")
                        render_print_stdout(f"Trusted facts: {entry.trusted}")
                        render_print_stdout(f"As of: {entry.as_of.isoformat()}")
                        render_print_stdout(f"Provenance: {entry.provenance}")
                        render_print_stdout(json.dumps(entry.fields, default=str, sort_keys=True))
                        return EXIT_OK
        render_print_stdout(f"Model/Profile: {name}")
        return EXIT_OK

    return EXIT_USAGE
