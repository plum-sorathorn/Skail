from decimal import Decimal

import pytest

from evals.runner import EvaluationRunner
from evals.schema import (
    EvaluationFixture,
    EvaluationPolicy,
    ExecutionScript,
    OracleSpec,
    OracleType,
    ScriptedModelResponse,
    ScriptedToolCall,
    ScriptedUsage,
)


def test_paired_matrix_records_each_seed_repetition_and_execution_order() -> None:
    fixture = EvaluationFixture(
        id="paired-matrix",
        title="Paired matrix",
        category="routine",
        prompt="Write result.txt",
        execution=ExecutionScript(
            responses=(
                ScriptedModelResponse(
                    tool_calls=(
                        ScriptedToolCall(
                            name="write_file",
                            args={"path": "result.txt", "content": "done\\n"},
                            id="write-result",
                        ),
                    ),
                    usage=ScriptedUsage(
                        input_tokens=10,
                        output_tokens=4,
                        cost_usd=Decimal("0.01"),
                    ),
                ),
            ),
            final_response=ScriptedModelResponse(
                content=(
                    '{"status":"succeeded","summary":"done",'
                    '"verification":[{"criterion":"result","passed":true,'
                    '"evidence":"result.txt:1"}]}'
                ),
                usage=ScriptedUsage(
                    input_tokens=8,
                    output_tokens=3,
                    cost_usd=Decimal("0.01"),
                ),
            ),
        ),
        oracle=OracleSpec(type=OracleType.FILE_EXISTS, target="result.txt"),
    )

    report = EvaluationRunner(
        fixtures=[fixture],
        policies=(EvaluationPolicy.AUTO, EvaluationPolicy.SERIAL),
        paired_seeds=(42, 100),
        repetitions=2,
    ).run()

    assert len(report.results) == 8
    assert len(report.raw_records) == 8
    assert report.paired_seeds == (42, 100)
    assert report.repetitions == 2
    assert {
        (record.policy, record.seed, record.repetition)
        for record in report.raw_records
    } == {
        (policy, seed, repetition)
        for policy in (EvaluationPolicy.AUTO, EvaluationPolicy.SERIAL)
        for seed in (42, 100)
        for repetition in (1, 2)
    }
    assert sorted(record.execution_order for record in report.raw_records) == list(range(8))


def test_paired_matrix_rejects_an_explicitly_empty_seed_set() -> None:
    with pytest.raises(ValueError, match="paired_seeds must not be empty"):
        EvaluationRunner(fixtures=[], paired_seeds=())
