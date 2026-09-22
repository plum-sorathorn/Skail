from __future__ import annotations

from pathlib import Path

import pytest

from skail.agents.context import ContextAssembler, ContextComponent
from skail.agents.profile_loader import ProfileLoader
from skail.domain.events import SecretRedactor
from skail.domain.security import PermissionSet, ProjectTrustLevel
from skail.sessions.export import export_session
from skail.sessions.journal import Journal


def test_untrusted_project_profile_and_permissions_ceiling(tmp_path: Path) -> None:
    project_agent = tmp_path / ".skail" / "agents" / "rogue"
    project_agent.mkdir(parents=True)
    (project_agent / "AGENTS.md").write_text(
        "---\n"
        "description: Rogue agent requesting network and execution\n"
        "role: implementer\n"
        "tools: read_file,write_file,execute\n"
        "permissions: read,write,execute,network\n"
        "---\n"
        "Rogue prompt instructions",
        encoding="utf-8",
    )

    loader = ProfileLoader(project_root=tmp_path, user_root=tmp_path / "user", builtins={})

    # 1. Untrusted workspace -> profile must NOT load
    full_ceiling = PermissionSet(read=True, write=True, execute=True, network=True)
    assert loader.load("rogue", trust=ProjectTrustLevel.UNTRUSTED, ceiling=full_ceiling) is None

    # 2. When trusted, requesting permissions exceeding ceiling raises ValueError
    read_only_ceiling = PermissionSet(read=True, write=False, execute=False, network=False)
    with pytest.raises(ValueError, match="exceeds permission ceiling"):
        loader.load("rogue", trust=ProjectTrustLevel.TRUSTED, ceiling=read_only_ceiling)


def test_secret_redactor_scrubs_all_credentials_from_context() -> None:
    secrets = [
        "Bearer sk-ant-api03-abcdef1234567890abcdef1234567890",
        "sk-proj-1234567890abcdef1234567890abcdef",
        "SuperSecretPassword123!",
        (
            "-----BEGIN OPENSSH PRIVATE KEY-----\n"
            "b3BlbnNzaC1rZXktdjEAAAA\n"
            "-----END OPENSSH PRIVATE KEY-----"
        ),
    ]
    redactor = SecretRedactor(secrets=secrets)
    assembler = ContextAssembler(redactor=redactor)

    for secret in secrets:
        scrubbed = redactor.scrub(f"Config containing {secret}")
        assert secret not in str(scrubbed)
        assert "[REDACTED]" in str(scrubbed)

        # Context assembler scrub check
        packet = assembler.assemble(
            task_id="test-task",
            objective=f"Objective with {secret}",
            constraints=(f"Constraint with {secret}",),
            state="running",
            references=(
                ContextComponent(
                    label="ref",
                    revision="rev1",
                    content=f"Payload {secret}",
                    rationale="rationale",
                    estimated_tokens=50,
                ),
            ),
        )

        for comp in packet.components:
            assert secret not in comp.content
        assert any("[REDACTED]" in comp.content for comp in packet.components)


def test_session_export_scrubs_all_secrets(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.sqlite")
    journal.migrate()

    import uuid
    session_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    secret_token = "secret_token_value_to_scrub"
    from datetime import UTC, datetime
    from decimal import Decimal
    journal.create_session(session_id=session_id, title="Secret Test", created_at=datetime.now(UTC))
    journal.create_run(
        run_id=run_id,
        session_id=session_id,
        status="running",
        budget_limit_usd=Decimal("5.00"),
        created_at=datetime.now(UTC),
    )
    journal.create_task(
        task_id="task-secret",
        run_id=run_id,
        description=f"Task containing secret: {secret_token}",
        status="succeeded",
        idempotency_key="key-sec",
        created_at=datetime.now(UTC),
    )

    from skail.domain.events import EventEnvelope, LifecyclePayload
    env = EventEnvelope(
        event_id=event_id,
        session_id=session_id,
        run_id=run_id,
        sequence=1,
        occurred_at=datetime.now(UTC),
        type="session.completed",
        payload=LifecyclePayload(status="completed"),
    )
    journal.append_event(event=env)

    redactor = SecretRedactor(secrets=[secret_token])
    out_file = tmp_path / "export.json"
    export_session(session_id, journal, out_file, redactor=redactor)

    exported_json = out_file.read_text(encoding="utf-8")
    assert secret_token not in exported_json
    assert "[REDACTED]" in exported_json
