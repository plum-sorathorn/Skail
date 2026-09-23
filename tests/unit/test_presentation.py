import json

from skail.runtime.presentation import (
    model_content_to_text,
    present_lead_answer,
    structured_output_for_jsonl,
)


def test_presenter_shows_json_answer_once_and_keeps_verification_out_of_chat() -> None:
    raw = json.dumps(
        {
            "answer": "Updated `src/example.py:run` and verified the result.",
            "verification": [
                {
                    "criterion": "No delegation",
                    "passed": True,
                    "evidence": "No child task was created.",
                }
            ],
        }
    )

    answer = present_lead_answer(raw)

    assert answer == "Updated `src/example.py:run` and verified the result."
    assert "Criterion" not in answer
    assert "Passed" not in answer
    assert "No child task" not in answer


def test_presenter_reports_evidence_only_json_without_inventing_an_answer() -> None:
    raw = json.dumps(
        {
            "verification": [
                {
                    "criterion": "No delegation",
                    "passed": True,
                    "evidence": "No task/subagent calls were made.",
                }
            ]
        }
    )

    answer = present_lead_answer(raw)

    assert "without a user-facing answer" in answer.lower()
    assert "Passed" not in answer
    assert "No task/subagent calls" not in answer


def test_presenter_uses_summary_without_appending_structured_evidence() -> None:
    answer = present_lead_answer(
        '{"summary":"The run completed.","verification":[{"passed":true}]}'
    )

    assert answer == "The run completed."


def test_presenter_preserves_supported_legacy_answer_fields() -> None:
    for field in ("reply", "content", "output", "result", "final"):
        raw = json.dumps({field: "The work is complete.", "verification": [{"passed": True}]})

        assert present_lead_answer(raw) == "The work is complete."


def test_presenter_preserves_unrecognized_json_and_malformed_json_as_literals() -> None:
    unknown = '{"requested_payload":{"count":2}}'
    malformed = '{"answer": "unfinished"'

    assert json.loads(present_lead_answer(unknown)) == json.loads(unknown)
    assert present_lead_answer(malformed) == malformed


def test_presenter_preserves_plain_technical_details() -> None:
    prose = "Passed: True; Criterion: No delegation; Evidence: No child task was created."

    assert present_lead_answer(prose) == prose


def test_jsonl_output_keeps_json_structured_and_plain_responses() -> None:
    structured = '{"answer":"Done.","verification":[{"passed":true}]}'

    assert structured_output_for_jsonl(structured) == json.loads(structured)
    assert structured_output_for_jsonl("Done.") == "Done."


def test_model_content_to_text_extracts_text_blocks_without_python_repr() -> None:
    content = [
        {"type": "text", "text": "First sentence."},
        {"type": "image", "url": "opaque-image-reference"},
        {"type": "text", "text": "Second sentence."},
    ]

    assert model_content_to_text(content) == "First sentence.\nSecond sentence."
    assert model_content_to_text({"answer": "Done."}) == '{"answer": "Done."}'
