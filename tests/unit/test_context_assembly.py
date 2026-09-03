from rudder.agents.context import ContextAssembler, ContextComponent
from rudder.domain.events import SecretRedactor


def test_packet_is_bounded_and_does_not_include_unselected_history() -> None:
    packet = ContextAssembler(max_tokens=10).assemble(
        task_id="task",
        objective="do work",
        constraints=("do not write",),
        references=(ContextComponent("lead-transcript", "1", "x" * 100, "history", 25),),
    )
    assert packet.version == 1
    assert {item.label for item in packet.components} >= {
        "objective", "constraints", "task-state"
    }
    assert "lead-transcript:token_budget" in packet.omissions


def test_packet_digest_covers_content_and_registered_secrets_are_scrubbed() -> None:
    assembler = ContextAssembler(redactor=SecretRedactor(["canary-secret"]))
    first = assembler.assemble(task_id="task", objective="one canary-secret")
    second = assembler.assemble(task_id="task", objective="two canary-secret")

    assert first.revision != second.revision
    assert "canary-secret" not in repr(first)
