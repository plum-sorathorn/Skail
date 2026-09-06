# Rudder adaptive orchestration and release implementation guide

Status: **Ready for phased implementation; no phase or release gate is certified by this document.**
Prepared: 2026-09-05
Workspace: `C:\Users\plum\Documents\Works\Rudder`
Branch: `rudder`
Target: v0.1.0 remediation plus adaptive execution graphs and outcome-based routing.

## 1. Read this first

This guide combines the proposed orchestration redesign with the remaining v0.1.0 remediation. It is an implementation handoff, not evidence that the implementation already works. Execute one numbered phase at a time, verify and commit it independently, then check in with the user and stop before starting the next phase.

The objective is lower **total cost per successfully completed user request**, with quality parity and useful parallel speedups. Agent count, low token prices, and plausible planning output are not success metrics.

The user selected these design boundaries:

- Quality parity with a capable single-agent baseline; do not deliberately trade away completion for savings in the default policy.
- Include isolated parallel editing and verified integration, with a serialized fallback.
- Implement orchestration/routing and preserve core harness capabilities; maintain a separate feature-parity roadmap.
- Use the existing subscriptions economically for implementation. Do not make paid provider calls, integrate Codex OAuth, buy capacity, push, publish, or rename remotes.

Creating this guide does not authorize executing its release, deletion, or external-service steps now. When the user starts implementation, phase commits and check-ins follow the supplied handoff. Any later explicit session authorization takes precedence over these defaults.

### Verified starting point and evidence limits

The branch history inspected when preparing this guide ends at:

| Commit | Purpose in the supplied remediation history |
|---|---|
| `0b78744` | Reopen release evidence |
| `7546255` | Compose runtime models from catalog configuration |
| `17e6f2c` | Persist provider-call accounting |
| `732a0ca` | Enforce delegated lifecycle |
| `566df68` | Require verifiable task outcomes |
| `34a39c5` | Restore scoped interrupted execution |

The supplied handoff reports 500 passing offline tests, two documented skips, Ruff, and mypy. These are historical results, not the current phase's verification. The preceding architecture investigation ran 37 focused routing/task-lifecycle tests successfully; it did not rerun the full release matrix.

Preserve these existing unrelated working-tree changes. Never stage, overwrite, stash, revert, or incorporate them into release evidence without their owner's explicit instruction:

- `.gitignore`
- `evals/results/run_1.json`
- `evals/results/run_1.md`
- `evals/results/run_2.json`
- `evals/results/run_2.md`

Preserve additional user changes found at implementation time as well. Use explicit staging paths; never `git add .` or `git add -A` for these phases.

### Source documents and precedence

Read the applicable `AGENTS.md`, accepted ADRs, [SPEC](../docs/rudder/SPEC.md), [architecture](../docs/rudder/ARCHITECTURE.md), and [feature contracts](../docs/rudder/FEATURES.md) before their subsystem changes. Query Graphify before locating unfamiliar code.

The existing [remediation tracker](rudder-v0.1.0-release-remediation.md) and [historical implementation plan](plan.md) remain historical records. Phase 00 establishes this guide as the active sequence and adds pointers without deleting history. Do not silently leave conflicting active instructions behind.

The current ADR rejects a static DAG for every prompt and requires lead-originated `task` calls. The new decision is an adaptive plan interpreted by a fixed runtime, with a direct path and compatibility `task` surface. Record that change in a successor ADR before implementing it; do not pretend the old ADR already approves the new topology.

## 2. Reconciliation with the old remediation

| Existing requirement | Combined disposition | New owner |
|---|---|---|
| Remediation 1-6 | Preserve and revalidate; reopen only demonstrated regressions. Phase 2's unchecked tracker entry is not proof its implementation is missing. | 00 and regression gates |
| Remediation 7: events | Implement before the new graph so its decisions use the same persisted event truth. | 02-03, extended in 06-14 |
| Remediation 8: independent evaluation | Build the independent foundation early; measure final execution policies after the redesign. | 04-05, 15 |
| Remediation 8: serialized writers | Retain shared-workspace fixtures; add separate isolated-writer fixtures once isolation is implemented. Never weaken shared-writer exclusion. | 11-12, 15 |
| Remediation 9: raw evidence, packaging, CI | Apply to the redesigned runtime and exact candidate, not an intermediate old-runtime release. | 17-24 |
| Fixed role/risk floors and +0.15 escalation | Retain as compatibility/cold-start behavior; carry hard requirements correctly. Calibrated strategy selection is separately evidence-gated. | 01, 13 |
| Lead chooses every batch | Replace with required execution decisions and automatic dispatch of an accepted plan. | 06-09 |
| Todos are not executable tasks | Preserve. A new validated plan contract creates tasks; arbitrary `write_todos` content never executes. | 06-07 |
| Three children and two attempts | Preserve, including across plan revisions and both dispatch surfaces. | 08-09, 13 |
| Five-percentage-point completion allowance | Superseded for default production policy by quality parity. Offline scripted cases require their expected outcomes; they cannot certify model quality. | 00, 15, Q1 |
| 15% full-runtime speedup | Preserve for the frozen synthetic parallel suite, with five paired repetitions per seed. Do not alter sleeps to pass it. | 15, 17 |
| 20% cost reduction | Preserve as an economic qualification target. Synthetic accounting tests and live savings qualification are different evidence classes. | 15, 17, Q1 |
| 50 approved fixtures versus 1,000 diverse requests | At least 50 independent offline fixtures gate engineering readiness. The larger held-out live corpus gates broad quality/savings claims and production promotion of learned routes. | 05, Q1 |
| Tag before remote rename in old tracker | A tag never authorizes a remote rename. Explicit external authorization is still required. | 00, 24 |
| Legacy cleanup | Separate optional cleanup after preservation reference and release state are verified. Not part of the release candidate implementation. | C1 |

### Two completion boundaries

**Engineering-ready v0.1.0:** all numbered phases pass their required local/platform checks; adaptive graphs and isolation work under independent offline fixtures; unsupported claims are removed. The outcome-based router is implemented and testable, but novel cheaper strategies remain in shadow/experimental mode without qualifying real evidence. `auto` retains the recorded conservative baseline policy where evidence is absent. State this limitation in the UI and docs.

**Economically qualified default:** Q1 supplies independently checked live evidence for workload-specific promotion. No phase may call this complete from fake models. Q1 is externally blocked until the user authorizes a spending cap and provides usable provider access; its absence does not prohibit finishing every offline engineering task. The v0.1.0 release verifier must distinguish engineering readiness from economic qualification rather than silently dropping either gate.

This separation is deliberate: it reconciles the no-spend instruction with implementing a router whose actual competence cannot be measured using scripted models. It does not claim universal savings for the conservative baseline.

## 3. Model allocation and usage discipline

These assignments concern the agents **implementing Rudder**, not hardcoded model choices inside Rudder's router.

Use `gpt-5.6-terra` at medium effort for most Python/runtime changes, raising effort only for a reproduced hard problem. Use `gpt-5.6-luna` for tightly specified compatibility, packaging, and final-document edits. Use `gemini-3.8-flash` for fixture authoring, projection/UI work against fixed contracts, and documentation; use it only through access the user already has. Use `gpt-5.6-sol` at high effort for the four designated architecture/review phases.

This is a task-allocation judgment, not a measured comparison on this repository. Official documentation describes [Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol) as the complex-work tier, [Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra) as balancing intelligence and cost, and [Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna) as cost-sensitive. [Gemini 3.8 Flash documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash) documents tool use and structured outputs. Sources checked 2026-09-05.

