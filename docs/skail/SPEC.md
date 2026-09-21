# Specification: Skail

> Status note: this is a normative product contract. Its requirements are implemented and verified
> only where the active tracker, tests, or named evidence say so; it is not a blanket capability or
> release-qualification claim. See [the feature matrix](FEATURE_PARITY_ROADMAP.md).

Status: Approved
Date: 2026-09-02
Target platforms: Windows and Linux
Runtime: Python 3.12+, DeepAgents and LangGraph
Command: `skail`

## 1. Objective

Skail Harness (distribution: `skail-harness`, command: `skail`) is a local, provider-neutral coding harness for people who want the speed and accuracy of an orchestrated multi-agent workflow while staying within a budget.

The default experience is:

> Just prompt; Skail will orchestrate.

A capable lead agent may solve simple work directly or delegate bounded work to as many as three subagents. Every lead run and subagent task receives a model assignment before its first provider call. The model remains stable for that attempt. Skail selects models according to hard capability requirements, task role, observed evidence, provider health, and budget. Explicit user instructions override orchestration preferences but never bypass safety policy.

Skail supersedes the archived predecessor product. It is not a proxy, plugin, daemon, or adapter
for another coding harness.

## 2. Users and jobs

### Primary user

A developer who:

- wants multi-agent exploration, implementation, testing, and review;
- uses more than one model or provider;
- cares about completion quality and turnaround time;
- cannot justify running every task on the most expensive model;
- wants automation without surrendering visibility or control.

### Primary jobs

1. Give Skail an ordinary coding request without describing an orchestration strategy.
2. Let the lead agent decide whether direct execution or delegation is appropriate.
3. Run independent subagent work concurrently when that reduces wall-clock time.
4. Assign cheaper or stronger models according to each task's role and requirements.
5. See what every agent is doing, what it costs, and why a model was selected.
6. Override the default model, budget, concurrency, delegation, or agent selection when desired.
7. Resume interrupted work with the task tree, route decisions, and transcript intact.

## 3. Product principles

1. **Just prompt; Skail will orchestrate.** Ordinary use must not require the user to design a graph or choose agents.
2. **Explicit intent wins.** “Do this yourself,” “use a reviewer,” “do not edit,” and similar user constraints override autonomous preferences.
3. **One capable lead.** The lead agent can read, edit, execute, and answer; it is not a coordinator that is helpless without children.
4. **Delegate for leverage.** Use subagents for parallel work, specialized judgment, or context isolation—not ritualistically.
5. **Assign models to tasks, not calls.** A task attempt has one model owner. Silent per-call model switching is prohibited.
6. **Optimize completed work.** Cost per successful task is the primary economic metric, not the price of an isolated call.
7. **Escalate once.** The first task-attempt failure may retry on a stronger model. A second failure returns to the lead.
8. **Bound concurrency.** No more than three subagents execute concurrently, and the user may configure a lower limit.
9. **Share outcomes, isolate noise.** Subagents receive explicit context and return structured results; their intermediate context does not bloat the lead conversation.
10. **Useful, not austere.** Keep the visible concepts and default tools small enough to understand but complete enough for daily coding.
11. **Safety is a runtime boundary.** Prompts are not access controls. Filesystem and command restrictions are enforced outside the model.
12. **Local and legible.** Sessions, costs, routes, and task events are stored locally. External telemetry is off by default.

### 3.1 Product lineage

Skail deliberately combines ideas from four sources without cloning any one of them:

| Source | Pull into Skail | Do not copy |
|---|---|---|
| Pi | A direct prompt-to-work loop, a compact comprehensible core tool set, project/user instructions and skills, strong provider compatibility testing, and a terminal experience that keeps the model capable of ordinary direct work. | An exact tool-count target or treating multi-agent orchestration as only an optional example extension. |
| DeepAgents SDK | The agent loop, standard `task` tool, compiled subagents, filesystem/execution/todo/skills/memory capabilities, middleware, backends, human interrupts, and LangGraph persistence/streaming. | Framework types as Skail's public contracts or prompt-only security. |
| Deep Agents Code (`dcode`) | The proven shape of a capable main coding agent, Textual terminal client ideas, provider/model selection, slash commands, and a real coding-agent product built on DeepAgents. | Its deployment topology as a requirement; Skail's initial local runtime does not require a LangGraph server process. |
| Skail | Provider neutrality, LLM Gateway/DevPass support, capability-floor economics, route explainability, deterministic failure signals, and local usage accounting. | The proxy, plugin plane, OMA, SLM, shims, daemon, or compatibility modes. |

