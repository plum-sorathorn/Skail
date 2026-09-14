from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_adaptive_plan_is_the_active_tracker_and_adr_is_accepted() -> None:
    adr = _read("docs/decisions/0006-adaptive-execution-and-release-boundaries.md")
    old_adr = _read("docs/decisions/0001-rudder-native-multi-agent-harness.md")
    plan = _read("tasks/plan.md")
    todo = _read("tasks/todo.md")
    remediation = _read("tasks/rudder-v0.1.0-release-remediation.md")

    assert "Status: Accepted" in adr
    assert "ADR 0006 supersedes decision 3" in old_adr
    for tracker in (plan, todo, remediation):
        assert "rudder-adaptive-orchestration-and-release-plan.md" in tracker
    assert "Status: Historical" in plan
    assert "Status: Historical" in todo
    assert "Historical audit record" in remediation
    assert "Authoritative remediation phases" not in remediation


def test_release_contract_separates_engineering_and_external_authority() -> None:
    adr = _read("docs/decisions/0006-adaptive-execution-and-release-boundaries.md")
    spec = _read("docs/rudder/SPEC.md")
    remediation = _read("tasks/rudder-v0.1.0-release-remediation.md")

    assert "Engineering-ready v0.1.0" in adr
    assert "Economic qualification" in adr
    assert "A release tag requires separate explicit" in adr
    assert "authorization and exact-commit platform evidence" in adr
    assert "within five percentage points" not in spec
    assert "A tag never authorizes a remote rename" in adr
    assert "Creating a tag never authorizes" in remediation


def test_active_guide_uses_the_renamed_rudder_workspace() -> None:
    guide = _read("tasks/rudder-adaptive-orchestration-and-release-plan.md")

    assert "C:\\Users\\plum\\Documents\\Works\\Rudder" in guide
    assert "C:\\Users\\plum\\Documents\\Works\\AutoConduck" not in guide


def test_readme_clones_the_rudder_branch_into_a_rudder_directory() -> None:
    readme = _read("README.md")

    assert "git clone https://github.com/plum-sorathorn/Rudder.git -b rudder" in readme
    assert "cd Rudder" in readme
    assert "github.com/plum-sorathorn/AutoConduck" not in readme
    assert "cd AutoConduck" not in readme


def test_phase_20_documents_evidence_boundaries_and_feature_roadmap() -> None:
    readme = _read("README.md")
    documentation_index = _read("docs/rudder/README.md")
    cli = _read("docs/rudder/CLI.md")
    roadmap = _read("docs/rudder/FEATURE_PARITY_ROADMAP.md")

    assert "not a live-provider quality or savings claim" in readme
    assert "78.7%" not in readme
    assert "100% offline" not in readme
    assert "--jsonl" in cli
    assert "ADR 0006" in documentation_index
    for capability in (
        "Streaming",
        "Sessions and resume",
        "Approvals",
        "Steering",
        "Skills and memory",
        "Provider compatibility",
        "Inspection",
        "Context management",
    ):
        assert capability in roadmap
    for follow_on in (
        "Editor integration",
        "External tool and extension interoperability",
        "Background-agent interaction",
        "Multimodal workflows",
    ):
        assert follow_on in roadmap