API prices do not establish ChatGPT Plus or Google AI Pro quota consumption or entitlement. Account-specific remaining limits and access to these exact names were not verified. Do not estimate how many phases fit in a subscription from API token prices. See [Codex pricing/access guidance](https://learn.chatgpt.com/docs/pricing) for the distinction between access modes.

`GLM-5.3-Flash` is an allowed optional substitute for Luna's bounded work if the user already has working access. It is not a required dependency or justification to purchase another plan. Default fallback for unavailable Gemini access is Luna for docs/fixtures and Terra for code. If Terra is quota-limited, preserve the handoff and wait or use an explicitly available equivalent; do not automatically spend API money.

Usage rules:

1. One active implementing model at a time. No default agent swarm for building this harness.
2. Start each phase with its handoff, applicable contracts, Graphify results, and relevant files, not the entire transcript.
3. Do not run Sol as a permanent supervisor. The four review checkpoints exist to catch architectural mistakes before later work compounds them.
4. Reviews return prioritized findings with reproductions. The phase author fixes them; Sol rechecks the affected diff rather than restarting the whole review.
5. After two unsuccessful attempts at the same implementation defect without new evidence, stop guessing: produce a bounded diagnosis for Terra or the next Sol checkpoint. This is a development-efficiency rule, distinct from Rudder's runtime attempt contract.
6. Test execution uses local compute; concise test output avoids unnecessary model context. Do not repeatedly rerun unchanged passing checks without a reason.
7. Never ask a cheap model to redesign accounting, security, or recovery while supposedly performing a mechanical phase.

## 4. Common phase contract

### Before work

- Verify branch, current commit, changed files, prior phase evidence, and applicable instruction files.
- Search available skills and load relevant ones. Use plain `graphify query`, `graphify explain`, or `graphify path` before unfamiliar exploration; then inspect the specific returned files.
- State the phase's intended behavior and checks. Write a failing meaningful regression before behavior changes.
- If the phase is too large for one focused session, split it into suffixed slices such as `08a` and `08b`, update dependencies, commit and check in after each. Do not silently expand scope.

### Implementation and verification

- Use PowerShell syntax and `apply_patch`. Preserve public compatibility unless this guide explicitly changes it.
- Prefix Git/test/high-output developer commands with `rtk`; if it fails to spawn, use the raw command immediately.
- Run focused tests, affected integration/contract suites, then the complete offline suite for runtime phases and the old remediation 7-9 completion checkpoints.
- Run `python -m ruff check src tests scripts evals benchmarks` and `python -m mypy src\rudder` for Python changes. Extend focused type coverage to new typed evaluation helpers; do not hide errors by dropping paths or adding blanket ignores.
- Use `rtk pytest`, `python scripts\smoke.py --fake-provider`, and `rtk git diff --check` as applicable. Documentation-only phases need link/content/diff validation, not a gratuitous full suite unless they are the final release candidate.
- Run `graphify update .` after source changes and applicable documentation changes. Review generated changes and stage only intended graph artifacts under repository policy. Do not enable paid semantic extraction.
- All CLI/TUI tests isolate user-home/session/config/trust/credential paths in temporary directories and explicitly choose fake execution. Never print environment secrets.

### Commit and handoff

Review the complete phase diff, stage explicit phase paths, commit, then report to the user and stop. Do not start the next phase in the same continuation.

Each phase record must contain: commit, implementation model, acceptance evidence, exact commands/results, skips with reasons, known limitations, protected-file status, and the next phase. Mark completion only after verification. Tracker completion may reference the phase commit in the following handoff; do not try to embed a commit's own hash in itself.

No checkmark, commit title, model report, or generated summary substitutes for actual runtime evidence.

## 5. Architecture contract for implementation

### Control flow

The initial lead call returns a final answer or records `direct`, `discover`, or `planned` execution through a structured control tool. This is part of the first necessary model call, not a separate classifier. Runtime middleware enforces the decision before operational tool calls; the same response may contain a valid decision followed by compatible tools, processed in that order. Allow a scoped user-question interrupt before a decision if user intent is genuinely required.

Direct execution retains the capable DeepAgent tool loop. It can submit a plan later when new evidence warrants it. Discovery submits only the next evidence-gathering frontier and an explicit decision checkpoint. Planned execution submits a finite dependency graph; completed prerequisites release known work without lead calls.

Wake the lead for discovery checkpoints, contradictory evidence, changed scope, unresolved failures, integration conflicts, material steering, and final synthesis. Do not wake it for every ordinary worker success. Preserve a stable lead assignment for the run; do not change a healthy model mid-loop.

Use a fixed LangGraph coordinator with typed plan data. Do not generate Python, compile arbitrary model-authored code, or infer executable tasks from todo prose. Keep the current compiled child lifecycle and standard `task` surface through one shared task service. A compatibility `task` call becomes one validated plan task, not a second scheduler.

LangGraph parallel supersteps can wait for unrelated siblings. Use a durable ready queue plus independent child execution/checkpoint namespaces and completion notifications. The in-process dispatcher may use asynchronous waits for the first completion; persist launch intent and result transitions before exposing them. Do not rely on process memory or a large join node for correctness. This does not require a daemon or preview background-agent service.

### Minimum contracts

| Contract | Required meaning |
|---|---|
| `ExecutionDecision` | Direct/discovery/planned mode, objective, constraints, reason; a final answer may terminate without work. |
| `ExecutionPlan` | Schema/policy version, revision, nodes, dependencies, acceptance criteria, unresolved decision checkpoints. |
| `PlanNode` | Agent/tool/verification/integration/checkpoint kind; objective, inputs, output contract, effect/resource scope, task features. |
| `PlanRevision` | Expected prior revision, added/replaced/cancelled unfinished nodes, justification/evidence; completed identities remain stable. |
| `RouteEstimate` | Evidence revision/authority, compatibility result, expected total spend, cost uncertainty, success evidence, latency, candidate strategy and reasons. |
| `WorkspaceSnapshot` | Canonical base, captured relevant dirty/untracked inputs, input digests, isolation/workspace identity. |
| `ChangeSet` | Base snapshot, changed paths/content digests, patch/artifacts, validation and integration status. |
| `VerificationEvidence` | Check identity, tested input/output revision, outcome, authority, artifact reference. |

Use plan-local names in model output; Rudder allocates persistent opaque IDs and resolves dependencies atomically. Reject cycles, missing references, duplicate objectives, invalid scope, and unauthorized effects before execution. A tool node still uses the normal tool/approval boundary; a plan is not permission.

Assignments consume the validated hard requirements on `TaskSpec`, strengthened by current context and explicit constraints. No secondary builder may drop them. Model pinning, delegation off/ask, max children, and permissions apply to both plan and compatibility paths.

Every agent task has at most two attempts across revisions. A node rename is not a fresh retry allowance. Typed failure reasons distinguish competence, provider, environment, approval, budget, invalid output, and stale input. Preserve existing provider retry/fallback accounting without turning it into an unbounded task retry ladder.

Use one schema-repair opportunity for invalid plan output, then return to direct execution without silently widening scope. After two consecutive plan revisions with no new evidence or changed executable work, stop replanning and return to bounded direct work or a truthful blocked result. Existing configured call/time/budget limits remain authoritative.

### Routing and cold start

Choose among direct work, one worker, and feasible plans with up to three active children. Nodes that can be deterministic tool operations do not need agent assignments. Hard filters always precede economic ranking.

Estimate `planning + execution + verification + integration + expected recovery + synthesis`. Include actual assembled input size, expected tool output, model-specific workload/call estimates, output limits, valid cache assumptions, isolation setup, and provider latency. Compare remaining costs at replanning; do not optimize sunk cost. Keep expected costs distinct from launch reservations and conservative per-call admission limits.

An initial empirical implementation uses versioned observations keyed by work family, model/provider revision, relevant harness/tool configuration, and verification authority. Store sample counts, success/failure counts, observed costs, and latency distributions; compute bounded summaries outside the synchronous selection path. Use broader-family evidence for estimates when exact cells are sparse, explicitly marking uncertainty. Do not manufacture quality certification by pooling unrelated work.

For the first implementation, automatic economic promotion requires an approved paired-evaluation policy artifact. Descriptive local statistics alone never promote a route. Cold-start, stale, or unsupported cells use the recorded conservative baseline and emit the reason. Planner confidence is not a success probability. Do not multiply node success probabilities as though correlated tasks and shared verification were independent.

Among quality-qualified strategies select the lowest expected total spend; use estimated elapsed time only for equal cost at the estimator's documented monetary precision, then a stable strategy/model key. Prefer direct work when no evidence-backed decomposition benefit is available. A failed cheap strategy's cost and undetected-error risk belong to its outcome, not to an excluded sample.

Preserve reservations for completion work before launching optional children. If quality-preserving completion is unaffordable, reduce optional work or report budget-blocked; do not weaken hard quality/compatibility requirements silently. Provider charges with uncertain settlement remain uncertain and block unsafe replay.

## 6. Phase index

Every row starts unchecked. Dependencies refer to this guide, not the old phase numbers. Execute the numbered rows in order; dependencies describe what a resumed session must verify.

| Done | Phase | Owner | Main dependency | Deliverable |
|---|---|---|---|---|
| [x] | 00 | Sol | Existing baseline | Reconciled ADR/spec and tracker contract |
| [x] | 01 | Terra | 00 | Authoritative routing inputs and task estimates |
| [x] | 02 | Terra | 01 | Post-commit event delivery |
| [x] | 03 | Luna | 02 | CLI terminal/exit/output contract |
| [x] | 04 | Terra | 03 | Independent evaluator and fixture usage |
| [x] | 05 | Gemini Flash | 04 | Approved offline fixture corpus |
| [ ] | 06 | Terra | 05 | Persistent executable-plan state |
| [ ] | 07 | Terra | 06 | Required execution decisions and plan admission |
| [ ] | 08 | Terra | 07 | Ready-work execution without lead round trips |
| [ ] | 09 | Terra | 08 | Revision-aware context, recovery, and steering |
| [ ] | 10 | Sol | 09 | Independent graph/accounting review |
| [ ] | 11 | Terra | 10 | Reproducible isolated worker snapshots |
| [ ] | 12 | Terra | 11 | Serialized verified integration |
| [ ] | 13 | Terra | 12 | Outcome-based strategy routing in shadow mode |
| [ ] | 14 | Gemini Flash | 13 | Replayable plan/route/workspace TUI |
| [ ] | 15 | Terra | 14 | Honest paired evaluation and timing |
| [ ] | 16 | Sol | 15 | Independent economics/isolation review |
| [ ] | 17 | Terra | 16 | Raw-evidence release verifier |
| [ ] | 18 | Luna | 17 | Packaging and exact-commit CI wiring |
| [ ] | 19 | Terra | 18 | Startup/rendering/security performance checks |
| [ ] | 20 | Gemini Flash | 19 | Honest documentation and feature roadmap |
| [ ] | 21 | Sol | 20 | Final integrated review |
| [ ] | 22 | Terra | 21 | Clean Windows candidate matrix |
| [ ] | 23 | Luna | 22 | Exact final documentation commit |
| [ ] | 24 | Terra | 23 | Exact-commit verification and conditional tag |

Q1 is the separately authorized live qualification track. C1 is optional archive cleanup after release. Neither is silently included in a normal numbered-phase run.

## 7. Detailed phases

### Phase 00 — Lock the successor architecture and release boundaries

**Owner:** `gpt-5.6-sol`, high. **Depends on:** baseline only. **Scope:** documentation/contracts; no runtime rewrite.

1. Verify the reported commit history and inspect behavior behind remediation 1-6. Record discrepancies without reopening unrelated working code merely because a tracker is stale.
2. Write a successor ADR covering adaptive plan execution, standard-task compatibility, isolated writers, model stickiness, outcome qualification, and the two release boundaries above. Keep ADR 0001 as historical and annotate superseded decisions.
3. Update only relevant SPEC/architecture/feature sections. Replace the production default's five-point quality allowance; retain historical diagnostic metrics with their original labels.
4. Link this guide from `tasks/plan.md`, `tasks/todo.md`, and the remediation tracker. Map remaining old checkboxes to their new phase owners. Correct any implication that tagging authorizes remote renaming.
5. Freeze plan/node/event schema responsibilities and migration version ownership. Reuse existing domain concepts; no speculative extension framework.

**Acceptance:** no conflicting active execution/release instructions; old completed work is preserved; numbered phases can proceed without another architecture permission question. Commit `docs(rudder): define adaptive execution and release contracts` and check in.

### Phase 01 — Fix the routing boundary before changing the policy

**Owner:** `gpt-5.6-terra`, medium. **Depends on:** 00.

Start with routing requirements, selector, controller assignment paths, profiles, and estimator. Inspect their current call graph first.

1. Create one authoritative derivation path for lead, batch, compatibility-task, and retry requirements. Preserve role hard minimum, tools, structured output, modalities, context/output requirements, user pins, exclusions, and budget constraints.
2. Replace bootstrap-sized per-model estimates with estimates built for the actual task packet. Use existing profile expected-call counts as explicitly labelled priors until observed estimates are available. Include tool-result and cache assumptions; never assume cache hits merely because a provider supports them.
3. Preserve manual selection behavior for unknown models while checking hard compatibility. Unknown price/usage is not zero.
4. Keep current ranking and fixed-attempt semantics during this phase, making later behavioral comparisons attributable.

**Acceptance:** incompatible candidates are rejected through the actual controller, not only selector unit tests; two materially different workloads produce different justified estimates; retries retain hard requirements. Run focused selector/requirements/assignment/controller tests plus common gates. Commit `fix(routing): preserve task requirements and workload estimates`.

#### Phase 01a — Preserve validated requirements through controller assignment

**Scope:** Carry `TaskSpec.requirements` into compatibility-task batch assignment and retry
assignment, including role hard minimum, tools, structured output, modalities, context/output
limits, model-policy floor, exclusions, and budget. Derive the lead assignment from the lead
profile's hard requirements. Do not change estimates, ranking, or manual unknown-price behavior.

**Acceptance:** the actual controller rejects a delegated candidate that lacks the profile-required
tool capability; retry derivation retains validated hard requirements and exclusions. This slice is
complete only with focused routing/controller tests and the common Python gates.

#### Phase 01b — Estimate actual task packets and preserve manual unknowns

**Scope:** Replace bootstrap candidate estimates with packet-aware estimates and profile expected-call
priors, then verify manual unknown-price compatibility and hard-budget behavior without changing
ranking or fixed-attempt semantics.

**Depends on:** Phase 01a.

### Phase 02 — One post-commit event delivery path

**Owner:** `gpt-5.6-terra`, medium. **Depends on:** 01. **Replaces:** old remediation 7 event core.

1. Trace journal transactions and existing event bus/subscribers. Append the event envelope in the same transaction as its state transition; notify subscribers only after successful outer commit. A rollback emits nothing.
2. Use one shared subscription service for JSONL and TUI. Register subscribers before services capture observers, or resolve current subscribers dynamically. Subscriber exceptions cannot undo committed state or suppress other subscribers.
3. Persist event IDs, ordered sequence/cursor, run/invocation identity, and applicable task/attempt/assignment/tool/interrupt IDs. Do not fabricate child IDs for run-only events.
4. Cover model activity/output, tools, task/result, routes, budgets, questions, approvals, checkpoint, compaction, resume, and cancellation. Add typed payloads sufficient to rebuild panels without prose parsing.
5. Support reconnect/replay by durable cursor. Delivery may be replayed after a crash; consumers deduplicate by event ID. Promise one persisted logical event, not magical exactly-once delivery to arbitrary external observers.

**Acceptance:** subscriber reads see committed rows; rollback/nested transaction/reentrant subscriber tests pass; reconstructed projections equal live projections. Run event, journal, projection, and CLI/TUI integration suites. Commit `fix(events): deliver correlated journal events after commit`.

### Phase 03 — Terminal events, exit codes, and isolated CLI tests

**Owner:** `gpt-5.6-luna`, medium; escalate transaction design defects to Terra. **Depends on:** 02. **Completes:** old remediation 7.

This phase is split into two reviewable slices because terminal state ordering and invocation/output
ownership are separate concerns. Both slices are complete.

#### Phase 03a — Atomically commit terminal failure and cancellation events

**Status:** complete. **Scope:** controller terminal exception paths only.

Update run, task, attempt, and session state in the same journal transaction that appends a
`run.failed` or `run.cancelled` event. Post-commit observers must never see a terminal event while
the corresponding run is still `running`; this applies to initial execution and resumed
interrupted execution. Preserve the existing uncertain-settlement error behavior.

**Acceptance:** a production `RunController` subscriber reading the journal during a terminal
failure observes the committed failed state; the same transaction ordering is used for cancellation
and resumed failures. Focused controller/event tests, affected suites, Ruff, mypy, Graphify, and
diff checks pass.

1. Centralize terminal responsibility for each invocation with a persisted run. Distinguish invocation identity from run identity so resume can have one invocation outcome without creating contradictory terminal task/run states.
2. Cover bootstrap-after-run-creation, routing, provider, checkpoint, resume, blocked, and cancellation exits. Failures before persistence still return the correct CLI error without inventing persisted events. An unavailable journal cannot honestly promise durable delivery; return failure and a truthful diagnostic rather than fabricate a success envelope.
3. Preserve exit codes `0` success, `1` failure, `2` usage error, `3` blocked, `4` cancelled. Persist one terminal envelope and avoid duplicate emission by nested handlers.
4. Print stdout contains only final output; JSONL stdout contains only envelopes. Retain `--jsonl` and documented `--json` compatibility. Progress/errors go to the correct stderr channel.
5. Isolate subprocess CLI tests from actual home, trust, configuration, credentials, and existing sessions. Exercise the installed entry path where practical.

**Acceptance:** every listed failure path has output/exit/uniqueness coverage; TUI receives early events. Run focused event/CLI/TUI tests, affected suites, full tests, Ruff, mypy, Graphify. Commit `fix(cli): unify invocation termination and output contracts`.

### Phase 04 — Make evaluation execution independent of its oracle

**Status:** complete.

**Owner:** `gpt-5.6-terra`, medium. **Depends on:** 03. **Begins:** old remediation 8.

1. Separate fixture input/workspace/prompt, scripted provider/tool behavior, and private scoring oracle into distinct structures. Provider fakes and script builders must not receive the oracle object or read its target/expected fields.
2. Make scripts express predetermined tool/model behavior with their own explicit usage records. Reported cost and tokens cannot come from route estimates. Oracle expectations remain accessible only to scoring.
3. Reconcile result usage against persisted calls/settlements; account for failed work. Missing usage, missing candidates, stale files, duplicate records, invalid paths, blocked/failed runs, and unresolved settlement must never become successful scored completions.
4. Distinguish expected failure contract fixtures from economic completion fixtures. An expected blocked outcome can pass its contract assertion but is not a successful user task in the economic denominator.
5. Persist immutable raw execution records before summary generation, with an explicit synthetic/offline evidence label.

**Acceptance:** changing only the oracle expectation changes pass to fail while the execution trace remains identical; disabling runtime writes causes required mutation fixtures to fail; changing a routing estimate does not change fake usage. Commit `fix(evals): separate execution scripts from scoring and usage`.

### Phase 05 — Curate independent offline workloads

**Status:** complete.

**Owner:** `gemini-3.8-flash`, medium; fallback Luna. **Depends on:** 04. **Scope:** fixtures, manifest, fixture validation tests.

1. Curate at least 50 distinct approved offline fixtures using the new schema. Retain useful old cases after independently rebuilding scripts; do not merely copy oracle values into a newly named script at runtime.
2. Include direct edits, read-only analysis, dependent discovery, parallel exploration plus serialized writes, retries, budget blocks, invalid requests, recovery, Windows paths, and non-code answers. Separate policy comparisons from failure-contract checks.
3. Add small adversarial oracle mutations and file-write suppression tests. Reset each fixture workspace from its inputs; validate resolved paths remain inside that workspace, including links/junction behavior.
4. Freeze manifest/version/digests before measurement. Record review/approval of each fixture's intended work and scoring meaning; do not equate a schema-valid fixture with an approved one.

**Acceptance:** no fake/model/script has oracle access; all fixtures have independent scoring and explicit evidence class; at least 50 approved cases are real distinct workloads. Run fixture/evaluator suites and common checks. Commit `test(evals): curate independent offline workload fixtures`.

### Phase 06 — Persist plans and their legal transitions

**Owner:** `gpt-5.6-terra`, medium. **Depends on:** 05.

This phase is split into three independently reviewable slices: 06a defines and validates the
versioned framework-free plan contract; 06b persists it atomically with the required journal
migration; 06c connects policy-version resume compatibility and plan events. Later slices may not
reinterpret records created by earlier slices.

#### Phase 06a — Define versioned plan contracts and admission validation

**Scope:** Add domain-owned plan, node, and revision contracts with schema/policy versions and
deterministic whole-graph validation. Model output remains plan-local; no runtime IDs, journal
records, scheduler changes, or event variants are introduced in this slice.

**Acceptance:** valid plans round-trip; missing dependencies, cycles, duplicate local identities,
and invalid node data are rejected before an admission caller can allocate work. Commit
`feat(domain): define validated execution plan contracts`.

#### Phase 06b — Persist atomically admitted plans

**Depends on:** 06a. **Scope:** Add the journal migration and durable plan/node/revision records,
then atomically validate and persist an accepted plan without allocating executable work.

#### Phase 06c — Preserve policy compatibility and emit plan events

**Depends on:** 06b. **Scope:** Record run policy/schema versions, preserve old-session behavior,
reject unsupported future versions, and add typed plan/node/revision event variants.

1. Implement the minimum plan contracts in section 5 with schema versions, runtime IDs, revision compare-and-set, node dependencies, artifact references, and task lineage.
2. Add journal migrations that preserve existing sessions, assignments, usage, approval state, and terminal results. Store the execution policy/schema revision on each new run.
3. Validate the entire proposed graph atomically before allocating executable work: cycles, missing dependencies, invalid kinds, duplicate objectives, scope and authority violations. Reuse the task validator and registry.
4. Existing sessions resume under their recorded old policy; new-plan sessions use the new interpreter. Reject unsupported future versions explicitly. Do not reinterpret todo data as a plan.
5. Add plan/node/revision event variants through phase 02's delivery path.

**Acceptance:** plan round-trip and migration tests pass; invalid graphs produce no partially admitted tasks; old journals resume unchanged. Commit `feat(runtime): persist versioned execution plans`.

### Phase 07 — Require an execution decision and admit plans

**Owner:** `gpt-5.6-terra`, medium. **Depends on:** 06.

1. Add the control-tool/middleware interface for initial direct/discovery/planned decisions, plan submission, and one repair opportunity. Final answers without tool work remain valid.
2. Preserve first-call efficiency: a decision and valid following tool operations can be processed in one response. Reject side effects preceding admission. Do not add a permanent cheap classifier or keyword complexity detector.
3. Keep direct DeepAgent work and allow a later transition to a plan. Discovery plans contain bounded evidence work and a checkpoint, not guessed downstream implementations.
4. Route standard `task(description, subagent_type)` calls through the same admitted-task service. Enforce `delegation=off|ask|auto` on both interfaces. In ask mode planning may occur but children wait for approval.
5. Attach the same user, trust, model, scope, and budget constraints regardless of entry surface.

**Acceptance:** normal prompts exercise direct, discovery, and planned paths with scripted model decisions but no explicit user delegation instruction; a refused/invalid plan cannot bypass controls; simple work has no extra classifier call. Commit `feat(agents): add validated execution decisions and plan admission`.

### Phase 08 — Execute ready work without lead round trips

**Owner:** `gpt-5.6-terra`, high only if needed. **Depends on:** 07.

1. Implement a durable coordinator around existing compiled child graphs. Persist node launch intent, assignment/reservation, execution/checkpoint identity, result verification, and completion before dependent release.
2. Schedule by readiness, explicit priority, and stable creation order; enforce the shared global one-to-three child limit across all dispatch surfaces. Do not reserve an execution slot for a node waiting on prerequisites or an unavailable workspace resource.
3. Handle independent completion notifications so `A -> C` permits C to start when A finishes while independent B is still running. Avoid a batch-wide graph join that waits for B.
4. Execute known authorized tool nodes without an LLM and through the normal security/approval wrapper. Agent nodes retain DeepAgents' local reasoning/tool loop and task-bound model.
5. Preserve verified-success dependency semantics, terminal results, bounded retries, cancellation, and lead/shared writer exclusion.

**Acceptance:** deterministic barriers prove A/C overlap with B, max-three across mixed paths, no dependent release on unverified success, and zero lead calls between predetermined successful nodes. Crash injection cannot double-launch settled work. Commit `feat(runtime): schedule persistent ready work independently`.

### Phase 09 — Replanning, context, interrupts, and recovery

**Owner:** `gpt-5.6-terra`, medium. **Depends on:** 08.

1. Implement evidence-triggered checkpoints and incremental revisions. Completed nodes stay immutable; changed assumptions invalidate affected downstream artifacts/tasks rather than restarting the entire graph.
2. Pass bounded objective/constraints/prerequisite artifacts and source revisions to workers; enable authorized retrieval of additional detail. Preserve failure evidence and unresolved questions during compaction. Do not inherit entire lead transcripts.
3. Reconstruct plan readiness from journal plus checkpoints after interruption. Account for in-flight ambiguous calls before replay. Distinguish node cancellation from a run-level terminal outcome.
4. Preserve existing exact-command approval scoping and policy recheck. New user input revises only affected work; serialize revisions against completion notifications so stale outputs cannot be integrated.
5. Enforce the repair/no-progress limits and attempt lineage across renamed/replaced nodes. Distinguish failure types before choosing escalation, waiting, direct takeover, or blocking.

**Acceptance:** discovery changes later tasks; stale evidence is rejected; unrelated completed work survives replanning; approval/resume/cancel and two-attempt invariants hold across restarts. Commit `feat(runtime): reconcile plan revisions context and recovery`.

### Phase 10 — Independent graph and accounting review

**Owner:** `gpt-5.6-sol`, high, fresh review context. **Depends on:** 09.

Review phases 01-09 against actual CLI/TUI/controller behavior. Trace first-call assignment, every reservation owner, post-commit events, decision enforcement, task compatibility, graph launch/recovery, and cancellation boundaries. Attempt a cycle, mixed direct/task bypass, stale revision, resumed approval, and task rename to reset attempts.

Return severity, concrete reproduction, affected invariant, and minimal fix. Tests must exercise production paths rather than helper-only behavior. Have the original phase owner fix findings in separately scoped follow-up commits and check in after each; this checkpoint remains open until required fixes and regression checks pass.

**Acceptance:** no unresolved critical/high correctness or accounting issue; review evidence distinguishes passing checks from untested claims. Commit the review record if no code changes are needed: `docs(review): record adaptive graph correctness checkpoint`.

### Phase 11 — Snapshot and isolate writer workspaces

**Owner:** `gpt-5.6-terra`, medium. **Depends on:** 10.

1. Add managed worktree/snapshot ownership and immutable base manifests. Capture the relevant current workspace state, including dirty/untracked inputs, without committing, stashing, or altering user changes.
2. Ensure each admitted isolated writer sees the same intended base and required inputs. Do not substitute a clean HEAD checkout or copy secret-bearing ignored files indiscriminately.
3. Validate canonical paths, links/junctions, Git metadata ownership, cancellation, cleanup targets, and safe retention. Keep worktrees with unintegrated changes recoverable.
4. Use a serialized shared-workspace fallback when isolation is unavailable or setup is not worthwhile. Expose the chosen workspace mode and reason.
5. Treat ports, databases, caches, install operations, and external resources separately from file isolation; resource conflicts serialize or block through existing policy.

**Acceptance:** dirty workspace tests show exact input reproduction and zero user mutations; workers cannot escape their permitted root; non-Git/unsupported environments fall back explicitly; interrupted work is retained. Commit `feat(workspaces): create reproducible isolated task snapshots`.

### Phase 12 — Integrate changes under one writer

**Owner:** `gpt-5.6-terra`, medium. **Depends on:** 11.

1. Persist changesets with base/changed-path/content digests and verification references. Check actual effects against declared scope, not just the final prose result.
2. Serialize canonical-workspace integration. Recheck base inputs and detect user edits since launch before applying; preserve conflicts and request bounded lead judgment.
3. Apply dependent changes in verified dependency order. Independent filenames are not sufficient if public interfaces or generated assets conflict.
4. Verify the combined tree and attach evidence to that integrated revision. A child passing tests in isolation does not prove integration success.
5. Make crash recovery explicit around apply/record boundaries using before/after digests and durable intent. Never automatically repeat a possibly applied patch or reset the workspace.

**Acceptance:** two useful isolated writers really overlap; shared writers never overlap; semantic and textual conflict fixtures block unsafe integration; crash/cancel retains recoverable changes and accurate state. Commit `feat(workspaces): verify and serialize changeset integration`.

### Phase 13 — Outcome-based strategy estimates and shadow routing

**Owner:** `gpt-5.6-terra`, medium. **Depends on:** 12.

1. Implement strategy estimates and workload evidence from section 5. Compare direct, one-worker, and feasible parallel plans, including setup, checking, recovery, and integration costs. Do not create extra candidate plans by repeatedly querying models.
2. Store observation provenance/authority and model/harness revisions. Compute empirical summaries offline from immutable outcomes; selection uses a deterministic snapshot without network I/O.
3. Add shadow decisions and explanations while the active conservative policy continues execution. Shadow mode makes no extra provider calls and causes no speculative file effects.
4. Implement policy-artifact qualification, unknown/stale fallback, total-completion allowance, no-route handling, and fixed-attempt binding. Test economic promotion with explicitly synthetic qualification artifacts isolated from production trust.
5. Keep production promotion disabled absent genuine approved paired evidence. A catalog capability vector, self-confidence number, or fake-provider success count cannot satisfy that requirement.

**Acceptance:** a cheap-but-failure-prone strategy loses to a more economical reliable path; uncertainty selects the baseline; cost-sensitive fan-out never starves completion work; shadow results cannot alter execution. Commit `feat(routing): estimate completed-work cost and shadow strategies`.

### Phase 14 — Reconstruct the new execution state in the TUI

**Owner:** `gemini-3.8-flash`, medium; fallback Terra. **Depends on:** 13.

1. Extend existing projections/panels for plan nodes/dependencies, active mode, route reasons, evidence status, workspace/integration state, and actual/estimated/reserved/unknown cost.
2. Reconstruct panels entirely from persisted structured snapshots/events; live and resumed views must agree. Register subscriptions before runtime services run.
3. Make required user judgments visible without confusing planned, queued, executing, waiting approval, verified, integrated, and complete. Do not show unsupported background steering controls.
4. Preserve existing transcript, keyboard flow, questions, approvals, cancellation, compaction, session selection, and stdout behavior. Avoid a cosmetic redesign beyond the new state requirements.

**Acceptance:** Textual pilot/runtime tests exercise real projection updates, early events, resume, cancellation, and route shadow labels. Commit `feat(tui): project adaptive plans routes and integration state`.

### Phase 15 — Paired evaluation of the completed runtime

**Owner:** `gpt-5.6-terra`, medium. **Depends on:** 14. **Completes:** old remediation 8.

1. Use real controller controls for fixed economy, fixed quality, auto, serial, and no-delegation baselines. Fixed baselines pin concrete model identities; changing a routing-mode enum alone is not a fixed baseline. Record executed assignments.
2. Add fixed-model orchestration and new-policy synthetic comparisons to separate model effects from graph effects. Preserve immutable pre-redesign diagnostics/source references; do not maintain a second old runtime inside production solely for comparisons.
3. Extend frozen workloads with direct answers, adaptive discovery, non-barrier dependency execution, recovery, and isolated integration. Compare equivalent useful work and the same effects. Do not compare different tasks merely to favor parallel execution.
4. Keep shared fixtures as independent read-only work followed by serialized writes. Isolated-writer fixtures use matched isolation setup in serial and parallel modes. Deterministic barriers prove actual overlap; timing alone does not.
5. Measure from full controller entry through final settlement and terminal persistence. Child timing is diagnostic. Record setup/integration/verification costs; nothing required for completion is omitted from the comparison.
6. Freeze simulation latency for both policies before measuring. Retain the preserved 450 ms legacy diagnostic workload when reproducing its gate; do not restore the discredited 650 ms adjustment. Never increase sleeps, delete slow cases, select only favorable seeds, or reduce thresholds to pass.
7. Use seeds 42 and 100, seeded execution order, and five repetitions for each parallel fixture/policy/seed pair. Retain every raw repetition, failure, timeout, and invalid run. Define paired speedup as the median of per-fixture values `1 - median(auto repetitions) / median(serial repetitions)` for each seed; require at least 15% for both. Report full wall medians too. Retain the existing maximum ten-percentage-point cross-seed spread check unless a separately evidenced methodology revision is approved.
8. Compute total cost per successful task as all measured task expenditure, including failures, divided by independently successful task count. Zero successes yields unavailable/infinite cost, never zero. Also report failed-work spend explicitly. Synthetic cost comparisons remain synthetic.
9. Record source commit and digest, fixture/catalog/policy digests, seed/order/repetition, OS, Python/dependency versions, timestamps, exact commands, assignments/call/settlement references, and raw observations. Store diagnostics outside the release checkout and never overwrite protected reports.

**Acceptance:** oracle independence, equivalent work, overlap, usage reconciliation, raw retention, and failed gates remaining failed are regression-tested. If speedup fails, profile and fix real overhead in a separate scoped slice; keep this phase open. Run full tests, Ruff including evals/benchmarks, mypy, Graphify. Commit `fix(evals): measure paired end-to-end orchestration outcomes`.

### Phase 16 — Independent economics and isolation review

**Owner:** `gpt-5.6-sol`, high, fresh review context. **Depends on:** 15.

Attack the oracle separation, synthetic labels, cost denominator, baseline pinning, qualification trust, stale evidence, workspace snapshots, external resource isolation, integration replay, and completion reserves. Recompute a small report independently from raw observations. Verify oracle mutation and write suppression actually fail through the controller. Inspect held-out/frozen workload handling for selection bias.

**Acceptance:** no critical/high open issue; simulated quality cannot enable a production route; the reviewer can explain exactly which savings claims remain unproven. Authors repair findings before closure. Commit `docs(review): record routing economics and workspace checkpoint`.

### Phase 17 — Independently validate raw release evidence

**Owner:** `gpt-5.6-terra`, medium. **Depends on:** 16. **Begins:** old remediation 9.

1. Recompute completion, costs, per-fixture medians, paired speedups, repetition coverage, and gates from raw records. Serialized summaries are convenience data and must agree with recomputation; never trust `all_gates_passed`.
2. Reject forged summary values, future/naive timestamps, nonfinite or invalid negative values, missing/duplicate pairs or invocation records, mismatched source/fixture/catalog/policy digests, insufficient repetitions, fewer than 50 approved fixtures, unresolved usage, and missing required platform evidence.
3. Validate declared expected-failure contract outcomes separately from economic successes. Retain unexpected failures in summaries and fail engineering gates where required; do not blanket-drop failure fixtures to achieve 100%.
4. Separate engineering/synthetic gates from live economic qualification. An offline-only report can never certify Q1. Freeze documented freshness policy appropriate to multi-platform CI; do not widen it automatically because evidence expired. Source identity and immutable artifact integrity remain mandatory even for fresh reports.
5. Add an adversarial report with `all_gates_passed=true` and failing raw data; reject it. Also test edited aggregate costs, missing slow repetitions, duplicate successes, and future timestamps.
6. Make release/evaluation scripts function via direct invocation and supported module entry points from a clean environment. Keep helper modules in their intended package boundary; do not accidentally ship the evaluation corpus in the wheel.

**Acceptance:** raw evidence independently determines pass/fail; source and platform mismatches fail closed; unsupported live claims cannot pass. Commit `fix(release): recompute gates from bound raw evidence`.

### Phase 18 — Fresh packaging and exact-commit CI wiring

**Owner:** `gpt-5.6-luna`, medium; Terra handles unexpected packaging architecture issues. **Depends on:** 17.

1. Build exactly one fresh wheel and sdist into temporary storage; inspect both for intended code/assets and exclusion of legacy/runtime-inert material. Validate the sdist can produce the intended wheel in an independent temporary build if required, recording it as a separate validation artifact rather than confusing the primary pair.
2. Install the primary wheel into a clean environment and test from outside the repository so imports cannot fall back to `src/`. Run CLI help/version and explicit fake smoke through the installed command.
3. Prepare Windows/Linux CI for offline suites, static checks, package smoke, security/contracts, and raw-evidence verification against the exact checked-out SHA. CI output includes artifact digests and environment metadata.
4. Keep artifacts/evidence outside the source checkout. Do not rewrite repository URLs, auto-push branches, publish releases, or trigger paid services.

**Acceptance:** installed-wheel execution works with no source-path leakage; legacy is absent; workflow syntax/commands are validated locally. Linux status remains pending until that workflow actually runs on the candidate. Commit `build(release): verify isolated artifacts and platform evidence`.

### Phase 19 — Measure real startup, rendering, and runtime overhead

**Owner:** `gpt-5.6-terra`, medium. **Depends on:** 18.

1. Measure actual CLI startup separately from first useful runtime response. Projection replay throughput does not measure Textual rendering; add a real rendered-update/interaction measurement under three active children and record the harness/environment.
2. Measure event persistence/query, context assembly/redaction, journal growth, scheduler overhead, workspace setup, and integration overhead with reproducible commands and raw repetitions.
3. Retain documented thresholds including greater than 100 event appends/sec and the 15% end-to-end gate. Do not copy old approximately 450 ms startup or zero-stutter claims into new results. New rendering measurements are diagnostic until their acceptance threshold is explicitly documented and reviewed; inherited gates cannot be relabeled diagnostic to avoid failure.
4. Run security/contract suites for Windows filesystem links, command boundaries, redaction canaries, approval isolation, and crash/recovery. Profile failures before optimizing; keep changes scoped and repeat affected measurements after changes.
5. Audit pinned dependency versions and licensing against current authoritative sources. Record exact versions, notices, advisory dates, and limitations. Fix blocking findings or keep release blocked with a precise finding; documenting a critical issue alone does not waive it.

**Acceptance:** performance claims map to actual measured operations, no unresolved release-blocking security/license finding, raw benchmark evidence retained externally. Commit `test(release): measure runtime rendering and boundary performance`.

### Phase 20 — Documentation and separate feature-parity roadmap

**Owner:** `gemini-3.8-flash`, medium; fallback Luna. **Depends on:** 19.

1. Audit active README, AGENTS, SPEC, architecture, feature, CLI, evaluation, performance, threat-model, support, package, and tracker claims against implemented behavior. Preserve historical documents as explicitly historical.
2. Remove or qualify unsupported claims such as unscoped "verified", "zero leakage", "zero UI stutter", "66.7% speedup", real-provider savings, and unrun platform success. Keep exact measured claims only with evidence provenance.
3. Explain adaptive versus direct execution, worktree fallback, approval/steering boundaries, typed plan state, retry limits, shadow routing, and economic qualification pending. Document actual CLI flags and exit codes.
4. Add a core-feature acceptance matrix for streaming, sessions/resume, approvals, steering, skills/memory, provider compatibility, inspection, and context management. Record demonstrated gaps rather than claiming parity from middleware availability.
5. Create a separate backlog for editor integration, external tool/extension interoperability, richer background-agent interaction, and multimodal workflows. No implementations of these features belong in this phase.

**Acceptance:** each active capability claim has tests/evidence or an explicit experimental/unverified label; repository URLs unchanged; docs distinguish engineering release from Q1. Commit `docs(rudder): align adaptive runtime documentation and roadmap`.

### Phase 21 — Final integrated review

**Owner:** `gpt-5.6-sol`, high, fresh review context. **Depends on:** 20.

Review the complete change since the starting baseline with emphasis on real CLI/TUI paths, security, migrations, model/plan contracts, budget ownership, release recomputation, packaging, and documentation truth. Reuse earlier review records but do not treat them as evidence for later changes. Confirm every old remediation 7-9 bullet has an implementation/test owner in this guide.

Require a small representative end-to-end trace for direct, discovery/replan, isolated parallel integration, approval/resume, budget block, and cancellation. Check that no claim requires an unauthorized live run and that tag eligibility cannot be forged from summary fields.

**Acceptance:** no unresolved critical/high finding and no missing release-blocking requirement; fixes land before phase 22. Commit `docs(review): record final adaptive release audit`.

### Phase 22 — Complete the clean Windows candidate matrix

**Owner:** `gpt-5.6-terra`, medium. **Depends on:** 21.

1. Create a clean isolated candidate checkout at the reviewed commit. Preserve the original dirty workspace; do not clean it to satisfy the verifier.
2. Run the complete Windows offline matrix: security/contracts/full tests, Ruff across source/tests/scripts/evals/benchmarks, mypy, smoke, fresh packaging/install, measured benchmarks, paired evaluation, and independent release verification.
3. Store artifacts outside the checkout, record exact source/environment/command identities, and verify source cleanliness afterward. Build caches may live in dedicated temporary paths; do not hide a tracked mutation by excluding it from the cleanliness check.
4. If a gate fails, repair the specific issue in its owning phase/slice and rerun affected checks plus the final matrix on the new commit. Do not reuse a passing report from the superseded candidate.

**Acceptance:** every local required gate passes on the same candidate; external Linux status is represented truthfully. Record evidence references and commit a readiness record if needed: `docs(release): record Windows candidate readiness`. That new commit is not automatically certified; phases 23-24 revalidate the final source.

### Phase 23 — Final synchronized documentation commit

**Owner:** `gpt-5.6-luna`, medium. **Depends on:** 22 and closure of review findings.

1. Synchronize release-facing documentation/metadata and trackers with the actual implementation and verified candidate results. Preserve pending Linux/exact-final-commit/Q1 status where applicable.
2. Keep final release attestations external so the documentation commit does not need to contain its own hash or a prediction that its future verification passed. Refer to the external evidence procedure/location rather than fabricating self-referential evidence.
3. Validate links/content, run Graphify as applicable before committing, review only the intended docs/metadata diff, and leave protected files untouched.
4. Use this exact commit message:

   `docs(rudder): synchronize all documentation and repository metadata for v0.1.0 release`

**Acceptance:** exact-message commit exists; it is the frozen release candidate for phase 24; no tag yet. Check in and stop.

### Phase 24 — Verify the exact final commit and conditionally tag

**Owner:** `gpt-5.6-terra`, medium. **Depends on:** 23 plus external evidence when available.

1. Run the strengthened release verifier and complete required Windows checks in a clean isolated checkout of the exact documentation commit. Store generated artifacts outside it.
2. Obtain actual Linux CI results for that same commit, including raw required evidence and package checks. Local workflow preparation, an older green run, or a merge commit with a different SHA does not count.
3. Recompute all required engineering gates and validate both platform source identities. If Linux or another external prerequisite is unavailable, finish local work, report the exact missing artifact/check, leave release completion and the tag unset, and stop. Do not push to obtain CI without explicit authorization.
4. Only when all required platform evidence exists and implementation-session authorization permits release tagging, create annotated `v0.1.0` pointing to that exact commit. Inspect an existing tag first; never replace or move it silently. Record evidence references in the tag annotation/external attestation.
5. Do not modify the candidate after verification. A subsequent source/docs change requires a new exact candidate and rerun; never attach old evidence to it. Do not commit a tracker update after tagging and pretend it is part of the tagged candidate.
6. Do not push, publish, spend money, integrate Codex OAuth, or rename a remote. Completion of offline gates does not certify live economics.

**Acceptance:** exact-commit Windows and Linux evidence either both pass and support the authorized tag, or the precise external blocker is reported with tag/completion unset. This phase does not require an extra source commit after the frozen documentation commit.

## 8. Separately authorized follow-on tracks

### Q1 — Live economic qualification and production promotion

**Owner:** Terra for tooling/runs; Sol only for a bounded review if methodology changes. **Start only with:** explicit provider-spend authorization, hard cap, selected provider access, and frozen evaluation protocol. Subscription access used to implement Rudder is not authorization to run paid evaluations inside Rudder.

- Build toward at least 1,000 diverse held-out requests across repositories, languages, scope, coupling, and verification types. Use repository/task-family splits and repeated stochastic runs; keep calibration and qualification sets separate.
- Compare capable and inexpensive fixed direct baselines, fixed-model orchestration, current conservative auto, and proposed qualified strategies with the same useful tools and work. Record all failures and actual provider usage, including reasoning/cache/tool charges where applicable.
- Use independent executable or adjudicated outcomes. Agent self-reports and passing self-written tests alone are insufficient for a general quality claim. Analysis/design tasks need a documented independent scoring rubric.
- Require no lower observed completion than the capable direct baseline and a preregistered paired 95% confidence interval excluding a loss greater than one percentage point. The one-point statistical tolerance is not a policy to deliberately reduce quality. Require at least 20% lower aggregate cost per successful request and at least 15% median improvement on the predefined parallel-eligible stratum, with no new safety/workspace defects.
- Use repository-clustered paired resampling for uncertainty, retain raw runs and evaluator judgments, and report important workload strata so aggregate improvements cannot hide a major regression. Insufficient precision means unqualified; never stop sampling opportunistically at the first favorable result. Any extension requires a newly recorded budget/protocol decision.
- Validate model/harness/evidence revisions and approve policy artifacts only for demonstrated workload classes. Activate at new-run boundaries; existing attempts stay fixed. Unknown classes remain on the baseline. Use local observation for drift detection, never unreviewed promotion.
- End-to-end qualification failure keeps the new economic policy in shadow/experimental mode. Publish no broad savings claim until evidence supports it. No telemetry upload or data-sharing is implied.

### C1 — Optional legacy removal

**Owner:** Luna for a verified mechanical manifest; Terra for dependency questions. **Start only with:** explicit cleanup authorization after the release/preservation checks.

- Resolve and inspect the preservation tag/reference. Demonstrate that the archive is recoverable before deleting anything.
- Verify no runtime, packaging, tests, scripts, or documentation commands depend on the archive. Identify exact deletion targets within `legacy/autoconduck/` and review the manifest.
- Perform removal only as a separate cleanup commit. Never combine it with v0.1.0 candidate verification, move an existing release tag, or erase unrelated user data.
- Run boundary/package tests and Graphify, and state what was removed and how it can be recovered. If the cleanup changes released content, qualify a later release independently.

## 9. Copyable phase-start prompt

```text
Implement only phase <PHASE_ID> from:
  tasks/rudder-adaptive-orchestration-and-release-plan.md
in C:\Users\plum\Documents\Works\Rudder on branch rudder.

Use the phase's assigned model if available through my existing access. Read the guide's
common contract, architecture contract, phase dependencies, and applicable AGENTS/ADR/spec
sections. Query Graphify before unfamiliar exploration. Verify actual runtime behavior;
tracker checkboxes and commit titles are not proof.

Preserve all unrelated changes, especially .gitignore and the four evals/results/run_1/run_2
JSON/Markdown files. Do not stage them. Use PowerShell, rtk, and apply_patch as instructed.
Use offline deterministic fixtures. Do not spend money, use live providers, integrate Codex
OAuth, push, publish, rename remotes, delete legacy, or create a release tag in this phase
unless this is the relevant explicitly authorized final phase and all prerequisites hold.

Implement the bounded phase, run its focused/affected/common checks, update Graphify, review
the full diff, and commit explicit phase paths. Fix any failures within scope. Report the
commit, tests, remaining limitations, and next phase, then check in and stop. If blocked by
external evidence, finish all independent local work and identify exactly what is missing.
Do not continue to the next phase automatically.
```

### Required phase handoff record

```text
Phase:
Status: complete / incomplete / externally blocked
Implementation model:
Commit(s):
Behavior delivered:
Acceptance evidence and commands:
Test results and documented skips:
Review findings closed/open:
External evidence location and source identity, if applicable:
Protected/unrelated files preserved:
Unproven claims or missing evidence:
Next phase and its dependencies:
```

### Phase 00 handoff

```text
Phase: 00 — Lock the successor architecture and release boundaries
Status: complete
Implementation model: GPT-6 Codex (assigned Sol treated as a recommendation)
Commit(s): phase commit; resolve from Git history by the required commit subject
Behavior delivered: ADR 0006 accepts adaptive typed plans, task compatibility, isolated-writer and schema ownership contracts, model stickiness, outcome qualification, and separate engineering/economic release boundaries. Active and historical trackers are reconciled. The active guide and its copyable phase-start prompt name the canonical `Rudder` workspace; intentional AutoConduck legacy and migration references remain unchanged.
Acceptance evidence and commands: `rtk pytest tests\unit\test_documentation_contracts.py -q`; `rtk pytest`; `python -m ruff check src tests scripts evals benchmarks`; `python -m mypy src\rudder`; targeted content/link review; `graphify update .`; `rtk git diff --check`; complete diff review
Test results and documented skips: documentation contracts 2 passed; complete offline suite 502 passed and 2 skipped; Ruff and mypy passed. The suite's two existing skips remain documented by pytest. Live providers, paid evaluation, platform release evidence, tagging, pushing, publishing, remote rename, and legacy cleanup were out of scope
Review findings closed/open: conflicting static-DAG, five-point quality-loss, tracker-authority, and tag/remote instructions closed; no Phase 00 finding remains open
External evidence location and source identity, if applicable: none required for this documentation/contracts phase
Protected/unrelated files preserved: .gitignore and evals/results/run_1.json, run_1.md, run_2.json, run_2.md excluded from phase staging
Unproven claims or missing evidence: economic qualification remains unproven until separately authorized Q1 evidence exists
Next phase and its dependencies: Phase 01 — Fix the routing boundary before changing the policy; depends on completed Phase 00
```

### Phase 01a handoff

```text
Phase: 01a — Preserve validated requirements through controller assignment
Status: complete
Implementation model: GPT-6 Codex (assigned Terra treated as a recommendation)
Commit(s): phase commit; resolve from Git history by the required commit subject
Behavior delivered: Assignment derivation reuses validated task requirements for batch and retry paths, including hard compatibility requirements and exclusions. Lead routing derives profile-required tool and structured-output requirements.
Acceptance evidence and commands: `rtk pytest tests\unit\test_requirements.py tests\unit\test_selector.py tests\integration\test_assignment.py tests\integration\test_lead.py -q`; `rtk pytest`; `python -m ruff check src tests scripts evals benchmarks`; `python -m mypy src\rudder`; `graphify update .`; `rtk git diff --check`; complete diff review
Test results and documented skips: focused routing/controller suite 49 passed; complete offline suite 504 passed and 2 skipped; Ruff and mypy passed. The suite's two existing skips remain documented by pytest
Review findings closed/open: controller requirement loss closed. Packet-aware estimation and manual unknown-price behavior remain open in Phase 01b.
External evidence location and source identity, if applicable: none required; all fixtures are offline and deterministic
Protected/unrelated files preserved: .gitignore and evals/results/run_1.json, run_1.md, run_2.json, run_2.md excluded from phase staging
Unproven claims or missing evidence: Phase 01 remains incomplete until Phase 01b supplies actual-packet estimate and manual unknown-price evidence
Next phase and its dependencies: Phase 01b — Estimate actual task packets and preserve manual unknowns; depends on Phase 01a
```

### Phase 01b handoff

```text
Phase: 01b — Estimate actual task packets and preserve manual unknowns
Status: complete
Implementation model: GPT-6 Codex (assigned Terra treated as a recommendation)
Commit(s): phase commit; resolve from Git history by the required commit subject
Behavior delivered: Lead, compatibility-task batch, and retry candidate snapshots are estimated from a deterministic assembled preflight packet, profile-specific expected-call priors, declared tool-result allowance, output requirements, and zero cache reuse. Unknown manual price remains explicit and cannot be reserved as zero.
Acceptance evidence and commands: `rtk pytest tests\unit\test_estimates.py tests\unit\test_selector.py tests\integration\test_assignment.py tests\integration\test_lead.py -q`; `rtk pytest`; `python -m ruff check src tests scripts evals benchmarks`; `python -m mypy src\rudder`; `graphify update .`; `rtk git diff --check`; complete diff review
Test results and documented skips: focused routing/controller suite 41 passed; complete offline suite 506 passed and 2 skipped; Ruff and mypy passed. The suite's two existing skips remain documented by pytest
Review findings closed/open: bootstrap-sized runtime estimates replaced; manual unknown-price reservation remains correctly blocked rather than treated as zero. No Phase 01 finding remains open.
External evidence location and source identity, if applicable: none required; all fixtures are offline and deterministic
Protected/unrelated files preserved: .gitignore and evals/results/run_1.json, run_1.md, run_2.json, run_2.md excluded from phase staging
Unproven claims or missing evidence: observed workload estimates remain priors until later evaluation phases; no economic strategy promotion claim is made
Next phase and its dependencies: Phase 02 — One post-commit event delivery path; depends on completed Phase 01
```

### Phase 02 handoff

```text
Phase: 02 — One post-commit event delivery path
Status: complete
Implementation model: GPT-6 Codex (assigned Terra treated as a recommendation)
Commit(s): phase commit; resolve from Git history by the required commit subject
Behavior delivered: A journal-backed EventBus is the controller and assignment delivery path. Events notify only after the outer transaction commits; nested transactions use savepoints; rollback drops callbacks. Durable cursor replay reads committed events, failed subscribers are isolated, and TUI projections deduplicate replayed event IDs.
Acceptance evidence and commands: `rtk pytest tests\unit\test_event_bus.py tests\unit\test_tui_projection.py tests\integration\test_lead.py tests\integration\test_assignment.py -q`; `rtk pytest`; `python -m ruff check src tests scripts evals benchmarks`; `python -m mypy src\rudder`; `python scripts\smoke.py --fake-provider`; `graphify update .`; `rtk git diff --check`; complete diff review
Test results and documented skips: focused event/journal/projection/controller suite 41 passed; complete offline suite 510 passed and 2 skipped; Ruff, mypy, and fake-provider smoke passed. The suite's two existing skips remain documented by pytest
Review findings closed/open: early observer capture and direct unshared delivery closed. Phase 03 remains responsible for terminal invocation events and CLI exit behavior.
External evidence location and source identity, if applicable: none required; all fixtures are offline and deterministic
Protected/unrelated files preserved: .gitignore and evals/results/run_1.json, run_1.md, run_2.json, run_2.md excluded from phase staging
Unproven claims or missing evidence: delivery is at-least-once to observers; consumers deduplicate by event ID. Terminal invocation contract remains Phase 03 work
Next phase and its dependencies: Phase 03 — Terminal events, exit codes, and isolated CLI tests; depends on completed Phase 02
```

### Phase 03a handoff

```text
Phase: 03a — Atomically commit terminal failure and cancellation events
Status: complete
Implementation model: GPT-5 Codex (assigned Luna treated as a recommendation)
Commit(s): resolve from Git history by the phase-owned commit subject
Behavior delivered: Initial and resumed controller exception paths now update terminal run/task/attempt/session state and append the corresponding run.failed or run.cancelled event in one journal transaction. Post-commit subscribers therefore observe terminal state consistently.
Acceptance evidence and commands: `rtk pytest tests\integration\test_lead.py -k terminal_failure_event_observes_committed_failed_run -q`; affected event/controller suite; `python -m ruff check src tests scripts evals benchmarks`; `python -m mypy src\rudder`; `graphify update .`; `rtk git diff --check`; complete diff review
Test results and documented skips: regression passed. The deterministic no-response fake causes the existing provider-usage uncertainty exception after terminal state is committed; that behavior is preserved and is asserted by the test. Full affected verification follows below.
Review findings closed/open: terminal event-before-state ordering closed for initial and resumed controller exception paths. CLI invocation identity, terminal output uniqueness, exit behavior, and subprocess isolation remain open in Phase 03b.
External evidence location and source identity, if applicable: none required; all fixtures are offline and deterministic
Protected/unrelated files preserved: `.gitignore` and `evals/results/run_1.json`, `run_1.md`, `run_2.json`, `run_2.md` excluded from phase staging
Unproven claims or missing evidence: Phase 03 parent remains incomplete; this slice does not certify the CLI contract or release readiness.
Next phase and its dependencies: Phase 03b — CLI invocation, terminal output, exit codes, and isolated tests; depends on Phase 03a
```

### Phase 03b handoff

```text
Phase: 03b — CLI invocation, terminal output, exit codes, and isolated tests
Status: complete
Implementation model: GPT-5 Codex (assigned Luna treated as a recommendation)
Commit(s): resolve from Git history by the phase-owned commit subject
Behavior delivered: Each CLI execution carries one invocation_id distinct from its resumable run_id, including route and budget events. JSONL preserves one terminal event as the final envelope for completed and blocked persisted runs; pre-persistence failures do not fabricate terminal events. Print/JSONL output separation and temporary-home subprocess isolation are covered by end-to-end tests.
Acceptance evidence and commands: `rtk pytest tests\e2e\test_cli_e2e.py -q`; `rtk pytest tests\unit\test_event_bus.py tests\unit\test_events.py tests\unit\test_tui_projection.py tests\integration\test_assignment.py tests\integration\test_lead.py tests\integration\test_recovery.py tests\integration\test_tui_shell.py tests\integration\test_tui_commands.py tests\e2e\test_cli_e2e.py -q`; `rtk pytest -q`; `python -m ruff check src tests scripts evals benchmarks`; `python -m mypy src\rudder`; `python scripts\smoke.py --fake-provider`; `graphify update .`; `rtk git diff --check`; complete diff review
Test results and documented skips: CLI suite 18 passed; affected suite 115 passed; full offline suite 514 passed and 2 skipped; Ruff, mypy, fake-provider smoke, Graphify, and diff checks passed. The two existing pytest skips remain documented.
Review findings closed/open: invocation propagation through controller and assignment-generated events, terminal uniqueness, documented output separation, and temporary-home isolation closed. No Phase 03 finding remains open.
External evidence location and source identity, if applicable: none required; all fixtures are offline and deterministic
Protected/unrelated files preserved: `.gitignore` and `evals/results/run_1.json`, `run_1.md`, `run_2.json`, `run_2.md` excluded from phase staging
Unproven claims or missing evidence: this phase does not certify release readiness, cross-platform packaging, or live-provider quality/economic qualification.
Next phase and its dependencies: Phase 04 — Make evaluation execution independent of its oracle; depends on completed Phase 03
```

### Phase 04 handoff

```text
Phase: 04 — Make evaluation execution independent of its oracle
Status: complete
Implementation model: GPT-5 Codex (assigned Terra treated as a recommendation)
Commit(s): phase commit; resolve from Git history by the required commit subject
Behavior delivered: Evaluation fixtures may carry an explicit execution script whose model responses, tool calls, and reported usage are independent of the scoring oracle. The runner persists immutable raw execution records before scoring and summaries, and a missing script yields an incomplete execution rather than a passing result. Disabling runtime writes correctly fails required mutation fixtures.
Acceptance evidence and commands: `rtk pytest tests\unit\test_eval_runner.py -q`; `rtk pytest tests\contract\test_eval_fixtures.py tests\unit\test_release_check.py tests\unit\test_eval_runner.py -q`; `python scripts\eval_routing.py --policies auto --seed 42`; full offline suite, Ruff, mypy, fake-provider smoke, Graphify, diff check, and complete diff review
Test results and documented skips: focused evaluator suite and affected fixture/release suite pass. The sample evaluator runs deterministically but exits 1 because its unqualified cost and parallel gates remain intentionally unmet. Live providers and paid evaluation remain out of scope. Existing fixtures without execution scripts remain loadable but incomplete until Phase 05 independently rebuilds and approves them.
Review findings closed/open: oracle-derived execution and estimate-derived fake usage are closed. Independent 50-fixture curation, approval, and measurement remain Phase 05 work.
External evidence location and source identity, if applicable: raw execution records are embedded in the offline evaluation report; no external evidence is required for this phase.
Protected/unrelated files preserved: .gitignore and evals/results/run_1.json, run_1.md, run_2.json, run_2.md excluded from phase staging
Unproven claims or missing evidence: deterministic fake usage is not provider billing evidence; no quality, savings, timing, or release-readiness claim is made.
Next phase and its dependencies: Phase 05 — Curate independent offline workloads; depends on completed Phase 04
```

### Phase 05 handoff

```text
Phase: 05 — Curate independent offline workloads
Status: complete
Implementation model: Antigravity (assigned Gemini Flash treated as a recommendation)
Commit(s): phase commit; resolve from Git history by the required commit subject
Behavior delivered: Curated 54 distinct approved offline fixtures across 7 workload categories (trivial, routine, bounded, complex, high-risk, parallel with multi-turn task delegation, failure contract checks) with independent scripted model execution and private oracles. Manifest v1.1.0 freezes all 54 fixtures with explicit approval, synthetic_offline evidence class, and SHA-256 digests. Contract tests verify oracle isolation, category balance, role and platform coverage, adversarial oracle mutations, workspace resets, boundary containment, and file write suppression.
Acceptance evidence and commands: `rtk pytest tests\contract\test_eval_fixtures.py tests\unit\test_eval_runner.py tests\unit\test_release_check.py -q`; `rtk pytest -q`; `python -m ruff check src tests scripts evals benchmarks`; `python -m mypy src\rudder`; `python scripts\smoke.py --fake-provider`; `graphify update .`; `rtk git diff --check`; complete diff review
Test results and documented skips: contract fixtures suite 10 passed; evaluator suite 13 passed; release check 2 passed; full offline suite 525 passed and 2 skipped; Ruff, mypy, fake-provider smoke, Graphify, and git diff checks all passed with zero errors. The two documented skips in pytest remain documented.
Review findings closed/open: oracle access from fake/model/script closed; unapproved and duplicate fixtures closed; all 54 fixtures have explicit intended work, scoring meaning, independent usage, and frozen sha256 digests. No Phase 05 finding remains open.
External evidence location and source identity, if applicable: evals/manifest.toml with sha256 digests of all 7 fixture files; all fixtures are offline and synthetic.
Protected/unrelated files preserved: .gitignore and evals/results/run_1.json, run_1.md, run_2.json, run_2.md excluded from phase staging.
Unproven claims or missing evidence: offline fixtures do not constitute live provider performance or economic parity; Phase 06 plan state and subsequent runtime phases remain future work.
Next phase and its dependencies: Phase 06 — Persist plans and their legal transitions; depends on completed Phase 05
```

## 10. Definition of completion

- Numbered implementation phases are complete only with their recorded checks and phase handoffs.
- Engineering release readiness requires raw-evidence verification and exact-commit Windows/Linux results, not synthetic summaries alone.
- Live quality/cost parity remains unproven until Q1 passes. Neither completion of this document nor a v0.1.0 engineering tag changes that fact.
- Core-feature gaps remain explicit in the separate roadmap; "all mainstream features" is not an untestable release checkbox.
- Missing CI or live evidence is reported precisely; no tag, checkmark, or marketing statement substitutes for it.
