from pathlib import Path

from skail.agents.context import ContextAssembler, ContextComponent
from skail.agents.instructions import load_root_instructions
from skail.domain.events import SecretRedactor
from skail.domain.security import ProjectTrustLevel


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


def test_root_instructions_are_ordered_bounded_redacted_and_revision_pinned(
    tmp_path: Path,
) -> None:
    global_root = tmp_path / "global"
    workspace = tmp_path / "workspace"
    global_root.mkdir()
    workspace.mkdir()
    (global_root / "AGENTS.md").write_text("global canary", encoding="utf-8")
    (workspace / "AGENTS.md").write_text("workspace rules", encoding="utf-8")
    redactor = SecretRedactor(["canary"])

    components = load_root_instructions(
        workspace=workspace,
        trust=ProjectTrustLevel.TRUSTED,
        global_root=global_root,
        redactor=redactor,
    )

    assert [item.source for item in components] == ["builtin", "global", "workspace"]
    assert components[1].content == "global [REDACTED]"
    assert components[2].content == "workspace rules"
    assert all(item.revision for item in components)
    assert components[1].source == "global"


def test_untrusted_workspace_instructions_are_visible_but_not_active(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("must be ignored", encoding="utf-8")

    component = load_root_instructions(
        workspace=workspace,
        trust=ProjectTrustLevel.UNTRUSTED,
        global_root=tmp_path / "global",
    )[-1]

    assert component.disposition == "omitted:workspace_untrusted"
    assert component.content == ""
    assert component.rationale == "workspace_untrusted"


def test_oversized_workspace_instructions_are_omitted_with_reason(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("x" * 20, encoding="utf-8")

    component = load_root_instructions(
        workspace=workspace,
        trust=ProjectTrustLevel.TRUSTED,
        max_bytes=10,
    )[-1]

    assert component.disposition == "omitted:size_limit"
    assert component.content == ""


def test_base_instruction_components_are_injected_once_per_packet() -> None:
    root = ContextComponent(
        "instructions:global", "root-revision", "global rule", "root", 3, source="global"
    )
    packet = ContextAssembler(base_references=(root,)).assemble(
        task_id="task", objective="do work", references=(root,)
    )

    assert [item.label for item in packet.components].count("instructions:global") == 1
