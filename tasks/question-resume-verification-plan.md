# Question Resume Verification Plan

## Offline regression

`tests/contract/test_question_resume_contract.py` uses scripted model responses and a disposable
`tmp_path` workspace to interrupt for a format choice, resume with JSON, and check that only
`exporter.py` and `test_exporter.py` are written. The contract independently runs the generated
focused test with pytest from that fixture and verifies that no CSV file was created. This is
deterministic offline evidence of the JSON selection/exporter path; it is not a provider call or a
live TUI result.

## Live confirmation

This regression does not establish mounted Textual question/resume behavior in the same live run,
nor does it change the recorded status of S6. Any live confirmation remains pending until a new
operator TUI run captures the restored question, accepted answer, continued work, final output, and
workspace changes together. Do not infer a live pass from the offline fake-model contract.
