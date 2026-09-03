from rudder.runtime.escalation import bounded_handoff, escalation_floor


def test_escalation_raises_floor_once_and_bounds_handoff() -> None:
    assert escalation_floor(0.70) == 0.85
    assert escalation_floor(0.85) == 0.90
    handoff = bounded_handoff(summary="x" * 2_000, evidence=("a", "b"), max_items=1)
    assert len(handoff.summary) == 1_000
    assert handoff.evidence == ("a",)
