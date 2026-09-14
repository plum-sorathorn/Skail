from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_adaptive_plan_is_the_active_tracker_and_adr_is_accepted() -> None:
    adr = _read("docs/decisions/0006-adaptive-execution-and-release-boundaries.md")
    old_adr = _read("docs/decisions/0001-skail-native-multi-agent-harness.md")
    plan = _read("tasks/plan.md")
    todo = _read("tasks/todo.md")
    remediation = _read("tasks/skail-v0.1.0-release-remediation.md")

    assert "Status: Accepted" in adr
    assert "ADR 0006 supersedes decision 3" in old_adr
    for tracker in (plan, todo, remediation):
        assert "skail-adaptive-orchestration-and-release-plan.md" in tracker
    assert "Status: Historical" in plan
    assert "Status: Historical" in todo
    assert "Historical audit record" in remediation
    assert "Authoritative remediation phases" not in remediation


def test_release_contract_separates_engineering_and_external_authority() -> None:
    adr = _read("docs/decisions/0006-adaptive-execution-and-release-boundaries.md")
    spec = _read("docs/skail/SPEC.md")
    remediation = _read("tasks/skail-v0.1.0-release-remediation.md")

    assert "Engineering-ready v0.1.0" in adr
    assert "Economic qualification" in adr
    assert "A release tag requires separate explicit" in adr
    assert "authorization and exact-commit platform evidence" in adr
    assert "within five percentage points" not in spec
    assert "A tag never authorizes a remote rename" in adr
    assert "Creating a tag never authorizes" in remediation


def test_active_guide_uses_the_renamed_skail_workspace() -> None:
    guide = _read("tasks/skail-adaptive-orchestration-and-release-plan.md")

    assert "C:\\Users\\plum\\Documents\\Works\\Skail" in guide
    assert "C:\\Users\\plum\\Documents\\Works\\" + ("R" + "udder") not in guide
    assert "Final repository URL: `https://github.com/plum-sorathorn/Skail`" in guide
    assert "Final workspace: `C:\\Users\\plum\\Documents\\Works\\Skail`" in guide


def test_readme_clones_the_skail_branch_into_a_skail_directory() -> None:
    readme = _read("README.md")

    assert "git clone https://github.com/plum-sorathorn/Skail -b skail" in readme
    assert "cd Skail" in readme
    assert "github.com/plum-sorathorn/" + ("R" + "udder") not in readme
    assert "cd " + ("R" + "udder") not in readme


def test_phase_20_documents_evidence_boundaries_and_feature_roadmap() -> None:
    readme = _read("README.md")
    documentation_index = _read("docs/skail/README.md")
    cli = _read("docs/skail/CLI.md")
    roadmap = _read("docs/skail/FEATURE_PARITY_ROADMAP.md")

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


def test_renamed_contracts_distinguish_skail_from_the_archived_predecessor() -> None:
    documentation_index = _read("docs/skail/README.md")
    specification = _read("docs/skail/SPEC.md")
    migration = _read("docs/skail/MIGRATION.md")
    features = _read("docs/skail/FEATURES.md")

    assert "successor to Skail" not in documentation_index
    assert "Skail replaces Skail" not in specification
    assert "built wheel contains `skail` and no `skail` package" not in migration
    assert "dependency on `legacy` or `skail`" not in migration
    assert "| Archived feature | Skail decision |" in features
    for document in (documentation_index, specification, migration):
        assert "archived predecessor" in document


def test_phase_21_records_the_final_integrated_audit() -> None:
    audit = _read("docs/skail/PHASE_21_REVIEW.md")
    guide = _read("tasks/skail-adaptive-orchestration-and-release-plan.md")

    assert "Reviewed input: `b496d96f46f412223fe844b30ed74f7cdd53236a`" in audit
    for remediation in ("Remediation 7", "Remediation 8", "Remediation 9"):
        assert remediation in audit
    for trace in (
        "Direct execution",
        "Discovery and replan",
        "Isolated parallel integration",
        "Approval and resume",
        "Budget block",
        "Cancellation",
    ):
        assert trace in audit
    assert "No unresolved critical or high finding remains." in audit
    assert "### Phase 21 handoff" in guide
    assert "Phase: 21 — Final integrated review" in guide
    assert "Next phase and its dependencies: Phase 22" in guide
