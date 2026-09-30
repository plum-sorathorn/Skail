from skail.runtime.escalation import bounded_handoff, escalation_floor


def test_escalation_raises_floor_once_and_bounds_handoff() -> None:
    assert escalation_floor(0.70) == 0.85
    assert escalation_floor(0.85) == 0.90
    handoff = bounded_handoff(summary="x" * 2_000, evidence=("a", "b"), max_items=1)
    assert len(handoff.summary) == 1_000
    assert handoff.evidence == ("a",)


def test_bounded_handoff_retains_only_safe_diagnostics() -> None:
    handoff = bounded_handoff(
        summary="x",
        failure_category="result_validation",
        validation_path="$.artifacts.0.kind",
    )
    assert handoff.failure_category == "result_validation"
    assert handoff.validation_path == "$.artifacts.0.kind"

    unsafe_handoff = bounded_handoff(
        summary="x", failure_category="nope", validation_path="$.not a path"
    )
    assert unsafe_handoff.failure_category is None
    assert unsafe_handoff.validation_path is None
