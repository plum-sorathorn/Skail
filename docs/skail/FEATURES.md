# Skail Feature Contracts

> Status note: these are normative behavior contracts. A section is not an assertion that every
> integration has production parity; tested scope and demonstrated gaps are recorded in the
> [feature matrix](FEATURE_PARITY_ROADMAP.md).

Status: Approved
Date: 2026-09-02
Depends on: [SPEC.md](./SPEC.md), [ARCHITECTURE.md](./ARCHITECTURE.md)

This document defines how each Skail Harness product feature behaves from trigger to terminal result. It is intentionally more operational than a conventional feature list.

## 1. Conversation-first harness

### Purpose

Let the user start productive work with `skail` and a prompt, without starting a proxy, selecting an orchestration graph, or attaching Skail to another harness.

### Trigger and flow

1. `skail` resolves configuration, workspace, project trust, and session choice.
2. It validates that at least one usable lead model is available.
3. With an inline prompt, it submits immediately; without one, it opens the interactive TUI.
4. The run controller assigns the lead model, records the run, and invokes the lead graph.
5. Model, tool, task, approval, and budget events stream through one event channel.
6. The final answer and run outcome are checkpointed before control returns to the prompt.

### Invariants

- No local server or background daemon is required.
- A provider error is visible and actionable; it is not disguised as a successful empty answer.
- Print mode writes only the final answer to stdout so it composes in scripts.
- JSON mode emits versioned JSONL events and never mixes human formatting into stdout.

### Edge cases

- Non-interactive execution that needs user approval exits with a stable code and an approval-required event unless an explicit non-interactive policy was supplied.
- An empty prompt in print mode is a usage error.
- A second Skail process may read other sessions but must not concurrently mutate a session owned by a live process.

## 2. Capable lead agent

### Purpose

Keep Skail useful for simple work and resilient when delegation is unnecessary or unsuccessful.

### Behavior

The lead gets the full default coding tool set under the active safety policy. It owns the user-facing outcome and may inspect, edit, execute, ask questions, create todos, delegate, synthesize, and verify.

Its first necessary response may finish directly or record a typed `direct`, `discover`, or
`planned` decision. Direct work keeps the capable tool loop. Discovery schedules a bounded evidence
frontier and checkpoint. A validated plan releases ready dependencies without asking the lead to
select every batch. A scoped question may precede the decision when intent or authority is missing.
At a ready discovery checkpoint, Skail wakes the same lead assignment with the current plan and
bounded prerequisite evidence. The lead uses `execution_decision` again with the complete revised
plan and typed revision metadata; unavailable evidence or a failed revision compare-and-set cannot
release downstream work.

Its prompt defines delegation heuristics, but the runtime enforces user directives:

- `delegation=off`: the `task` tool is hidden or rejects calls before scheduling;
- `delegation=ask`: proposed tasks require user confirmation before launch;
- `delegation=auto`: valid tasks launch within concurrency, safety, and budget gates;
- explicit “do this yourself” applies to that instruction even when the configured default is `auto`;
- explicit “use N agents” is honored up to configured and hard limits, or Skail explains the conflict.

### Direct-versus-delegate heuristic

The lead normally delegates only when expected value exceeds overhead. Useful signals are independent parallel work, specialist posture, context isolation, and independent verification. A localized serial edit is normally direct work. This heuristic is not a separate SLM classifier and has no authority over permissions.

### Terminal responsibility

The lead must not paste child results blindly. It checks success criteria, resolves conflicts, runs or reviews final verification, and communicates remaining uncertainty. A child `succeeded` status is evidence, not proof of the entire user request.

## 3. Todo planning versus executable tasks

### Purpose

Avoid conflating a conversational checklist with work actually scheduled on an agent.

### Contracts

- `write_todos` manages lead planning items: `pending`, `in_progress`, `completed`.
- `task` creates a task request which Skail validates and registers.
- The task registry owns executable states, assignments, attempts, budgets, and results.
- A todo may reference a task ID, but neither state system silently mutates the other.
- An `ExecutionPlan` is a separate versioned domain contract; todo prose never becomes executable.

### Display

`/tasks` presents two sections: planning todos and executing/delegated tasks. This prevents “planned” from being mistaken for “running.”

## 4. Automatic delegation

