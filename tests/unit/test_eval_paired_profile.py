from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from evals.runner import EvaluationRunner
from evals.schema import (
    CANONICAL_PAIRED_RUNTIME_PROFILE,
    EvaluationFixture,
    EvaluationPolicy,
    EvaluationPolicyControls,
    ExecutionScript,
    OracleSpec,
    OracleType,
    RawExecutionRecord,
    ScriptedModelResponse,
    ScriptedUsage,
    TaskEvalResult,
)


def _fixture() -> EvaluationFixture:
    return EvaluationFixture(
        id="canonical-paired-profile",
        title="Canonical paired profile",
        category="parallel",
        prompt="Complete the deterministic fixture.",
        parallel_eligible=True,
        execution=ExecutionScript(
            final_response=ScriptedModelResponse(
                content="done",
                usage=ScriptedUsage(
                    input_tokens=1,
                    output_tokens=1,
                    cost_usd=Decimal("0.00"),
                ),
            )
        ),
        oracle=OracleSpec(type=OracleType.MULTI_ASSERT),
    )


def test_canonical_paired_profile_freezes_required_runtime_matrix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = CANONICAL_PAIRED_RUNTIME_PROFILE

    assert profile.id == "paired-runtime-v1"
    assert profile.paired_seeds == (42, 100)
    assert profile.repetitions == 5
    assert profile.policies == (
        EvaluationPolicy.AUTO,
        EvaluationPolicy.ECONOMY,
        EvaluationPolicy.QUALITY,
        EvaluationPolicy.SERIAL,
        EvaluationPolicy.NO_DELEGATION,
    )
    with pytest.raises(ValidationError):
        profile.repetitions = 1

    def run_cell(
        self: EvaluationRunner,
        *,
        fixture: EvaluationFixture,
        policy: EvaluationPolicy,
        policy_controls: EvaluationPolicyControls,
        catalog_revision: str,
    ) -> tuple[TaskEvalResult, RawExecutionRecord]:
        del self, policy_controls
        return (
            TaskEvalResult(
                fixture_id=fixture.id,
                policy=policy,
                completed=True,
                passed_oracle=True,
                wall_time_seconds=1.0,
                total_cost_usd=Decimal("0.00"),
                models_used=(),
                assignments_count=0,
                escalations_count=0,
                interrupts_count=0,
                catalog_revision=catalog_revision,
            ),
            RawExecutionRecord(
                fixture_id=fixture.id,
                policy=policy,
                script_digest="profile-test",
                usage_cost_usd=Decimal("0.00"),
            ),
        )

    monkeypatch.setattr(EvaluationRunner, "_run_fixture_policy", run_cell)
    report = EvaluationRunner.paired_runtime(fixtures=[_fixture()]).run()

    assert report.run_profile_id == profile.id
    assert report.paired_seeds == profile.paired_seeds
    assert report.repetitions == profile.repetitions
    assert len(report.results) == len(profile.policies) * len(profile.paired_seeds) * 5
    assert set(report.policy_summaries) == {policy.value for policy in profile.policies}
