"""Planned-mode guidance carries a minimal valid skeleton (plan-schema prompt gap)."""

from __future__ import annotations

from skail.agents.lead import TASK_PACKET_GUIDANCE
from skail.runtime.decisions import ExecutionDecisionGate

_REQUIRED_TOKENS = (
    "schema_version",
    "policy_version",
    "revision",
    "nodes",
    "local_id",
    "kind",
    "objective",
)


def test_guidance_carries_minimal_planned_skeleton() -> None:
    for token in _REQUIRED_TOKENS:
        assert token in TASK_PACKET_GUIDANCE, token
    assert "checkpoint" in TASK_PACKET_GUIDANCE


def test_guidance_does_not_reissue_admitted_agents_through_task_tool() -> None:
    guidance = " ".join(TASK_PACKET_GUIDANCE.split())
    assert "Skail dispatches admitted AGENT nodes" in guidance
    assert "Do not call task() for agents already in a planned execution" in guidance


def test_skeleton_shape_admits_first_try() -> None:
    admitted: list[object] = []
    gate = ExecutionDecisionGate(admit_plan=admitted.append)
    decision = gate.admit(
        {
            "mode": "planned",
            "objective": "Survey the work area",
            "reason": "Bounded survey before changes.",
            "plan": {
                "schema_version": 1,
                "policy_version": "adaptive-v1",
                "revision": 1,
                "nodes": [
                    {
                        "local_id": "survey",
                        "kind": "agent",
                        "objective": "Survey the target area",
                    },
                    {
                        "local_id": "gate",
                        "kind": "checkpoint",
                        "objective": "Review the survey evidence",
                    },
                ],
            },
        }
    )
    assert decision.mode.value == "planned"
    assert gate.repairs_remaining == 2
    assert len(admitted) == 1