### Purpose

Turn a normal user prompt into bounded parallel or specialized work without requiring the user to describe an orchestration strategy.

The lead may use the standard `task` call for one task or submit a finite typed plan. Both enter one
Skail-owned plan service and share validation, assignment, budget, lifecycle, events, and recovery.

### Task request fields

The lead supplies a description, profile, success criteria, dependencies, requested write scope, optional model constraint, optional budget, and foreground/background preference.

### Validation logic

Skail rejects or blocks a request when:

- description is empty or exceeds the bounded handoff size;
- profile does not exist;
- parent depth reaches the configured maximum;
- dependencies are missing, cyclic, or terminally unsuccessful;
- requested tools exceed the profile or user policy;
- requested write paths escape the workspace;
- the same failed fingerprint has exhausted automatic retry;
- background execution is requested but not enabled.

Valid requests receive Skail-generated IDs and requirements. The model cannot self-assign authority, a larger budget, or extra concurrency by placing it in task text.

Plans use local names and declare dependencies, acceptance criteria, output contracts, effects,
resource scopes, and decision checkpoints. Admission allocates persistent IDs atomically and rejects
cycles, missing references, duplicate objectives, invalid scopes, and unauthorized effects. A
revision identifies its expected predecessor; completed nodes retain identity and retry history.

### Result logic

The lead receives a compact result containing status, summary, artifacts, changed paths, verification, both attempt summaries when applicable, and a recommended follow-up. Full child transcripts stay outside the lead context unless requested.

## 5. Built-in agent profiles

### Shared profile mechanics

Every profile declares:

- stable name and description shown to the lead;
- prompt fragment;
- allowed built-in and extension tools;
- read/write/execute posture;
- role floor and hard minimum capability;
- default success-result schema;
- whether child delegation is allowed;
- optional expected-call-count used for cost estimation.

Profiles never hardcode a commercial model. Routing assigns the model per task.

### Lead

Function: own the user request, choose direct work or delegation, synthesize, and verify.

Rules:

- receives a higher initial capability floor;
- can use all default tools under policy;
- is the only profile allowed to delegate by default;
- reserves enough budget to process child results;
- must explain blocked or returned tasks rather than loop automatically.

### General-purpose

Function: handle bounded delegated work that does not need a specialist posture.

Rules:

- gets filesystem, execution, skills, and memory support;
- is write-capable and therefore uses a write lease;
- returns changed paths and verification, not a conversational essay.

### Explorer

Function: locate code, trace dependencies, and answer architectural questions without modifying the workspace.

Rules:

- gets list/search/read tools;
- no execution by default, unless a read-only command policy is later proven enforceable;
- returns evidence with file/symbol references and explicit unknowns;
- uses the lowest built-in role floor.

### Implementer

Function: make a bounded code change and run focused verification.

Rules:

- gets filesystem edit and execution tools;
- requires a shared-workspace write lease or worktree;
- must preserve user changes and report touched paths;
- success requires the requested change plus relevant verification evidence.

### Tester

Function: construct or run tests, reproduce failures, and interpret results.

Rules:

- gets filesystem reads and execution;
- is classified write-capable because test runners and shell commands may write;
- cannot claim success from a zero exit code if required assertions were skipped;
- distinguishes environment failure from product failure.

### Reviewer

Function: provide an independent correctness, security, compatibility, and maintainability review.

Rules:

- cannot edit through built-in filesystem tools;
- execution, if enabled, still requires an exclusive lease;
- returns findings ordered by severity with evidence and verification gaps;
- “no findings” must state what was actually inspected and tested.

### Researcher

Function: research external or local documentation and return source-grounded conclusions.

Rules:

- gets read tools and optional web/MCP tools;
- is read-only;
- separates sourced facts from inference;
- returns citations or local references without flooding lead context.

## 6. User-defined profiles

### Locations and precedence

1. Trusted project `.skail/agents/<name>/AGENTS.md`.
2. User `~/.skail/agents/<name>/AGENTS.md`.
3. Built-in profile of the same name.

Project definitions only override after trust. Duplicate names at one level are an error.

### Loading

Frontmatter is parsed and schema-validated before prompt content is loaded. Unknown tools, invalid model constraints, excessive delegation depth, or broader-than-user permissions fail the profile with a diagnostic; they do not weaken policy.

