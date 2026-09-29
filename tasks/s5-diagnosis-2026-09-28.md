# S5 discovery failure diagnosis

**Current result:** S5's main adaptive-plan acceptance path passed in fresh run
`31f697cc-3018-43c8-a6fe-af638ad819e5`, session `5a70dbd0-e94c-480d-b3b2-c0cee319f90d`.
Both explorer reports were accepted; checkpoint success at event 59 preceded writer-running event
66; revision 2 added the scoped implementer; all four nodes succeeded. Only
`src/live_fixture/parser.py` changed, its digest matches the accepted result, no untracked files
remain, and all four precommitted parser tests passed with provider credentials removed.
The mounted TUI `/plan` replay of a copied live journal matched revision 2, all node IDs and successful
states. This is provider-free replay evidence; the raw live terminal capture alone was insufficient.
Conditional cancellation/question follow-ups remain in R9; they were not exercised in this successful run.

The September 28 diagnostic runs establish a current source-reference failure. They do not recover
the missing cause of the historical explorer failures. The historical `task.failed` events contain
`reason: null`, no safe category/path, and no original child result; attributing them to the current
failure would be speculation.

## Proven causes and separate blockers

| Observation | Diagnosis |
|---|---|
| Historical plan omitted agent resource scopes (LIVE-026) | Invalid model-authored plan; subsequent historical plans admitted after scope guidance was repaired. |
| Historical explorers failed, then retries reported `auto_ineligible` (LIVE-024) | Initial failure unknown. Retry eligibility is a separate downstream blocker, not its cause. |
| Historical ambiguous Qwen lead call (LIVE-025) | Provider outcome remains unknown; preserve its conservative settlement and never replay that assignment. |
| Fresh run `b83abbeb-f37c-4379-9ad0-3b07beae58a0` | One explorer rejected at `$.verification`; retry ineligible. Second explorer budget-blocked before execution because the operator's $0.60 cap could not cover concurrent GPT-4.1 lead/child reservations. All eight calls measured. |
| Fresh run `5b58d45d-d2b6-4bd5-85aa-1c176b2648af` | Both discoveries rejected for invalid source references: `/tests/test_parser.py:4` and basename-only `parser.py:4` are not full workspace-relative paths. Both retries ineligible. All fourteen calls measured. |
| Fresh run `54c3f34d-ef06-4ddd-943f-c98f36b95a55` | Mini lead submitted conflicting revision metadata before initial admission; tool calls initially lacked an accepted decision. One explorer's glob missed the explicitly named test file; another used read offset 60 beyond a 6/22-line file. No source-backed discovery acceptance; all eleven calls measured. |
| Fresh run `1a9becce-cc61-459c-86bc-ad6f70d28a8c` | Both explorers accepted, checkpoint succeeded, revision 2 correctly added the writer. Writer admission blocked under the $0.90 cap, before a provider call. Existing lead and batch-continuation reservations plus the next batch allowance reduced available budget. All nine calls measured. |
| Fresh run `31f697cc-3018-43c8-a6fe-af638ad819e5` | Same corrected workflow with a $1.25 cap completed and passed independent verification; all fourteen calls measured. |

The evaluated child reports in the second run have matching required criteria and nonempty evidence.
The runtime returns `analysis requires valid concrete source references`. A provider-free replay of
all nine extracted references rejects every original spelling and accepts every full relative-path
correction at the same line number. This isolates the path-format failure without weakening the
validator or treating model-authored findings as independently verified facts.

`RunController._validate_source_at` resolves a reference against the workspace, rejects paths outside
it and sensitive paths, and checks file existence and line bounds. The generic child guidance
previously said only `path:line`; it now explicitly requires the full workspace-relative path,
without a leading slash or drive letter, and explains that virtual tool-display slashes must be
omitted. The assembled two-explorer/checkpoint/writer regression failed before this guidance change
and passed afterward. No permission, source validator, result acceptance, or routing rule changed.

## Model selection and budget

The user explicitly authorized selecting models and reading the API credential from `.env` without
displaying it. Each fresh isolated HOME enabled `gpt-4.1` and `gpt-4.1-mini`; native authenticated
`skail models refresh` returned 142 priced models. GPT-4.1 prices were input/cached/output
$2/$0.50/$8 per million, mini $0.40/$0.10/$1.60. Frozen call pricing remains authoritative.

These are explicit **manual** routes with current price/tool/structured-output facts. No trusted
capability vector was invented. Enabling a model does not make it automatically eligible. The prior
S5 hold incorrectly reused the S8 implementer retry floor of 0.65; initial automatic explorer floor
is 0.35 (ordinary auto retry 0.50), while manual selection has no capability floor. Missing trusted
capability evidence still blocks automatic retries. This does not prevent an authorized fresh manual
S5 run. The corrected offline assembled path justifies that run independently of historical causation.

The five fresh runs cost $0.1995512 total, all measured across 56 unique calls. Cumulative campaign
local estimate is $3.946369484; S5 has used $0.631559654 of $2.25, leaving $1.618440346.
Provider billing remains unknown. The passing run used GPT-4.1 for all roles, a $1.25 reservation
cap, exact initial revision-1 instructions, and named-file reads with offset 0. No prior assignment
was replayed. Reservation allowances are not measured spend and released allowances are not charged.

## Evidence and limits

All paths below are relative to `out/live-agentic/`:

- `s5-diagnosis-20260928/`: fresh manual run, full export, catalog facts, transcript, reconciliation.
- `s5-diagnosis-20260928-attempt2/`: full export, `evaluated-child-results.jsonl`,
  `source-reference-replay.json`, reconciliation.
- `s5-diagnosis-20260928-attempt3/`: post-guidance run, full export, evaluated result, ordered gate logs.
- `s5-diagnosis-20260928-attempt4/`: bounded corrective run and its qualification record.
- `s5-diagnosis-20260928-attempt5/`: passing export, evaluated results, `verification.json`,
  `operator-parser-tests.log`, `plan-replay.svg`, frozen catalog, and reconciliation.

Ordered offline gates passed after the source-guidance change: Ruff, strict mypy (126 files),
unit/contract (927 passed, 2 skipped), smoke, and full suite (1,231 passed, 5 skipped). Logs are in
attempt3. Graphify updated; it warned that 14 non-code fixture files yielded no AST nodes.
These checks do not renew the earlier package/release or hosted-platform qualification for the new
source revision, establish the 20% suite-speed objective, or close S8 automatic escalation.

The per-attempt diagnostic entry point observes `parse_child_result`'s return before retry overwrites
the task-level journal result. It returns the original object unchanged and redacts credential values;
it does not alter validation or provider responses. Historical exports remain untouched. A remaining
diagnostic limitation is that production task-level storage replaces the detailed first result with
the retry's terminal result; exported failure category/path alone can conflate different verification
failures. The retained observer resolves this fresh diagnosis but is not a shipped persistence fix.

Fixtures are isolated clones. Strict/permissive parser tests were authored and committed by the
operator **before** each run; they must never be credited as Skail output. This fixture has a Python
API and no CLI, so `strict=True` is its applicable strict option. A live pass requires accepted
discoveries, checkpoint/revision, later integrated scoped implementation, independent parser tests,
and a rendered `/plan` comparison. A completed marker alone is insufficient.
