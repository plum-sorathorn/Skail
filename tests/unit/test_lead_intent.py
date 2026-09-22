from __future__ import annotations

from skail.agents.lead import LeadControls, resolve_lead_controls


def test_direct_instruction_is_a_run_scoped_no_delegation_constraint() -> None:
    controls = resolve_lead_controls(
        "Please do this yourself; do not delegate.", LeadControls()
    )

    assert controls.direct_only is True
    assert controls.delegation == "off"


def test_no_edit_instruction_disables_write_tools() -> None:
    controls = resolve_lead_controls("Review only. Do not edit files.")

    assert controls.write_allowed is False


def test_exact_agent_instruction_sets_a_run_scoped_count() -> None:
    controls = resolve_lead_controls("Use exactly two agents for independent reviews.")

    assert controls.required_agent_count == 2
    assert controls.max_children == 2


def test_explicit_constraints_do_not_leak_into_the_next_run() -> None:
    constrained = resolve_lead_controls("Handle this yourself and do not edit files.")
    unconstrained = resolve_lead_controls("Continue with the next task.")

    assert constrained.direct_only is True
    assert constrained.write_allowed is False
    assert unconstrained == LeadControls()