### Delegation

User profiles may request child delegation, but the global maximum depth and concurrency still apply. The stable default is depth one. Built-ins other than lead do not delegate.

### Reload

Profile changes apply to future task creation. Running tasks retain the profile revision recorded at assignment time. `/config` or `/agents` shows the source and revision.

## 7. Task-bound model routing

### Purpose

Use models economically without changing a task's identity or behavior in the middle of a healthy attempt.

### Requirement derivation

Before selection, `RequirementBuilder` combines:

- profile role and hard minimum;
- lead-estimated task risk constrained to an enum;
- actual tool and structured-output needs;
- prompt plus relevant workspace context estimate;
- input modalities;
- explicit user provider/model allow or deny rules;
- routing mode;
- attempt number and previously failed model;
- remaining task and run budgets.

The lead may describe task risk, but cannot reduce a profile hard minimum or lie about required tools.

### Automatic model eligibility

A model is automatically eligible only if its compatibility and capability evidence is trusted. Unknown models remain manually usable. Skail must never infer quality from model name, vendor reputation, price, or parameter-count text.

### Assignment result

The route decision records:

- chosen provider/model and catalog revision;
- effective floor and capability fit;
- estimated attempt cost;
- included and excluded candidate counts by reason;
- binding hard constraint;
- ranking reasons;
- user overrides;
- reservation ID.

`/route` renders this record; it does not recompute a possibly different answer.

### Model stickiness

Every model call in the attempt uses the assignment in graph state. The provider/model may change only through a recorded transport fallback or task escalation, both of which create new assignment IDs.

## 8. Routing modes and overrides

### `auto`

Use the lowest expected-total-spend strategy among quality-qualified choices. In cold-start, stale,
or unsupported workload classes, use the recorded conservative baseline and expose why. New cheaper
strategies remain shadow or experimental until an approved paired evaluation qualifies them.

### `economy`

Lower the soft floor by one band while preserving hard role/tool/context/modality requirements. If no cheaper qualified candidate exists, the result may match `auto`.

### `quality`

Prefer capability fit and tool reliability within a hard budget. Quality mode does not override a user budget.

### `manual`

Validate and use the exact model. If it cannot satisfy a required capability, return a conflict. Do not silently substitute.

### Override scopes

- CLI/session mode applies to future assignments.
- `--lead-model` pins only lead runs.
- `--agent-model profile=model` constrains tasks for that profile.
- An explicit instruction can constrain a specific task.
- Existing active attempts never change when a future-assignment setting changes.

## 9. Model catalog and evidence

### Sources

- maintained Skail catalog entries;
- provider model discovery;
- trusted user overrides;
- replayable Skail evaluations;
- provider pricing/capability metadata where authoritative.

### Merge order

User overrides > evaluated Skail evidence > maintained entries > discovered metadata. A higher source may fill or explicitly replace fields, and provenance is retained per field.

### Freshness

Profiles include an as-of timestamp. Stale price data warns and may disqualify a candidate from a hard-budget route. Stale capability data does not mutate automatically; it queues evaluation or requires manual selection.

### Local outcomes

Early provider failures influence health and fallback, not global capability. Skail does not learn a model-quality score from a handful of private sessions in the first release.

## 10. Provider support

### Provider resolution

Configuration names a provider adapter and credential alias. `ModelFactory` resolves the installed LangChain integration, creates the model with normalized options, and caches only safe immutable client configuration—not per-run state.

### Support levels

The models UI reports separately whether a provider/model is:

- constructible;
- contract-tested;
- auto-routing eligible;
- covered in maintained CI.

### LLM Gateway

LLM Gateway is first-class. Skail uses its OpenAI-compatible `/v1` endpoint, model discovery when available, and normalizes streaming tool calls and usage through a dedicated adapter. The adapter is contract-tested instead of assuming every OpenAI extension behaves identically.

### DevPass

DevPass is retained through the same explicit OpenAI-compatible adapter shape and its own base URL/configuration. It does not share hardcoded credentials or catalog identity with LLM Gateway.

### Other providers

Any compatible LangChain model may be manually configured. Automatic routing additionally requires evidence and normalized pricing. Provider-specific dependencies should be optional extras so broad compatibility does not make the core install heavy.

