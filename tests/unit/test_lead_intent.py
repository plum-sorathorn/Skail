from __future__ import annotations

from skail.agents.lead import TASK_PACKET_GUIDANCE, LeadControls, resolve_lead_controls


def test_direct_instruction_is_a_run_scoped_no_delegation_constraint() -> None:
    controls = resolve_lead_controls(
        "Please do this yourself; do not delegate.", LeadControls()
    )

    assert controls.direct_only is True
    assert controls.delegation == "off"


def test_explicit_planned_execution_sets_a_required_run_mode() -> None:
    controls = resolve_lead_controls("Use planned execution for this task.")

    assert controls.required_mode.value == "planned"


def test_mentioning_planned_execution_does_not_require_it() -> None:
    controls = resolve_lead_controls("What does 'use planned execution' mean?")

    assert controls.required_mode is None


def test_child_scoped_no_further_delegation_preserves_planned_mode() -> None:
    controls = resolve_lead_controls(
        "Use planned execution. Each explorer reports directly; do not delegate further."
    )

    assert controls.required_mode.value == "planned"
    assert controls.direct_only is False
    assert controls.delegation == "auto"


def test_explicit_choice_question_is_a_run_scoped_requirement() -> None:
    controls = resolve_lead_controls(
        "Before editing, ask me to choose exactly one format. "
        "Do not edit any files until I answer."
    )

    assert controls.requires_user_answer is True
    assert controls.write_allowed is None


def test_mentioning_ask_me_to_choose_does_not_require_a_question() -> None:
    controls = resolve_lead_controls("What does 'ask me to choose' mean?")

    assert controls.requires_user_answer is False


def test_no_edit_instruction_disables_write_tools() -> None:
    controls = resolve_lead_controls("Review only. Do not edit files.")

    assert controls.write_allowed is False


def test_do_not_edit_or_delegate_is_a_direct_no_write_constraint() -> None:
    controls = resolve_lead_controls(
        "Review this file. Do not edit or delegate.", LeadControls()
    )

    assert controls.direct_only is True
    assert controls.delegation == "off"
    assert controls.write_allowed is False


def test_exact_agent_instruction_sets_a_run_scoped_count() -> None:
    controls = resolve_lead_controls("Use exactly two agents for independent reviews.")

    assert controls.required_agent_count == 2
    assert controls.max_children == 2


def test_exact_child_agent_instruction_sets_a_run_scoped_count() -> None:
    controls = resolve_lead_controls("Use exactly two child agents in parallel.")

    assert controls.required_agent_count == 2
    assert controls.max_children == 2


def test_exact_implementer_agent_instruction_sets_a_run_scoped_profile() -> None:
    controls = resolve_lead_controls("Use exactly two implementer child agents in parallel.")

    assert controls.required_agent_count == 2
    assert controls.required_agent_profile == "implementer"


def test_lead_guidance_documents_exact_agent_resource_scopes() -> None:
    assert "resource_scopes" in TASK_PACKET_GUIDANCE
    assert "task_features.profile" in TASK_PACKET_GUIDANCE
    assert "exactly N agent nodes" in TASK_PACKET_GUIDANCE
    minimal_plan = TASK_PACKET_GUIDANCE.split("Minimal planned shape (copy this):", 1)[1].split(
        "Plan fields are validated:", 1
    )[0]
    assert '"effect_scope": "read"' in minimal_plan
    assert '"resource_scopes": ["<survey-scope>"]' in minimal_plan
    assert '"depends_on": ["survey"]' in minimal_plan


def test_explicit_constraints_do_not_leak_into_the_next_run() -> None:
    constrained = resolve_lead_controls("Handle this yourself and do not edit files.")
    unconstrained = resolve_lead_controls("Continue with the next task.")

    assert constrained.direct_only is True
    assert constrained.write_allowed is False
    assert unconstrained == LeadControls()