Current upstream terminology matters: `deepagents-cli` now covers deployment-oriented `init`, `dev`, and `deploy` commands, while the interactive terminal coding agent is the separate `deepagents-code` package launched as `dcode`. Skail should study `dcode` for product behavior and the DeepAgents SDK for its runtime foundation, not treat the deployment CLI as the harness framework.

Sources:

- [Pi coding-agent prompt and default tool design](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/src/core/system-prompt.ts)
- [Pi provider integration test expectations](https://github.com/badlogic/pi-mono/blob/main/AGENTS.md)
- [DeepAgents repository and Deep Agents Code overview](https://github.com/langchain-ai/deepagents)
- [DeepAgents repository layout and CLI/dcode distinction](https://github.com/langchain-ai/deepagents/blob/main/AGENTS.md)

## 4. Scope

### Required for the first stable Skail release

- Conversation-first terminal UI and non-interactive print/JSON modes.
- Capable lead agent built with `create_deep_agent()`.
- Built-in general-purpose, explorer, implementer, tester, reviewer, and researcher profiles.
- DeepAgents filesystem, execution, todo, skills, memory, and synchronous subagent facilities where applicable.
- Up to three parallel synchronous subagent tasks.
- Task-bound model assignment and one automatic escalation attempt.
- `auto`, `economy`, `quality`, and `manual` routing modes.
- Optional per-run budget with reservations and hard launch gates.
- Windows PowerShell and Linux shell execution.
- Provider registry using LangChain integrations plus first-class LLM Gateway and DevPass adapters.
- Project/user agent definitions and skills, loaded only under the trust policy.
- Workspace permissions, command approval, cancellation, and explicit error surfaces.
- SQLite checkpoints, local task/route/usage journal, resume, and export.
- Route, budget, context, agent, and cost visibility.
- A replayable routing/orchestration evaluation suite.

### Required eventually, but isolated from the stable core

- Background subagents with individual check/update/steer/cancel operations.
- Worktree-isolated concurrent writers and patch integration.
- ACP or another editor-facing protocol.
- Optional remote or sandbox backends.

These features must sit behind Skail-owned interfaces because DeepAgents async subagents remain preview functionality.

### Explicit non-goals

- OpenAI- or Anthropic-compatible proxy endpoints.
- A daemon required for local interactive use.
- Plugin planes, hook spools, or external-harness shims.
- OMA compatibility or an OMA sidecar.
- An embedded SLM or ONNX classifier.
- Automatic task-graph recompilation after every error.
- Unbounded recursive agents or concurrency.
- Automatic routing across models lacking trustworthy capability and price data.
- Mandatory plan mode for simple work.
- Built-in semantic RAG or LanceDB in the initial product.
- Silent telemetry, mandatory LangSmith tracing, or cloud session storage.
- Runtime compatibility with Skail commands or configuration.

## 5. User-visible execution model

### 5.1 Lead behavior

The lead agent is a normal tool-using coding agent. Its first necessary response may provide a final
answer or record a typed `direct`, `discover`, or `planned` execution decision. The same response may
continue with compatible tools after the decision is accepted. A scoped user question may come
first when intent or authority is genuinely missing. For each user instruction the lead may:

- answer directly;
- inspect and modify the workspace directly;
- create a concise todo list for multi-step work;
- delegate one or more independent tasks;
- synthesize subagent results and continue implementation;
- ask the user when requirements or authority are missing.

`direct` retains the full lead tool loop and may submit a plan later when evidence changes.
`discover` submits only the next evidence-gathering frontier and a decision checkpoint. `planned`
submits a finite dependency graph whose ready work can proceed without another lead call. The
runtime validates plans before execution; generated code and `write_todos` content are not plans.
When a discovery checkpoint becomes ready, Skail wakes the same lead assignment with the current
plan and the bounded evidence references produced by its completed prerequisites. The lead records
the complete next plan plus typed revision metadata through `execution_decision`; the runtime
validates those references and applies the revision compare-and-set before releasing new work.

The lead should delegate when at least one of these is true:

- two or more independent workstreams can proceed concurrently;
- exploration would add substantial intermediate context to the lead;
- a specialist profile materially changes the tool set or review posture;
- independent review or verification would reduce meaningful risk.

The lead should normally work directly when the request is a question, a localized edit, a short serial operation, or delegation overhead would be comparable to the work.

These are prompt-level behavioral rules, not hard routing gates. Explicit user instructions take precedence.

### 5.2 Subagent behavior

Each delegated task has:

- a stable task ID and parent run ID;
- a role/profile;
- a bounded description and success criteria;
- an allowed tool set and permission policy;
- an optional write scope;
- a model assignment with explanation;
- a budget reservation;
- at most two attempts;
- a structured terminal result.

Before a lead or child model attempt, Skail assembles a small, inspectable context packet. It
contains current intent and explicit constraints, task/profile requirements, required state, and
labelled references selected within trust, permission, task-scope, and budget boundaries. Repository
detail, prior artifacts, skills, memory, and history load progressively through permitted tools or
explicit references; a child never receives the complete lead transcript by default. Under pressure,
compaction preserves current intent, task state, assignments/budgets, approvals/questions, changed
paths/verification, unresolved errors, and references to retained records.

Default child agents cannot delegate further. User-defined agents may opt into delegation, but the default maximum depth is one and the global three-agent concurrency limit still applies.

The standard `task` tool remains supported and admits one task through the same plan service. Plans
use local node names; Skail assigns persistent IDs, rejects cycles, missing references, duplicate
objectives, invalid scopes, and unauthorized effects, and preserves completed node identities across
revisions.

### 5.3 Foreground and background work

Foreground subagents use DeepAgents synchronous subagents. The lead blocks until the batch returns, although the TUI streams nested events and the user may cancel the whole active run. Multiple independent `task` calls in one assistant message may execute concurrently, subject to Skail's semaphore.

Background subagents are optional. When enabled, they use a Skail adapter over DeepAgents async subagents and gain individual status, update, and cancellation. The rest of Skail consumes the same `TaskExecutor` contract and must not depend on Agent Protocol details.

## 6. Model-routing behavior

### 6.1 Assignment boundary

The lead receives a model assignment before processing a new user instruction. A subagent receives an assignment in its compiled subgraph's assignment node before the first model call.

No routing policy may replace a model during a healthy attempt. Transport fallback and the single explicit escalation create a new recorded assignment.

### 6.2 Routing modes

| Mode | Behavior |
|---|---|
| `auto` | Select the lowest estimated-cost model that clears the capability floor and task budget while preserving role-specific quality requirements. |
| `economy` | Reduce the soft capability floor by one band, never below hard role, tool, context, modality, or safety requirements. |
| `quality` | Prefer highest measured capability fit within any explicit hard budget. Cost is a tiebreaker. |
| `manual` | Use the exact user-pinned model. Skail validates compatibility and reports conflicts rather than silently substituting, except for an explicitly configured provider-failure fallback. |

The user may pin only the lead model while leaving subagents automatic, or constrain a named agent profile to a model/policy.

### 6.3 Selection inputs

Hard filters:

- provider is configured and healthy;
- model is enabled;
- required tool calling and structured output are supported;
- context and output limits fit;
- required input modalities fit;
- provider/model is allowed by user configuration;
- estimated next call does not violate the hard budget gate;
- task-specific exclusions and prior failed model are respected.

Soft ranking inputs:

- capability fit for role and task kind;
- measured coding, reasoning, tool reliability, and latency evidence;
- estimated total attempt cost, including expected number of calls;
- recent local success/failure health;
- prompt-cache compatibility;
- routing mode.

Unknown capability is not zero and is not invented from model price, parameter-count strings, or brand names. Unknown models remain manually selectable but are excluded from automatic routing until a user supplies a trusted profile or evaluation evidence.

### 6.4 Initial capability floors

Initial values are evaluation hypotheses, not permanent product truths:

| Role | Base floor |
|---|---:|
| explorer | 0.35 |
| tester | 0.40 |
| researcher | 0.45 |
| general-purpose | 0.50 |
| implementer | 0.50 |
| reviewer | 0.55 |
| lead | 0.60 |

Task risk supplies another floor: trivial `0.25`, routine `0.35`, bounded `0.45`, complex `0.60`, high-risk `0.70`. The effective initial floor is:

```text
floor = clamp(max(role_floor, task_risk_floor) + mode_adjustment, role_hard_min, 0.85)
```

Mode adjustment is `-0.10` for economy, `0.00` for auto, and `+0.15` for quality. Manual mode does not use a floor. An escalation excludes the failed model and adds `+0.15`, capped at `0.90`.

These values must be configurable and replaced or confirmed through evaluation before stable release.

## 7. Budget behavior

Budgeting is opt-in. Cost-aware ranking remains active without a hard budget.

Supported limits:

- run/session hard budget;
- optional per-task hard budget;
- warning percentage, default 80%;
- optional provider or model price ceiling;
- maximum subagent concurrency.

Accounting rules:

1. Actual reported provider usage is authoritative when available.
2. Missing usage is estimated and visibly labelled.
3. Before a model call, Skail reserves its estimated input plus configured output allowance.
4. Before a parallel batch, Skail reserves every child attempt plus one lead continuation allowance.
5. New tasks or calls that would exceed the remaining unreserved budget do not launch. The lead receives a structured budget-blocked result and can reduce fan-out, select a cheaper qualified model, or ask the user.
6. In-flight calls are not killed solely because their estimate was low. Skail prevents subsequent calls and reports any bounded overshoot.
7. A task escalation must fit the remaining task and run budgets. It never silently ignores the cap.
8. Provider transport retries do not create duplicate usage events.

The primary economic measurement is total cost divided by successfully completed benchmark tasks.

## 8. Default tools

Skail exposes most of the useful DeepAgents coding surface without duplicating equivalent tools.

Default model-facing tools:

- `ls`
- `glob`
- `grep`
- `read_file` including supported image reads
- `write_file`
- `edit_file`
- `execute`
- `write_todos`
- `task`
- `ask_user`

Optional tools:

- `web_search`, enabled only when configured;
- MCP tools, installed and enabled explicitly;
- project/user Python extension tools, loaded only from trusted sources;
- background-task tools when the async adapter is enabled.

Git operations initially use `execute`; Skail will not add a redundant Git tool until evaluations show a reliability or safety benefit.

Tool visibility is profile-specific. Explorer and reviewer profiles do not receive write tools. Any profile with `execute` is treated as potentially write-capable for scheduling and approval because a shell can modify files even when `write_file` is hidden.

## 9. Agent profiles

| Profile | Purpose | Default tools | Default write posture |
|---|---|---|---|
| lead | Owns outcome, direct work, delegation, synthesis | all defaults | allowed under user policy |
| general-purpose | Bounded work without a specialist fit | filesystem, execute, skills | exclusive write lease |
| explorer | Codebase discovery and dependency analysis | ls, glob, grep, read_file | read-only |
| implementer | Bounded source changes and focused verification | filesystem, execute | exclusive write lease or worktree |
| tester | Run and interpret tests; propose fixes | filesystem read, execute | execute-capable; exclusive lease |
| reviewer | Independent correctness/security/quality review | filesystem read, execute | read-only tools; execute-capable lease |
| researcher | External or documentation research | read_file, optional web/MCP | read-only |

Profiles are defaults, not hardcoded model names. Routing assigns a model for every task instance.

Project and user profiles use `.skail/agents/<name>/AGENTS.md` and `~/.skail/agents/<name>/AGENTS.md`. Frontmatter may declare description, role, tools, model policy, permissions, whether delegation is allowed, and structured output schema. Project definitions are ignored until the project is trusted.

## 10. Concurrency and workspace ownership

- `orchestration.max_agents` accepts `1`, `2`, or `3`; default `3`.
- The limit includes all active child agents, foreground and background.
- Tasks with unmet dependencies remain queued.
- Read-only tasks may run concurrently.
- In shared-workspace mode, tasks with `execute`, `write_file`, or `edit_file` acquire a write lease. Unknown scope means a workspace-wide exclusive lease.
- Declared non-overlapping scopes may run together only when worktree isolation is enabled.
- The lead does not edit while a child holds the shared-workspace write lease.
- If a non-Git workspace cannot provide worktrees, Skail falls back to a single writer rather than pretending isolation.
- The scheduler queues excess tasks; it does not fail them merely because the current concurrency limit is full.
- Isolated writers execute from a recorded reproducible workspace snapshot and return a change set;
  one serialized integration owner checks conflicts and verification before applying it.

## 11. Failure and escalation

A tool error is evidence, not automatically a failed task attempt.

An attempt fails when any of these becomes true:

- the subgraph returns a structured `failed` result;
- a required success criterion or final verification is explicitly unmet;
- provider retries and same-tier fallback are exhausted;
- three identical consecutive tool calls occur;
- two consecutive tool errors occur;
- the same normalized error occurs twice;
- the attempt reaches its configured call, time, or budget boundary without a successful result;
- an unhandled runtime exception escapes the agent.

Attempt-one failure:

1. Persist the failure reason, evidence, current diff/worktree, and route decision.
2. Exclude the failed concrete model.
3. Raise the capability floor once.
4. Start attempt two with the same task ID, a new attempt ID, and a concise failure handoff.

Attempt-two failure:

1. Mark the task `returned_to_lead`.
2. Return both attempts and workspace state to the lead.
3. The lead may solve directly, re-scope into a materially different task, or ask the user.
4. Re-submitting the same normalized task fingerprint for another automatic retry is blocked unless the user explicitly authorizes it.

Safety denials and missing user authority produce `blocked`, not `failed`, and do not consume the escalation attempt.

## 12. Sessions and persistence

- LangGraph checkpointing is authoritative for runnable state and transcript recovery.
- Skail maintains a separate local SQLite journal for session metadata, task lifecycle, route decisions, approvals, and usage.
- User data lives under `~/.skail/`.
- Context compaction may be lossy, but checkpoints and exported session history preserve the underlying record.
- Resume restores the lead conversation, active task states, model assignments, budget accounting, and pending approvals.
- Local telemetry is enabled; external telemetry and LangSmith tracing are disabled unless explicitly configured.
- Credentials never appear in checkpoints, event payloads, prompts, or exports.

### 12.1 Global state and root instructions

Skail creates one physical `.skail` directory per user at `~/.skail`. Workspace-scoped state is
namespaced below `~/.skail/workspaces/<canonical-workspace-identity>/`; repositories and isolated
worktrees do not receive runtime `.skail` directories. Legacy local state may be imported
non-destructively and idempotently, with a redacted migration receipt and no automatic deletion.

Before each lead or child attempt, context assembly appends applicable root instructions in this
order: built-in Skail rules, `~/.skail/AGENTS.md`, then trusted `<workspace>/AGENTS.md`. Components
are bounded, secret-redacted, source-labelled, revision-hashed, and pinned for the attempt. A
workspace file found in an untrusted project is reported as ignored. These instructions cannot
relax code-owned safety, approval, permission, budget, concurrency, or filesystem boundaries.

## 13. Terminal experience

The default screen prioritizes the conversation rather than a configuration dashboard:

- message/tool stream in the main area;
- collapsible agent/task rail showing parentage, role, model, status, elapsed time, and cost;
- editor with steering/follow-up behavior;
- footer showing lead model, routing mode, session cost/budget, context usage, and active-agent count.

Required commands:

| Command | Function |
|---|---|
| `/agents` | Show the task tree and active assignments. |
| `/agent <id>` | Focus one agent's events and result. |
| `/tasks` | Show planned todos separately from executing task records. |
| `/route [id]` | Explain the lead or task model selection. |
| `/budget` | Show actual, estimated, reserved, and remaining budget. |
| `/mode <auto|economy|quality|manual>` | Change routing mode for future assignments. |
| `/model` | Choose or pin lead/subagent models. |
| `/cancel [id]` | Cancel the whole foreground run or an individual background task. |
| `/steer <id> <message>` | Update a background task when supported. |
| `/resume` | Select a previous session. |
| `/compact` | Request context compaction. |
| `/trust` | Inspect or set project trust. |
| `/config` | Inspect effective layered configuration and sources. |
| `/quit` | Exit after safely flushing local metadata. |

Interactive help also exposes `/help`, `/theme [dark|light|system]`, `/model`, and
`/missions` (`/children` is an alias). These entries use the same registry as parsing,
completion, and dispatch. `/fork` is intentionally not exposed: durable session forking has no
persisted contract yet.

The composer is the main-screen interaction anchor. The transcript and side panels are passive;
mouse clicks and keyboard focus cannot activate them. `Shift+Tab` cycles Agents → Plan → Route →
Budget while focus remains in the composer. Routing mode is changed with `/mode`; the former
Ctrl+A/B/P/R panel bindings are not part of the interface.

## 14. CLI contract

```text
skail [PROMPT...]
skail -p|--print [PROMPT...]
skail --json [PROMPT...]
skail -c|--continue
skail -r|--resume [SESSION_ID]
skail --no-session
skail --mode auto|economy|quality|manual
skail --model PROVIDER:MODEL
skail --lead-model PROVIDER:MODEL
skail --agent-model PROFILE=PROVIDER:MODEL
skail --budget USD
skail --max-agents 1|2|3
skail --delegation auto|ask|off
skail --workspace shared|worktree
skail --approve-project|--deny-project
skail auth ...
skail models ...
skail sessions ...
skail config ...
```

With no prompt in a terminal, `skail` starts interactive mode. Print mode emits only the final response to stdout and diagnostics to stderr. JSON mode emits versioned JSONL events. There is no implicit local server.

## 15. Configuration

Precedence, highest first:

1. CLI flags and explicit current-session changes.
2. Trusted workspace configuration in the global workspace namespace.
3. User `~/.skail/config.toml`.
4. Built-in defaults.

Secrets are resolved from environment variables or an OS credential store. Project configuration may reference a secret's environment-variable name but may not contain the secret value.

Onboarding choices are device-global and versioned. Credential resolution is explicit environment
variable, OS credential store, then interactive entry; interactive values are never persisted in
Skail files, logs, checkpoints, exports, screenshots, or test evidence.

Illustrative configuration:

```toml
[routing]
mode = "auto"
lead_model = "auto"
allow_unmeasured_models = false

[orchestration]
delegation = "auto"
max_agents = 3
max_depth = 1
background_agents = false
workspace_mode = "shared"

[budget]
run_usd = 2.00
warning_percent = 80

[providers.llmgateway]
type = "openai-compatible"
base_url = "https://api.llmgateway.io/v1"
api_key_env = "LLMGATEWAY_API_KEY"

[safety]
project_trust = "ask"
write_policy = "allow-workspace"
command_policy = "ask-dangerous"
```

The literal `base_url` must be `https://api.llmgateway.io/v1`; configuration validation must reject malformed schemes or unexpected path suffixes.

## 16. Commands for the planned repository

The exact dependency manager is confirmed during the skeleton task. The intended developer interface is:

```powershell
python -m pip install -e ".[dev]"
python -m pytest
python -m pytest tests\unit -q
python -m pytest tests\contract tests\integration -q
python scripts\smoke.py --fake-provider
python scripts\eval_routing.py --fixture evals\fixtures
graphify update .
```

Provider-live tests are opt-in and never part of the offline default suite.

## 17. Project structure

```text
src/skail/                 Skail package
  agents/                   lead and subagent profiles, loaders, task graphs
  cli/                      command parsing and non-interactive presentation
  config/                   typed schema, layered loading, paths
  providers/                provider factories, credentials, model registry
  routing/                  requirements, policy, budgets, health, explanations
  runtime/                  DeepAgents adapter, graph state, orchestration, events
  sessions/                 checkpoints, metadata, export
  tools/                    tool assembly, execution policy, approvals
  tui/                      Textual application and projections
  telemetry/                local usage and task event journal
tests/
  unit/                     pure policy and state tests
  contract/                 DeepAgents and provider adapter contracts
  integration/              graph, tools, persistence, and orchestration flows
  e2e/                      Windows/Linux CLI smoke scenarios
evals/                      replayable quality/cost/orchestration fixtures
docs/skail/                product and technical source of truth
docs/decisions/             accepted and superseded ADRs
legacy/skail/         inert reference snapshot, excluded from Skail package
tasks/                      active implementation plan and checklist
```

## 18. Code style

- Python 3.12 type syntax and `from __future__ import annotations` where useful.
- Pydantic models at configuration and external-data boundaries; dataclasses or typed dictionaries for small internal values.
- Protocols define replaceable framework/provider/storage boundaries.
- Discriminated unions represent events and state variants.
- No module-level mutable singleton for run state.
- Async only for I/O or concurrency; pure routing logic stays synchronous and deterministic.
- Errors use stable codes and structured details.

Representative interface style:

```python
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TaskAssignment:
    task_id: str
    attempt: int
    model: str
    estimated_cost_usd: float
    explanation: tuple[str, ...]


class RoutingPolicy(Protocol):
    def assign(self, request: "AssignmentRequest") -> TaskAssignment: ...
```

## 19. Testing strategy

- Unit tests prove deterministic routing, budgets, task state, failure fingerprints, configuration, and permissions.
- Contract tests pin all Skail assumptions about `create_deep_agent`, compiled subagents, state propagation, streaming namespaces, middleware ordering, and checkpointing.
- Provider contract tests use fake HTTP servers and recorded schema fixtures; live tests are opt-in.
- Integration tests run a lead and multiple fake-model subagents through actual compiled graphs.
- Concurrency tests prove that active children never exceed three and write leases prevent unsafe overlap.
- End-to-end tests execute the packaged `skail` command on Windows and Linux.
- Evaluation tests compare automatic routing with fixed economy and quality baselines on at least 50 representative coding tasks.

## 20. Boundaries

### Always

- Preserve task-bound model stickiness.
- Enforce maximum concurrency and delegation depth outside prompts.
- Validate provider responses and project-defined configuration.
- Record every assignment, fallback, escalation, approval, and budget block.
- Keep secrets out of state, logs, prompts, and exports.
- Test with fake models before provider-live tests.
- Run focused tests and `graphify update .` after code changes.

### Ask first

- Add a required runtime dependency.
- Change a public CLI flag, config key, event schema, or persisted data contract.
- Enable external telemetry or remote execution by default.
- Raise the concurrency or delegation-depth maximum.
- Make an unmeasured model automatically routable.
- Add a built-in tool that duplicates an existing DeepAgents capability.

### Never

- Reintroduce proxy or plugin-plane architecture.
- Import from `legacy/skail` at runtime.
- Treat an LLM or SLM classification as safety authority.
- Allow prompts alone to enforce filesystem or command security.
- Switch models invisibly within a healthy task attempt.
- Retry a failed task more than once automatically.
- report estimated usage or success as observed fact.

## 21. Acceptance criteria

Skail is ready for stable release when:

- a user can install and launch `skail` on Windows and Linux;
- simple work can be completed directly without mandatory delegation;
- eligible complex work can launch up to three parallel subagents;
- every subagent receives a model assignment before its first provider call;
- healthy attempts never change models;
- attempt one may escalate once and attempt two returns to the lead on failure;
- explicit user delegation, model, budget, write, and concurrency instructions are honored;
- shared-workspace write conflicts cannot run concurrently;
- all assignments and costs are visible and exportable;
- resume restores task and budget state without duplicating work;
- LLM Gateway completes streaming tool-call and structured-output contract tests;
- all default tests run offline;
- engineering readiness passes every approved deterministic offline oracle with no new safety or
  workspace defect; unsupported economic strategies remain shadow or experimental;
- production promotion of an economic strategy requires paired held-out evidence showing no lower
  observed completion than the capable direct baseline, with the preregistered confidence bound,
  and at least 20% lower aggregate cost per successful request;
- parallel-eligible scenarios reduce median wall-clock time by at least 15% compared with the same tasks forced serial;
- no critical safety or data-loss defect remains open.

The offline engineering boundary and live economic-qualification boundary are separate. Live
qualification requires explicit provider-spend authorization and an approved evaluation protocol.
Neither engineering readiness nor a release tag proves a broad savings claim.

## 22. Approved implementation decisions

1. Use `skail-harness` as the Python distribution name and retain the `skail` command.
2. Keep background agents experimental and isolated behind `TaskExecutor`; they are not a stable-release blocker.
3. Stable engineering evaluation uses at least 50 approved, oracle-backed offline fixtures balanced
   across risk, role, parallelism, platform, and failure behavior. Economic promotion uses the
   separate paired live qualification contract in ADR 0006 and the active implementation guide.
4. The stable core resolves credentials from environment-variable references. OS keyring support may be added later as an optional extra.
5. Target Python 3.12+. Pin the exact DeepAgents/LangGraph compatibility range only after Phase 1 contract spikes verify it.
6. Use the adaptive execution and release boundaries accepted in
   [ADR 0006](../decisions/0006-adaptive-execution-and-release-boundaries.md).
7. Use the global-state and instruction-precedence contract accepted in
   [ADR 0007](../decisions/0007-global-state-and-instruction-precedence.md).