## 11. Cost estimation and hard budgets

### Attempt estimate

```text
estimated_input = current_task_context + expected_tool_result_allowance
estimated_output = profile_output_allowance
estimated_calls = profile_expected_calls adjusted by task risk
estimated_attempt_cost = price(estimated_input, estimated_output) * estimated_calls
```

The estimate is deliberately conservative and its inputs are visible in `/budget` or `/route`.

### Reservation

Selection and reservation are one logical operation. A chosen model is not launched if another concurrent task consumed the remaining budget first.

### Lead allowance

Before a child batch starts, Skail retains enough budget for at least one lead synthesis call on the assigned lead model. If this cannot be retained, fan-out is reduced or blocked. Skail must not spend the full budget on children and strand the user without a final answer.

### Warnings and blocks

- At the warning threshold, emit one warning per threshold crossing.
- A denied reservation returns `budget_blocked` with cheaper qualified choices if any.
- User budget increases affect future gates; they do not rewrite recorded estimates.
- Provider-reported usage replaces the matching estimate when possible and is labelled authoritative.

## 12. Concurrency and scheduling

### Child limit

The user chooses 1, 2, or 3. The default and hard maximum are 3. The lead is not counted as a child slot but is subject to the write lease.

### Dependencies

Tasks launch only after every dependency succeeds. A failed, blocked, or cancelled dependency produces a dependency-blocked result unless the lead creates a new independent task.

### Shared-workspace mode

- read-only children may overlap;
- any child with execute/edit/write/custom-unknown tools is write-capable;
- only one write-capable participant holds the workspace lease;
- the lead waits before write-capable tool use while the lease is held;
- queued work remains visible and cancellable.

### Worktree mode

Worktree isolation may allow non-overlapping writer tasks. Each worker starts from a recorded
canonical snapshot and returns a content-addressed change set with verification evidence. One
serialized integration owner checks stale inputs, conflicts, scope, and verification. Non-Git or
unsafe repositories fall back to serialized shared mode without discarding user changes.

### Fairness

Within a run, ready tasks use lead-supplied priority and creation order. A newly proposed task does not jump ahead of an older equal-priority task. Approval waits do not consume a child execution slot, but their reserved budget remains held until timeout/cancellation.

## 13. Failure classification

### Non-terminal tool errors

One failed command, edit, or lookup is sent back to the agent normally. It becomes an attempt failure only through a terminal structured result, exhausted provider policy, deterministic stagnation, verification failure, or attempt boundary.

### Deterministic stagnation

Initial triggers:

- three identical consecutive tool calls;
- two consecutive tool errors;
- same normalized error twice;
- exhausted configured model-call/time/budget boundary.

Tool arguments are normalized without secrets. Semantically different searches or a corrected retry do not count as identical.

### Provider failures

- authentication and invalid-model errors fail routing/assignment and require configuration action;
- rate limit/outage may use a configured equivalent transport fallback;
- malformed tool or structured responses count against provider execution policy;
- provider fallback before meaningful execution does not consume task escalation.

### Verification failure

When success criteria require a test/build/check, a failing or skipped required check prevents `succeeded`. Environment inability is returned distinctly so the lead can ask for authority or explain uncertainty.

## 14. Escalate once, then return

### First failed attempt

Skail:

1. closes the attempt and settles usage;
2. preserves the worktree/shared changes;
3. records evidence and failed model;
4. checks remaining budget and candidates;
5. excludes the failed model and raises the floor by 0.15;
6. creates attempt two with a concise handoff.

The stronger model continues from the existing workspace state. Skail does not automatically erase partial work.

### Second failed attempt

Skail marks `returned_to_lead` and supplies both summaries. The lead may repair directly, materially re-scope, or ask the user. The same task cannot be automatically submitted for attempt three.

### Blocked work

Permission denial, missing authority, unsupported background mode, or an unaffordable escalation is `blocked`/`budget_blocked`, not a failure of model competence. These states do not automatically consume escalation.

## 15. Tool assembly

### Default tools

Skail adopts useful DeepAgents tools: list, glob, grep, read, write, edit, execute, todos, subagents, skills, and memory, plus Skail's user-question tool.

### Tool registry

