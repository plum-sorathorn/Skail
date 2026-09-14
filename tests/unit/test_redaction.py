from __future__ import annotations

import io
import logging
from datetime import UTC, datetime

from skail.agents.context import ContextAssembler
from skail.domain.events import DiagnosticPayload, EventEnvelope
from skail.domain.ids import EventId, RunId, SessionId
from skail.runtime.redaction import RedactingLogFilter, RedactionRegistry


def test_registered_secret_is_removed_from_nested_data_and_event_export() -> None:
    canary = "canary-secret-everywhere"
    registry = RedactionRegistry()
    registry.register(canary)
    nested = {"message": f"failed with {canary}", "items": [canary]}
    event = EventEnvelope(
        event_id=EventId("11111111-1111-4111-8111-111111111111"),
        session_id=SessionId("22222222-2222-4222-8222-222222222222"),
        run_id=RunId("33333333-3333-4333-8333-333333333333"),
        sequence=1,
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        type="diagnostic.error",
        payload=DiagnosticPayload(code="provider.error", summary=f"error {canary}"),
    )

    assert canary not in str(registry.scrub(nested))
    assert canary not in event.to_json(registry.redactor())


def test_redaction_covers_logs_tool_output_exception_chains_and_exports() -> None:
    canary = "registered-canary"
    registry = RedactionRegistry()
    registry.register(canary)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactingLogFilter(registry))
    logger = logging.getLogger("skail-redaction-test")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    try:
        try:
            raise ValueError(f"inner {canary}")
        except ValueError as inner:
            raise RuntimeError(f"outer {canary}") from inner
    except RuntimeError as error:
        logger.exception("provider failed with %s", canary)
        chain = registry.scrub_exception(error)

    tool_output = registry.scrub_tool_output(
        {f"header-{canary}": {canary, "safe"}}
    )
    exported = registry.scrub_export({"transcript": f"message {canary}"})

    assert canary not in stream.getvalue()
    assert canary not in repr(chain)
    assert canary not in repr(tool_output)
    assert canary not in repr(exported)


def test_live_registry_redacts_values_registered_after_consumer_capture() -> None:
    registry = RedactionRegistry()
    consumer = ContextAssembler(redactor=registry)
    late_secret = "late-provider-credential"

    registry.register(late_secret)
    packet = consumer.assemble(task_id="task-1", objective=f"use {late_secret}")

    assert late_secret not in repr(packet)