For every tool, the registry records:

- stable name and description;
- implementation source and version;
- schema;
- side-effect posture: read-only, workspace-write, external-write, unknown;
- path/network/credential requirements;
- profile allow list;
- approval policy.

Name collisions are configuration errors. Project tools cannot shadow built-ins unless the user explicitly approves the exact override.

### Output control

Large tool outputs are stored as artifacts and represented in model context by a bounded excerpt plus reference. Truncation is explicit; the agent can request another range. Secrets are redacted before either storage or context injection.

## 16. Filesystem safety

### Path resolution

All model-provided paths are virtual workspace paths. The backend resolves them against the canonical workspace root, follows safe normalization, and rejects traversal, symlink, or junction escape.

### Read policy

Default: allow workspace reads, subject to configured sensitive-file patterns. Reading outside the workspace requires an explicit user-approved path grant.

### Write policy

Default: allow writes inside the trusted workspace after normal harness approval policy. Sensitive paths, VCS metadata, credential files, and outside-workspace targets require stronger handling or rejection.

### Changed-file accounting

Every successful write/edit records canonical path, task, tool call, and before/after content hash. The journal need not store full file contents.

## 17. Command execution and approval

### Shell selection

- Windows uses PowerShell with the workspace as the default working directory.
- Linux uses the configured POSIX shell.
- Shell, command, arguments, and working directory are recorded separately where the backend exposes them.

### Policy evaluation

The execution wrapper categorizes a command as ordinary read/build/test, workspace mutation, network/external side effect, privilege request, destructive/high risk, or unknown.

Default policy:

- ordinary workspace build/test/read commands: allow under trusted project policy;
- ordinary workspace edits through shell: follow write policy and lease;
- external messages, publishing, deployment, privilege, destructive actions, and outside-workspace writes: ask or reject;
- unknown: ask.

### Approval response

The user may allow once, allow for session, create a narrow project rule, edit the proposed action, or reject. An edited action creates a new tool request; the original is never reported as executed.

### Non-interactive mode

The caller must provide an approval policy. Otherwise an interrupt yields a structured approval-required exit rather than hanging.

## 18. Project trust

### Initial detection

On first use of a canonical workspace containing Skail project configuration/extensions, the TUI summarizes requested capabilities before asking for trust. Merely opening the workspace does not execute project code.

### Trust levels

- `untrusted`: ignore executable/project-defined extensions and approval rules;
- `trusted`: load validated project configuration within user policy;
- `denied`: remember refusal and do not prompt again until explicitly changed.

Trust never overrides global prohibited actions or filesystem boundaries.

### Revocation

Revoking trust affects future tool/profile loads. Active project-defined tasks are cancelled before their next tool call and return a trust-revoked result.

## 19. Skills and memory

### Skills

Built-in and user skills are exposed through DeepAgents' skills mechanism. Project skills require trust. A selected skill is loaded into the relevant agent context and its source/revision is recorded.

### Memory

Skail memory means deliberate user/project instructions and bounded session summaries, not silent semantic harvesting. The first release uses file-backed DeepAgents-compatible memory. The user can inspect and edit it.

### Context isolation

Subagents receive the task request, applicable profile/skills, selected workspace references, and failure handoff when applicable. They do not automatically inherit the lead's full transcript. Persistent child memory is opt-in by profile and policy.

### Context assembly and pressure

Skail treats context as a finite working set, not a transcript dump. Before a lead or child model
attempt, it records a context packet containing selected components, source labels/revisions,
approximate token pressure, and explicit reasons for omitted, truncated, or compressed content.

The always-present portion is minimal: product/safety guidance, the current instruction and explicit
constraints, task success criteria, selected profile, and required current state. Workspace content,
skills, memory, artifacts, and historical detail are introduced through trusted just-in-time tools or
explicit references. Raw tool output is bounded and represented by a redacted artifact reference when
large.

Compaction preserves current objective, user constraints, task/attempt state, assignments, budgets,
approvals/questions, changed paths and verification, unresolved errors, and references to full
events/artifacts. It may discard verbose intermediate output, but never changes authoritative journal
records. Skail does not silently create cross-session semantic memory or inject vector-retrieved
content in the first stable release.

## 20. Human questions and steering

### `ask_user`

Any agent may create a structured question interrupt. It includes prompt, optional choices, reason, blocking scope, and task ID. The answer is recorded and delivered only to the waiting graph state.

### Foreground steering

New input while a foreground run is active is classified as:

- answer to a pending question;
- additive follow-up queued for the lead after the current batch;
- cancellation/replacement of the current run.

The TUI makes the classification visible before destructive cancellation.

### Background steering

When experimental background support is enabled, `/steer` sends a bounded update through the async adapter. It cannot expand permissions, budget, depth, or write scope without normal validation.

## 21. Sessions, resume, and compaction

### Session lifecycle

States: `active`, `idle`, `interrupted`, `completed`, `archived`. Exiting the TUI normally marks the session idle; it does not erase state.

### Resume

Resume restores transcript, lead/task graph states, assignments, task tree, usage, reservations, pending questions, and trust context. Orphaned in-flight provider calls become interrupted; Skail does not charge or replay them without reconciliation evidence.

### Planned dispatch and plan-node recovery

Admitted AGENT plan nodes launch exactly once. Admission binds the node to a
fresh queued task and attempt and moves it READY→LAUNCHING; the dispatch pump
later opens the persisted execution row (`plan_node_executions`) and runs it.

- Launch/reconcile: LAUNCHING/RUNNING/settled/retired/ambiguous provider work
  is never replayed. Ambiguous launches are reconciled to BLOCKED first, and
  settled rows resolve to their recorded terminal state. Nodes that already
  have a persisted task binding or execution record are skipped individually,
  so the LAUNCHING→RUNNING lifecycle is never re-entered from READY.
- Interrupt/block/failure exits: admitted-but-unlaunched nodes (no execution
  row) are reconciled to BLOCKED inside the same journal transaction that
  writes the terminal statuses, each emitting `plan.node_blocked`; the admitted
  dispatches are then cleared. Mid-flight children (with an execution row)
  keep their state, and nothing launches on the exit.
- Only READY nodes are re-admitted on resume, through the normal agent
  admission path (which rebuilds task/attempt/assignment records);
  already-admitted LAUNCHING work from the current resume is excluded from
  reconciliation so fresh work is never blocked as ambiguous, while
  independent READY nodes still dispatch.

### Compaction

Compaction summarizes conversational context while preserving:

- current user intent and explicit constraints;
- active todos/tasks and terminal result summaries;
- changed files and verification;
- model/budget state;
- approvals and unresolved questions.

Full persisted event history remains available for export. Compaction never rewrites usage records.

### Export

Exports include a redacted transcript, task/attempt tree, route explanations, usage, and verification. Secrets and configured sensitive tool output are excluded.

## 22. TUI visibility

### Agent rail

Each row shows task ID suffix, profile, model, status, elapsed time, current activity, and actual/estimated cost. Parent-child nesting is explicit. Queued and approval-waiting states are distinct from running.

### Route view

Displays the recorded assignment, mode, floor, estimate, binding constraints, important exclusions, fallback/escalation lineage, and catalog revision.

### Budget view

Displays hard limit, authoritative actual, estimated actual, reserved, available, warning state, lead allowance, and per-agent breakdown.

### Event stream

Tool calls and child updates may collapse by default but cannot disappear. Error and approval events remain visible until acknowledged.

## 23. Non-interactive output

### Print mode

- stdout: final lead response only;
- stderr: progress, warnings, approvals, and errors;
- process code reflects completed, failed, blocked, cancelled, or usage error.

### JSONL mode

- stdout: `EventEnvelope` JSON objects, one per line;
- terminal object: `run.completed`, `run.failed`, `run.blocked`, or `run.cancelled`;
- schema version is required;
- malformed provider text is always nested as escaped data, never raw output framing.

## 24. Local observability

### Recorded

Task lifecycle, assignments, candidate exclusion summaries, fallback/escalation, provider latency, normalized usage, reservations, approvals, tool status, verification, recovery, and local errors.

### Not recorded by default

Secrets, complete environment, arbitrary files, unredacted command output, or external traces.

### Retention

Configuration sets diagnostic-log retention. Session history remains until user deletion. Cache deletion does not delete authoritative session or usage records.

## 25. Evaluation harness

### Purpose

Demonstrate that “budget-aware orchestration” improves completed-work economics rather than merely choosing cheap calls.

### Fixture shape

Each fixture defines repository snapshot, user prompt, allowed tools, success oracle, risk/profile hints unavailable to the model only where needed for scoring, deterministic fake-provider behavior or approved live-provider matrix, and expected route invariants.

### Suites

- routing unit fixtures for hard filters and rankings;
- orchestration fixtures for direct/delegate/parallel choices;
- failure fixtures for retry and return-to-lead;
- budget fixtures for reservation races and reduced fan-out;
- safety fixtures for paths, commands, untrusted extensions, and secret redaction;
- end-to-end coding tasks for completion, cost, and wall time.

### Compared policies

- Skail `auto`;
- fixed economy model;
- fixed quality model;
- Skail forced serial;
- orchestration disabled where the task supports a direct baseline.

### Metrics

- oracle-backed completion rate;
- cost per completed task;
- median wall-clock time for parallel-eligible tasks;
- escalation and returned-to-lead rates;
- user-interrupt count;
- unsafe-action and state-recovery defects.

Prompt self-reports do not count as completion.

The deterministic offline suite gates engineering readiness. It cannot promote a novel economic
strategy or establish a broad savings claim. Promotion requires a separately authorized, held-out,
paired live evaluation with preregistered completion, cost, latency, and safety criteria.

## 26. Features removed from the archived implementation

| Archived feature | Skail decision | Reason / replacement |
|---|---|---|
| OpenAI-compatible proxy and HTTP server | Remove | Skail invokes providers directly as a harness. |
| Router-only and plugin operating modes | Remove | One native runtime owns agent and tool execution. |
| Plugin plane and `/plugin/*` endpoints | Remove | Task lifecycle is in Skail's graph/runtime. |
| OMA Node sidecar and complexity intercept | Remove | DeepAgents subagents plus Skail task graphs provide delegation. |
| Local SLM/ONNX classifier and downloader | Remove | Lead judgment plus deterministic runtime policy; no second classifier. |
| Turn Guard as proxy request classifier | Remove | Retain only deterministic stagnation ideas inside task attempts. |
| Session capability-floor bias | Remove | Explicit task attempt and escalation state replaces implicit turn bias. |
| Harness shims/hooks/spool files | Remove | Skail is the harness, not an observer of Claude Code/Pi/OpenCode. |
| Agent config mutation/backups | Remove | Skail reads its own config and never patches another harness. |
| FastAPI/Uvicorn request surface | Remove from core | No server is needed for local operation. |
| LiteLLM proxy dependency | Remove from core | LangChain provider integrations and explicit compatible adapters. |
| LanceDB knowledge/RAG | Do not port initially | Skills, memory, filesystem context, and subagent isolation cover v1 needs. |
| Existing Textual dashboard | Redesign | Reuse proven widgets/utilities only when they fit conversation-first UI. |
| Model presets/pricing catalog | Transform | Normalize into evidence-bearing model profiles and provider discovery. |
| Provider credentials and endpoint logic | Transform | Move behind provider adapters; preserve LLM Gateway and DevPass. |
| Capability-floor routing | Transform | Route task attempts, add evidence gates and total-attempt cost. |
| Deterministic repeated-call/error detection | Transform | Attempt-level stagnation signal; one escalation maximum. |
| Usage stats/ledger | Transform | Transactional run/task budget, reservation, and event journal. |
| Fail-soft proxy behavior | Replace | Agent/tool errors are structured and recoverable, but never falsely successful. |

## 27. Cross-feature invariants

1. Explicit user instructions override orchestration preferences, not safety boundaries.
2. Every model call belongs to a recorded assignment.
3. One healthy attempt uses one concrete provider/model assignment.
4. Every delegated task has at most two attempts.
5. No more than three children run simultaneously.
6. Unknown side effects are treated as writes for scheduling and as approval-worthy for safety.
7. A child cannot enlarge its own tools, permissions, scope, depth, or budget.
8. Todo state is not executable task state.
9. Estimated cost and usage are labelled; authoritative provider usage is distinguishable.
10. Terminal state and cost survive resume without duplicate execution.
11. User changes and partial child work are never discarded silently.
12. Legacy Skail code is reference-only and cannot be imported by Skail.
