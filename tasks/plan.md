# Rudder Implementation Plan

Status: Approved; implementation in progress on the `rudder` branch.
Date: 2026-09-02
Product specification: [../docs/rudder/SPEC.md](../docs/rudder/SPEC.md)
Architecture: [../docs/rudder/ARCHITECTURE.md](../docs/rudder/ARCHITECTURE.md)
Feature contracts: [../docs/rudder/FEATURES.md](../docs/rudder/FEATURES.md)
Repository transition: [../docs/rudder/MIGRATION.md](../docs/rudder/MIGRATION.md)

## 1. Delivery strategy

Build Rudder in vertical, verifiable slices. Establish the DeepAgents contracts and safety/economic invariants before investing in the full TUI. Every task should end with focused tests and a graph update. No task may silently broaden the approved specification.

The critical sequence is:

```text
approve contracts
  -> isolate legacy and create Rudder skeleton
  -> prove DeepAgents composition/model binding
  -> define domain/events/config/storage
  -> providers/catalog
  -> routing/budgets
  -> tools/safety
  -> task graphs/scheduler/failure policy
  -> lead and sessions
  -> CLI/TUI
  -> evaluation and release gates
```

Optional background agents and worktrees follow the stable synchronous shared-workspace release unless explicitly promoted after the framework spikes.

## 2. Definition of done for every implementation task

- Acceptance criteria are covered by automated tests where behavior is deterministic.
- Focused tests pass before the full affected suite is run.
- New user-visible errors use stable codes and actionable messages.
- New external/framework assumptions have contract tests.
- No secret or unrestricted tool output is added to logs/events/fixtures.
- Existing user changes are preserved and unrelated code is not reformatted.
- Public contract changes update the relevant specification/ADR in the same task.
- `graphify update .` is run after source or documentation changes.
- `rtk git diff --check` passes.
- The task checklist records verification and any deliberately deferred work.

## 3. Phase 0 — Approval and repository boundary

### Task 0.1: Resolve specification decisions

**Purpose:** Turn the proposed documents into an approved implementation contract.

**Decisions required:**

- Python distribution name while retaining the `rudder` command;
- whether background agents ship experimental or post-stable;
- initial evaluation fixture composition and numerical gates;
- environment-only versus optional OS-keyring credentials;
- exact DeepAgents/LangGraph supported version range after spikes.

**Acceptance:**

- [x] Decisions are recorded in the spec or a follow-up ADR.
- [x] ADR 0001 is `Accepted`.
- [x] The user explicitly authorizes the new branch and source-tree transition.

**Verification:** Review links and `rtk git diff --check`.

**Dependencies:** None.
**Likely files:** `docs/rudder/SPEC.md`, `docs/decisions/0001-rudder-native-multi-agent-harness.md`.
**Size:** S.

### Task 0.2: Preserve AutoConduck and relocate the legacy tree

**Purpose:** Establish a reversible, inert legacy boundary on the new Rudder branch.

**Steps:**

1. Verify clean/understood Git state and authoritative AutoConduck version.
2. Create the approved preservation reference and `rudder` branch.
3. Generate and review the exact move manifest described in `MIGRATION.md`.
4. Move old runtime, tests, scripts, packaging, and product docs into `legacy/autoconduck/` with Git-aware moves.
5. Add the legacy archive README and ignore/exclusion rules.

**Acceptance:**

- [x] No source file is lost; moves are reviewable in Git.
- [x] Legacy code has no root console entrypoint or active test collection.
- [x] `legacy/autoconduck/README.md` marks it reference-only and unmaintained on this branch.
- [x] AutoConduck user data is untouched.
- [x] Root Rudder docs and archived plans remain accessible.

**Verification:** `rtk git status`, `rtk git diff --stat`, reviewed move manifest, and targeted file-existence checks.

**Dependencies:** 0.1.
**Likely files:** mechanical move across the existing project; exception to the normal five-file task limit.
**Size:** L, mechanical/high-review.

### Task 0.3: Create the Rudder package and fake-provider smoke

**Purpose:** Produce the smallest installable native harness boundary.

**Implementation:**

- root `pyproject.toml` with `src` layout and `rudder` console script;
- `src/rudder/__init__.py` and `src/rudder/cli/main.py`;
- a minimal CLI with `--help`, version, and a fake-provider smoke command;
- root test configuration that excludes `legacy/`;
- no real DeepAgents orchestration yet.

**Acceptance:**

- [x] Editable install succeeds in a clean Python 3.12 environment.
- [x] `rudder --help` and `rudder --version` execute the new package.
- [x] Built distribution contains no `autoconduck` modules or old commands.
- [x] Tests are not collected from `legacy/`.
- [x] Core import does not require provider credentials or optional provider SDKs.

**Verification:** build/wheel content test, CLI subprocess test, `python -m pytest tests/unit/test_packaging.py -q`.

**Dependencies:** 0.2.
**Likely files:** `pyproject.toml`, `src/rudder/__init__.py`, `src/rudder/cli/main.py`, `tests/unit/test_packaging.py`, `README.md`.
**Size:** M.

### Task 0.4: Establish test, type, and CI skeleton

**Purpose:** Make Windows and Linux behavior visible from the first runtime task.

**Acceptance:**

- [x] Unit, contract, integration, and e2e markers/paths are defined.
- [x] CI runs offline unit/contract smoke on supported Windows and Linux versions.
- [x] Provider-live tests require an explicit marker and credentials.
- [x] CI checks wheel contents and the legacy import boundary.

**Verification:** local test commands plus CI configuration validation.

**Dependencies:** 0.3.
**Likely files:** `pyproject.toml`, `.github/workflows/ci.yml`, `tests/conftest.py`, `tests/unit/test_import_boundaries.py`, `scripts/smoke.py`.
**Size:** M.

### Checkpoint A — Clean product boundary

- [x] Rudder installs and launches independently.
- [x] AutoConduck exists only under the inert archive or preservation reference.
- [x] Offline tests run on Windows and Linux.
- [x] No proxy/plugin/OMA/SLM dependency is present in the root runtime.

## 4. Phase 1 — Framework contract spikes

These tasks are intentionally disposable at first. Promote spike code only after the contract is understood and tested.

### Task 1.1: Prove a lead DeepAgent with a fake model

**Purpose:** Validate minimal `create_deep_agent()` composition, streaming, tools, and checkpointing on the pinned candidate versions.

**Acceptance:**

- [ ] A fake chat model drives one tool call and one final response.
- [ ] Nested DeepAgents/LangGraph events can be adapted without UI-specific types.
- [ ] A SQLite-backed checkpointer resumes a deliberately interrupted run.
- [ ] The version range and required framework APIs are documented.

**Verification:** `python -m pytest tests/contract/test_deepagents_lead.py -q`.

**Dependencies:** 0.4.
**Likely files:** `src/rudder/runtime/deepagents_adapter.py`, `tests/contract/test_deepagents_lead.py`, `tests/fakes/models.py`, `pyproject.toml`, `docs/decisions/0002-framework-version-contract.md`.
**Size:** M.

### Task 1.2: Prove compiled subagent and pre-call model binding

**Purpose:** Validate the central architectural claim before building routing.

**Implementation:** Create a tiny outer `StateGraph` with validate/assign/execute/result nodes; make its execute node invoke a DeepAgent; supply the compiled runnable as a `CompiledSubAgent` through the standard `task` tool.

**Acceptance:**

- [ ] The lead invokes the child through `task`.
- [ ] The assignment node executes before the child's first model request.
- [ ] Middleware sees the assignment and installs exactly that fake model for every call.
- [ ] Child context is isolated and its structured result returns to the lead.
- [ ] A missing or changed assignment produces a tested invariant error.

**Verification:** `python -m pytest tests/contract/test_compiled_subagent.py -q`.

**Dependencies:** 1.1.
**Likely files:** `src/rudder/runtime/task_graph_spike.py`, `src/rudder/runtime/model_middleware.py`, `tests/contract/test_compiled_subagent.py`, `tests/fakes/models.py`.
**Size:** M.

### Task 1.3: Prove nested streaming, concurrency, and cancellation

**Purpose:** Establish what the stable synchronous path can promise.

**Acceptance:**

- [ ] Three fake child tasks can execute concurrently and expose distinct task/stream identities.
- [ ] A fourth task is externally gated rather than started.
- [ ] Foreground cancellation stops the lead and unfinished children without a false success.
- [ ] Completed child results remain available when another child fails/cancels.
- [ ] Windows event-loop behavior is covered.

**Verification:** deterministic barriers rather than timing-only assertions in `tests/contract/test_deepagents_concurrency.py`.

**Dependencies:** 1.2.
**Likely files:** `src/rudder/runtime/deepagents_adapter.py`, `tests/contract/test_deepagents_concurrency.py`, `tests/fakes/models.py`, `tests/fakes/tools.py`.
**Size:** M.

### Task 1.4: Decide stable versus experimental background support

**Purpose:** Exercise start/check/update/cancel/list through the preview API without coupling the core to it.

**Acceptance:**

- [ ] A small `TaskExecutor` contract supports foreground and preview background adapters.
- [ ] Contract differences and process/server requirements are recorded.
- [ ] The spec decision is updated to ship experimental or defer.
- [ ] Failure to support background mode leaves foreground behavior unchanged.

**Verification:** fake executor contract suite; preview contract test may be separately marked.

**Dependencies:** 1.3.
**Likely files:** `src/rudder/runtime/task_executor.py`, `src/rudder/runtime/background_adapter.py`, `tests/contract/test_task_executors.py`, `docs/rudder/SPEC.md`, `docs/decisions/0003-background-execution.md`.
**Size:** M.

### Checkpoint B — Framework feasibility

- [ ] Compiled tasks really can bind a model before first child call.
- [ ] Synchronous nested events, checkpoints, and cancellation satisfy Rudder contracts.
- [ ] Preview functionality is isolated or deferred.
- [ ] Blocking incompatibilities result in a documented design revision before more code.

## 5. Phase 2 — Domain contracts, events, configuration, persistence

### Task 2.1: Implement IDs, task/attempt/result, and routing domain types

**Purpose:** Create framework-independent canonical state.

**Acceptance:**

- [ ] Standard UUID4 opaque IDs serialize consistently without an extra runtime dependency.
- [ ] Task and attempt states accept only legal transitions.
- [ ] Assignments are immutable and limited to attempt 1 or 2.
- [ ] Money uses decimal strings at serialization boundaries.
- [ ] Domain modules import no DeepAgents, Textual, provider, or database packages.

**Verification:** table-driven unit tests and import-boundary test.

**Dependencies:** Checkpoint B.
**Likely files:** `src/rudder/domain/ids.py`, `src/rudder/domain/tasks.py`, `src/rudder/domain/routing.py`, `src/rudder/domain/usage.py`, `tests/unit/test_domain.py`.
**Size:** M.

### Task 2.2: Implement the versioned event union

**Purpose:** Give runtime, storage, JSONL, and TUI one stable event contract.

**Acceptance:**

- [ ] Envelope requires schema version, IDs, sequence, timestamp, type, and typed payload.
- [ ] All required event families have discriminated payloads.
- [ ] Round-trip, unknown-version, missing-field, and secret-redaction tests pass.
- [ ] Sequence allocation is monotonic per run under concurrency.

**Verification:** `python -m pytest tests/unit/test_events.py -q`.

**Dependencies:** 2.1.
**Likely files:** `src/rudder/domain/events.py`, `src/rudder/runtime/event_bus.py`, `tests/unit/test_events.py`, `tests/unit/test_event_bus.py`.
**Size:** M.

### Task 2.3: Implement configuration schema and layered resolution

**Purpose:** Resolve defaults, user TOML, trusted project TOML, CLI/session overrides, and provenance.

**Acceptance:**

- [ ] Precedence and table/list merge rules match the architecture.
- [ ] Every effective value can report a redacted source.
- [ ] Unknown/malformed/security-sensitive keys follow documented behavior.
- [ ] LLM Gateway URL validation accepts canonical `/v1` and rejects malformed suffixes.
- [ ] Config files cannot contain literal provider secrets under prohibited fields.

**Verification:** fixture matrix in `tests/unit/test_config.py`.

**Dependencies:** 2.1.
**Likely files:** `src/rudder/config/models.py`, `src/rudder/config/loader.py`, `src/rudder/config/paths.py`, `tests/unit/test_config.py`, `tests/fixtures/config/`.
**Size:** M.

### Task 2.4: Implement project trust records

**Purpose:** Prevent project-defined code/config from activating before consent.

**Acceptance:**

- [ ] Canonical path and filesystem identity are used where available.
- [ ] Untrusted/denied/trusted transitions are explicit and persisted.
- [ ] Replacement/move mismatch asks again.
- [ ] Project profiles, skills, tools, MCP, provider references, and approval rules are gated.
- [ ] Revocation affects future loads and signals active project tasks.

**Verification:** Windows and Linux path fixtures; unit tests for trust transitions.

**Dependencies:** 2.3.
**Likely files:** `src/rudder/config/trust.py`, `src/rudder/config/loader.py`, `src/rudder/domain/security.py`, `tests/unit/test_trust.py`.
**Size:** M.

### Task 2.5: Implement Rudder journal and migrations

**Purpose:** Persist product state separately from LangGraph internals.

**Acceptance:**

- [ ] Initial schema covers sessions, runs, tasks, attempts, assignments, reservations, usage, approvals, and events.
- [ ] Migrations are transactional and idempotent.
- [ ] Task state and budget changes can share one transaction.
- [ ] Concurrent writers respect SQLite busy/retry bounds without data duplication.
- [ ] Journal queries return typed domain snapshots, not raw UI rows.

**Verification:** temporary-database tests including rollback and concurrent reservation fixtures.

**Dependencies:** 2.1–2.2.
**Likely files:** `src/rudder/sessions/schema.py`, `src/rudder/sessions/journal.py`, `src/rudder/sessions/migrations.py`, `tests/unit/test_journal.py`, `tests/integration/test_journal_concurrency.py`.
**Size:** L.

### Task 2.6: Wrap LangGraph checkpointing and reconciliation

**Purpose:** Resume graph state without treating framework tables as product data.

**Acceptance:**

- [ ] Checkpointer and journal paths are distinct.
- [ ] Idempotency keys correlate checkpoint and journal operations.
- [ ] Recovery marks orphaned calls interrupted and does not duplicate terminal work.
- [ ] Pending approvals restore as pending, never pre-approved.
- [ ] Corrupt/unavailable checkpoints produce a structured recovery error and preserve journal data.

**Verification:** crash-boundary integration scenarios in `tests/integration/test_recovery.py`.

**Dependencies:** 1.1, 2.5.
**Likely files:** `src/rudder/sessions/checkpoints.py`, `src/rudder/sessions/recovery.py`, `src/rudder/sessions/journal.py`, `tests/integration/test_recovery.py`.
**Size:** L.

### Checkpoint C — Durable core contracts

- [ ] Domain/routing types are framework-independent.
- [ ] Events round-trip and persist.
- [ ] Config/trust cannot activate untrusted project behavior.
- [ ] Crash recovery preserves terminal/task/budget truth.

## 6. Phase 3 — Providers and model catalog

### Task 3.1: Implement provider adapter and model factory ports

**Purpose:** Normalize model construction, discovery, usage, and errors without hiding support levels.

**Acceptance:**

- [ ] Native, OpenAI-compatible, manual, and unverified levels are represented.
- [ ] Factory instances are keyed by safe immutable configuration.
- [ ] Missing optional provider package produces an install hint.
- [ ] Errors normalize to stable auth/rate-limit/transient/invalid-model/protocol classes.
- [ ] Fake provider supports streaming, tools, structured output, usage, and injected failures.

**Verification:** provider contract suite against the fake adapter.

**Dependencies:** 2.1, 2.3.
**Likely files:** `src/rudder/providers/base.py`, `src/rudder/providers/factory.py`, `src/rudder/providers/errors.py`, `tests/fakes/provider.py`, `tests/contract/test_provider_contract.py`.
**Size:** M.

### Task 3.2: Implement credential resolution and redaction

**Purpose:** Resolve environment/keyring aliases without leaking values.

**Acceptance:**

- [ ] Provider config stores credential references only.
- [ ] Environment resolver fails with actionable missing-key error.
- [ ] Optional keyring path follows the approved Task 0.1 decision.
- [ ] Resolved values are registered with log/event/tool-output redaction.
- [ ] Exports and exception chains contain no fixture secret.

**Verification:** canary-secret tests over errors, events, logs, and exports.

**Dependencies:** 2.3, 3.1.
**Likely files:** `src/rudder/providers/credentials.py`, `src/rudder/runtime/redaction.py`, `tests/unit/test_credentials.py`, `tests/unit/test_redaction.py`.
**Size:** M.

### Task 3.3: Implement LLM Gateway adapter

**Purpose:** Preserve the highest-priority AutoConduck provider as a first-class Rudder provider.

**Acceptance:**

- [ ] Canonical `https://api.llmgateway.io/v1` configuration works.
- [ ] Streaming text and fragmented tool arguments normalize correctly.
- [ ] Structured-output support is tested or marked unsupported per model.
- [ ] Usage and pricing/model discovery responses normalize with provenance.
- [ ] Auth, rate-limit, transient, invalid-model, and protocol failures classify correctly.

**Verification:** fake HTTP contract suite; optional marked live smoke with user credentials.

**Dependencies:** 3.1–3.2.
**Likely files:** `src/rudder/providers/llmgateway.py`, `src/rudder/providers/openai_compatible.py`, `tests/contract/test_llmgateway.py`, `tests/fixtures/providers/llmgateway/`.
**Size:** M.

### Task 3.4: Implement DevPass and generic OpenAI-compatible adapters

**Purpose:** Retain DevPass and offer an explicit compatibility path without overstating support.

**Acceptance:**

- [ ] DevPass has a separate provider identity/configuration and contract fixtures.
- [ ] Generic endpoint requires explicit base URL and model declaration.
- [ ] Non-standard fields are ignored or mapped only when tested.
- [ ] Generic models default to manual/unverified auto-routing status.

**Verification:** adapter contract suite with distinct fake endpoints.

**Dependencies:** 3.3.
**Likely files:** `src/rudder/providers/devpass.py`, `src/rudder/providers/openai_compatible.py`, `tests/contract/test_devpass.py`, `tests/contract/test_openai_compatible.py`.
**Size:** M.

### Task 3.5: Implement LangChain provider registry

**Purpose:** Inherit compatible LangChain providers through explicit lazy factories and optional dependencies.

**Acceptance:**

- [ ] Registry lists installed/constructible/tested/auto-eligible levels separately.
- [ ] Provider SDKs import lazily.
- [ ] A manually configured supported integration constructs via documented LangChain APIs.
- [ ] Unsupported kwargs and provider mismatch fail before a paid call.

**Verification:** test two representative optional providers with fakes/mocks; no live credentials in default suite.

**Dependencies:** 3.1.
**Likely files:** `src/rudder/providers/registry.py`, `src/rudder/providers/langchain.py`, `tests/contract/test_langchain_providers.py`, `pyproject.toml`.
**Size:** M.

### Task 3.6: Implement evidence-bearing model catalog

**Purpose:** Merge maintained, discovered, evaluated, and user model metadata without inventing capability.

**Acceptance:**

- [ ] Field-level provenance and as-of times survive merging.
- [ ] Unknown capability never derives from name or price.
- [ ] Hard-budget routing can reject missing/stale price data.
- [ ] Manual selection remains possible for unmeasured models with clear status.
- [ ] Catalog snapshots have deterministic revision IDs.

**Verification:** merge precedence, stale data, and auto-eligibility fixture tests.

**Dependencies:** 3.1, 3.3–3.5.
**Likely files:** `src/rudder/providers/catalog.py`, `src/rudder/providers/models.py`, `src/rudder/providers/catalog_sources.py`, `tests/unit/test_model_catalog.py`, `tests/fixtures/catalog/`.
**Size:** L.

### Checkpoint D — Usable providers

- [ ] Fake provider and LLM Gateway contract paths support required agent features.
- [ ] DevPass and generic endpoints are isolated and honestly labelled.
- [ ] Optional provider breadth does not inflate the core install.
- [ ] Unknown models are manual, not silently auto-routed.

## 7. Phase 4 — Routing and budget control

### Task 4.1: Implement capability requirements and floor calculation

**Purpose:** Convert role, risk, tools, context, modality, mode, and escalation into deterministic requirements.

**Acceptance:**

- [ ] Initial role/risk floors match the approved spec.
- [ ] Economy never falls below hard minimum.
- [ ] Quality and escalation caps are enforced.
- [ ] Explicit tool/context/modality requirements are hard filters.
- [ ] Lead/model-generated hints cannot weaken hard requirements.

**Verification:** exhaustive table tests around all floor boundaries.

**Dependencies:** 2.1, 3.6.
**Likely files:** `src/rudder/routing/requirements.py`, `src/rudder/routing/capabilities.py`, `tests/unit/test_requirements.py`.
**Size:** M.

### Task 4.2: Implement deterministic selector and explanations

**Purpose:** Select by hard compatibility and mode-specific rank while explaining every exclusion.

**Acceptance:**

- [ ] `auto`, `economy`, `quality`, and `manual` match documented ordering.
- [ ] Stable keys resolve complete ties deterministically.
- [ ] Failed model and user exclusions are enforced.
- [ ] Empty pools return `route.no_qualified_model`, not a hidden fallback.
- [ ] Recorded explanation includes binding constraint and exclusion counts.

**Verification:** replayable routing fixtures and property tests for determinism.

**Dependencies:** 4.1.
**Likely files:** `src/rudder/routing/selector.py`, `src/rudder/routing/explain.py`, `tests/unit/test_selector.py`, `tests/fixtures/routing/`.
**Size:** M.

### Task 4.3: Implement attempt cost estimates

**Purpose:** Estimate total task-attempt cost rather than a single isolated call.

**Acceptance:**

- [ ] Estimate uses input, tool-result allowance, output allowance, expected calls, and cache price when supported.
- [ ] Missing price is distinct from zero price.
- [ ] Assumptions are present in the route/budget explanation.
- [ ] Decimal arithmetic and token rounding are consistent.

**Verification:** price fixtures including cached input, missing data, and boundary rounding.

**Dependencies:** 3.6, 4.1.
**Likely files:** `src/rudder/routing/estimates.py`, `src/rudder/domain/usage.py`, `tests/unit/test_estimates.py`.
**Size:** M.

### Task 4.4: Implement transactional budget reservations

**Purpose:** Prevent parallel task selection from overcommitting the hard budget.

**Acceptance:**

- [ ] Reserve/settle/release are atomic and idempotent.
- [ ] Actual, estimated actual, reserved, and available remain distinct.
- [ ] Concurrent reservation race cannot exceed the limit except recorded provider estimate overshoot.
- [ ] Lead continuation allowance is retained for child batches.
- [ ] Warning threshold emits without repetition.

**Verification:** barrier-based concurrent database tests and crash/retry cases.

**Dependencies:** 2.5, 4.3.
**Likely files:** `src/rudder/routing/budget.py`, `src/rudder/sessions/journal.py`, `tests/unit/test_budget.py`, `tests/integration/test_budget_concurrency.py`.
**Size:** L.

### Task 4.5: Combine selection and reservation into assignment service

**Purpose:** Ensure no model is considered assigned until its attempt budget is held and the decision is recorded.

**Acceptance:**

- [ ] Assignment snapshots config/catalog/health/budget inputs.
- [ ] Selection and reservation race retries from a fresh snapshot within a bound.
- [ ] Assignment event persists before model construction/call.
- [ ] Batch assignment either funds an affordable subset plus lead allowance or launches none incorrectly.

**Verification:** integration fixtures with concurrent catalog/budget state changes.

**Dependencies:** 4.2–4.4.
**Likely files:** `src/rudder/routing/assignment.py`, `src/rudder/routing/budget.py`, `src/rudder/runtime/event_bus.py`, `tests/integration/test_assignment.py`.
**Size:** M.

### Task 4.6: Implement task-bound model middleware and provider fallback

**Purpose:** Install the immutable assignment into every call and distinguish transport fallback from escalation.

**Acceptance:**

- [ ] Middleware never calls selector during a healthy attempt.
- [ ] Every call validates the assignment ID.
- [ ] Configured equivalent transport fallback creates a new assignment/event.
- [ ] Authentication/invalid-model errors do not retry pointlessly.
- [ ] Normalized usage settles the correct reservation once.

**Verification:** fake-provider sequences for healthy, rate-limit, outage, auth, malformed, and duplicate callback paths.

**Dependencies:** 1.2, 3.1, 4.5.
**Likely files:** `src/rudder/runtime/model_middleware.py`, `src/rudder/providers/fallback.py`, `src/rudder/routing/assignment.py`, `tests/integration/test_model_binding.py`, `tests/integration/test_provider_fallback.py`.
**Size:** L.

### Checkpoint E — Economic routing

- [ ] Every model call maps to a persisted assignment.
- [ ] Auto/manual/mode behavior is deterministic and explainable.
- [ ] Concurrent work cannot over-reserve the run budget.
- [ ] Transport fallback and task escalation are visibly different.

## 8. Phase 5 — Tools, permissions, and extensions

### Task 5.1: Assemble the default DeepAgents tool surface

**Purpose:** Use most useful framework tools while keeping one registry and profile-aware visibility.

**Acceptance:**

- [ ] List/glob/grep/read/write/edit/execute/todos/task/skills/memory and `ask_user` have stable Rudder metadata.
- [ ] Duplicate names and unknown schemas fail at startup.
- [ ] Each tool declares source, version, side effects, approvals, and profile visibility.
- [ ] Large output becomes a redacted artifact plus bounded excerpt.

**Verification:** registry and output-boundary contract tests.

**Dependencies:** 1.1, 2.2.
**Likely files:** `src/rudder/tools/registry.py`, `src/rudder/tools/assembly.py`, `src/rudder/tools/artifacts.py`, `tests/unit/test_tool_registry.py`, `tests/contract/test_deepagents_tools.py`.
**Size:** L.

### Task 5.2: Enforce virtual workspace filesystem boundaries

**Purpose:** Root model filesystem operations to the selected workspace.

**Acceptance:**

- [ ] Normal, absolute, traversal, symlink, and Windows junction cases are tested.
- [ ] Outside-workspace grants require explicit canonical paths.
- [ ] Sensitive-file patterns apply before content enters context.
- [ ] Writes record task/path and before/after hashes.

**Verification:** platform-specific temp workspace adversarial tests.

**Dependencies:** 5.1.
**Likely files:** `src/rudder/tools/filesystem.py`, `src/rudder/tools/policy.py`, `tests/integration/test_filesystem_boundary.py`, `tests/unit/test_sensitive_paths.py`.
**Size:** L.

### Task 5.3: Implement command execution policy and approvals

**Purpose:** Secure the shell and other side-effecting tools not covered by filesystem permissions.

**Acceptance:**

- [ ] PowerShell and POSIX invocations preserve structured working directory/arguments where possible.
- [ ] Action classes and default allow/ask/reject behavior match feature contracts.
- [ ] Decisions support once/session/narrow-project-rule/edit/reject.
- [ ] Edited command becomes a new request.
- [ ] Non-interactive approval-required exits without hanging.

**Verification:** command policy table tests plus harmless subprocess integration tests on Windows/Linux.

**Dependencies:** 2.4, 5.1–5.2.
**Likely files:** `src/rudder/tools/execution.py`, `src/rudder/tools/approvals.py`, `src/rudder/domain/security.py`, `tests/unit/test_execution_policy.py`, `tests/integration/test_approvals.py`.
**Size:** L.

### Task 5.4: Implement `ask_user` interrupts

**Purpose:** Let lead/children request missing input through durable structured interrupts.

**Acceptance:**

- [ ] Question, options, reason, task, and blocking scope persist.
- [ ] Answer resumes only the correct waiting graph.
- [ ] Cancellation and invalid/stale answer behavior are explicit.
- [ ] Resume restores pending questions without granting an answer.

**Verification:** checkpointed lead and child interrupt scenarios.

**Dependencies:** 2.6, 5.1.
**Likely files:** `src/rudder/tools/ask_user.py`, `src/rudder/runtime/interrupts.py`, `tests/integration/test_questions.py`.
**Size:** M.

### Task 5.5: Implement trusted profiles, skills, and memory loading

**Purpose:** Support built-in/user/project customization without executing untrusted project content.

**Acceptance:**

- [ ] Precedence and frontmatter validation match feature contracts.
- [ ] Project sources stay inactive until trusted.
- [ ] Running task retains source revision after files change.
- [ ] Skills/memory context is bounded and source-labelled.
- [ ] A child cannot expand global permissions/depth/budget from its profile.

**Verification:** trusted/untrusted fixture trees and reload tests.

**Dependencies:** 2.4, 5.1.
**Likely files:** `src/rudder/agents/profile_loader.py`, `src/rudder/tools/skills.py`, `src/rudder/tools/memory.py`, `tests/unit/test_profile_loader.py`, `tests/integration/test_extension_trust.py`.
**Size:** L.

### Task 5.6: Add explicit MCP/custom tool loading boundary

**Purpose:** Allow useful extensions without making them an implicit core dependency.

**Acceptance:**

- [ ] Extensions are opt-in and list permissions/side effects before activation.
- [ ] Unknown side effect is treated as write-capable and approval-worthy.
- [ ] Tool name collisions require explicit resolution.
- [ ] Secrets pass out-of-band where supported and are redacted.
- [ ] Disabled/broken extension cannot prevent core startup unless selected as required.

**Verification:** fake MCP/custom tool fixtures for read, write, unknown, collision, and failure.

**Dependencies:** 5.1, 5.3, 5.5.
**Likely files:** `src/rudder/tools/extensions.py`, `src/rudder/tools/mcp.py`, `tests/contract/test_extensions.py`, `tests/fixtures/extensions/`.
**Size:** M.

### Checkpoint F — Safe useful tools

- [ ] Default tool surface supports daily coding without duplicate abstractions.
- [ ] Filesystem and shell boundaries are enforced outside prompts.
- [ ] Project extensions cannot activate before trust.
- [ ] Questions/approvals survive checkpoints.

## 9. Phase 6 — Profiles, task lifecycle, scheduler, and lead

### Task 6.1: Implement built-in profile definitions

**Purpose:** Encode lead, general, explorer, implementer, tester, reviewer, and researcher postures.

**Acceptance:**

- [ ] Tool sets, role floors, expected calls, output schemas, and write posture match `FEATURES.md`.
- [ ] No profile hardcodes a commercial model.
- [ ] Only lead delegates by default.
- [ ] Reviewer/explorer/researcher built-in file tools are read-only.
- [ ] Execute-capable tester/reviewer are scheduled as write-capable.

**Verification:** snapshot/schema tests and cross-check with tool registry.

**Dependencies:** 4.1, 5.1, 5.5.
**Likely files:** `src/rudder/agents/profiles.py`, `src/rudder/agents/prompts.py`, `tests/unit/test_profiles.py`.
**Size:** M.

### Task 6.2: Implement task validation, fingerprint, and registry

**Purpose:** Turn model-authored requests into safe Rudder-owned task specs.

**Acceptance:**

- [ ] Empty/oversized/profile/depth/dependency/scope/background errors are stable.
- [ ] IDs and requirements are generated by Rudder.
- [ ] Dependency cycles are rejected deterministically.
- [ ] Fingerprint includes normalized request and workspace revision.
- [ ] Exhausted fingerprint blocks a third automatic attempt/task loop.

**Verification:** table and graph-cycle tests.

**Dependencies:** 2.1, 2.5, 6.1.
**Likely files:** `src/rudder/runtime/task_validation.py`, `src/rudder/runtime/task_registry.py`, `src/rudder/runtime/fingerprint.py`, `tests/unit/test_task_validation.py`, `tests/unit/test_task_registry.py`.
**Size:** M.

### Task 6.3: Implement scheduler, dependencies, and three-child semaphore

**Purpose:** Queue and execute bounded child work independently of prompt compliance.

**Acceptance:**

- [ ] Config accepts only 1–3.
- [ ] Ready tasks dispatch in priority/creation order.
- [ ] Dependencies gate launch and propagate blocked outcomes.
- [ ] A fourth task queues; maximum active never exceeds configured limit.
- [ ] Approval waits release execution slots without losing reservations.

**Verification:** deterministic barriers and scheduler property tests.

**Dependencies:** 1.3, 4.5, 6.2.
**Likely files:** `src/rudder/runtime/scheduler.py`, `src/rudder/runtime/task_registry.py`, `tests/unit/test_scheduler.py`, `tests/integration/test_scheduler_concurrency.py`.
**Size:** L.

### Task 6.4: Implement shared-workspace write leases

**Purpose:** Prevent concurrent write-capable lead/child activity.

**Acceptance:**

- [ ] Edit/write/execute/custom-unknown postures require a lease.
- [ ] Read-only children remain concurrent.
- [ ] Lead write tools wait while a child lease is held.
- [ ] Cancellation/crash releases or recovers stale leases safely.
- [ ] Non-Git workspaces behave safely without pretending isolation.

**Verification:** lead/child and child/child race tests with fake tools.

**Dependencies:** 5.1, 6.3.
**Likely files:** `src/rudder/runtime/leases.py`, `src/rudder/runtime/scheduler.py`, `src/rudder/tools/assembly.py`, `tests/integration/test_write_leases.py`.
**Size:** L.

### Task 6.5: Implement attempt execution and structured result evaluation

**Purpose:** Replace the spike with the production compiled task graph.

**Acceptance:**

- [ ] Validate/assign/acquire/execute/evaluate/return nodes use canonical state.
- [ ] Selected profile DeepAgent receives bounded context and fixed assignment.
- [ ] Success requires structured result plus required verification.
- [ ] Compact result returns to lead; full transcript/events remain by ID.
- [ ] Blocked, budget-blocked, cancelled, failed, and succeeded remain distinct.

**Verification:** actual compiled graph with fake profiles/models/tools.

**Dependencies:** 4.6, 5.1–5.4, 6.1–6.4.
**Likely files:** `src/rudder/agents/task_graph.py`, `src/rudder/agents/result_evaluator.py`, `src/rudder/runtime/task_executor.py`, `tests/integration/test_task_graph.py`, `tests/contract/test_task_result.py`.
**Size:** L.

### Task 6.6: Implement deterministic failure monitor

**Purpose:** Detect genuine attempt failure without punishing healthy long tool loops.

**Acceptance:**

- [ ] Three identical calls, two consecutive errors, same normalized error twice, and boundaries trigger.
- [ ] One error or corrected retry does not trigger.
- [ ] No file-count or generic turn-count escalation exists.
- [ ] Normalization redacts secrets and ignores unstable values where documented.
- [ ] Permission/user-input blocks do not count as model failure.

**Verification:** sequence table tests including false-positive controls.

**Dependencies:** 2.2, 5.1, 6.5.
**Likely files:** `src/rudder/runtime/failure_monitor.py`, `src/rudder/domain/tasks.py`, `tests/unit/test_failure_monitor.py`.
**Size:** M.

### Task 6.7: Implement one escalation and return-to-lead

**Purpose:** Recover from under-tiering once without an automatic retry ladder.

**Acceptance:**

- [ ] Attempt-one failure settles usage and preserves workspace state.
- [ ] Attempt two excludes failed model and raises floor by configured 0.15 cap.
- [ ] Failure handoff is bounded and evidence-bearing.
- [ ] Unaffordable/no-candidate escalation becomes structured blocked result.
- [ ] Attempt-two failure returns to lead and fingerprint prevents automatic attempt three.

**Verification:** task graph sequences for success-first, success-second, fail-twice, blocked, cancel, and provider fallback distinction.

**Dependencies:** 4.5, 6.5–6.6.
**Likely files:** `src/rudder/agents/task_graph.py`, `src/rudder/runtime/escalation.py`, `src/rudder/runtime/fingerprint.py`, `tests/integration/test_escalation.py`.
**Size:** M.

### Task 6.8: Build the production lead graph and delegation controls

**Purpose:** Deliver “just prompt, we'll orchestrate” with a lead that remains fully capable.

**Acceptance:**

- [ ] Lead can complete a direct fake coding flow without delegation.
- [ ] `auto`, `ask`, and `off` delegation are runtime-enforced.
- [ ] Multiple `task` calls use the scheduler and compiled profiles.
- [ ] Explicit user model/agent/delegation/write constraints are applied to the current instruction.
- [ ] Lead synthesizes returned/blocked tasks without automatic resubmission loops.

**Verification:** scripted integration conversations covering direct, parallel, user-forced, user-forbidden, and failure-return paths.

**Dependencies:** 5.4, 6.1–6.7.
**Likely files:** `src/rudder/agents/lead.py`, `src/rudder/agents/prompts.py`, `src/rudder/runtime/run_controller.py`, `tests/integration/test_lead.py`, `tests/integration/test_delegation_controls.py`.
**Size:** L.

### Checkpoint G — Headless Rudder core

- [ ] A prompt can complete directly or through up to three subagents.
- [ ] Models are fixed by assignment, budgets are enforced, and write overlap is impossible.
- [ ] One escalation works and second failure returns to lead.
- [ ] Explicit user constraints override autonomous delegation preferences.

## 10. Phase 7 — Sessions, CLI, and TUI

### Task 7.1: Implement session lifecycle, resume, compaction, and export

**Purpose:** Make long-running harness work recoverable and inspectable.

**Acceptance:**

- [ ] Active/idle/interrupted/completed/archived transitions are valid.
- [ ] Resume restores lead/task/assignment/budget/question state without duplicate calls.
- [ ] Compaction preserves all fields listed in `FEATURES.md`.
- [ ] Export is redacted and includes tasks/routes/usage/verification.
- [ ] Process lock prevents concurrent mutation of one session.

**Verification:** crash/resume/compact/export integration suite.

**Dependencies:** 2.6, 3.2, 6.8.
**Likely files:** `src/rudder/sessions/service.py`, `src/rudder/sessions/compaction.py`, `src/rudder/sessions/export.py`, `tests/integration/test_sessions.py`, `tests/integration/test_export.py`.
**Size:** L.

### Task 7.2: Implement CLI command contract and exit codes

**Purpose:** Expose interactive, print, JSONL, model, budget, session, auth, and config entrypoints.

**Acceptance:**

- [ ] Flags and precedence match `SPEC.md`.
- [ ] Print stdout/stderr separation is exact.
- [ ] JSONL emits only versioned event objects and one terminal event.
- [ ] Completion/failure/blocked/cancel/usage have documented exit codes.
- [ ] No command starts a proxy/server or recognizes old aliases.

**Verification:** subprocess tests on Windows/Linux with fake provider.

**Dependencies:** 6.8, 7.1.
**Likely files:** `src/rudder/cli/main.py`, `src/rudder/cli/commands.py`, `src/rudder/cli/render.py`, `tests/e2e/test_cli.py`, `docs/rudder/CLI.md`.
**Size:** L.

### Task 7.3: Build conversation-first TUI shell and event projection

**Purpose:** Render the lead conversation and events without coupling runtime to Textual.

**Acceptance:**

- [ ] Main transcript/editor/footer operate with fake events.
- [ ] UI state reconstructs from snapshot plus event stream.
- [ ] Tool/task events may collapse but errors/approvals remain visible.
- [ ] Resize, keyboard navigation, screen readers/contrast, and terminal-width fallbacks are tested.
- [ ] Runtime modules do not import Textual.

**Verification:** Textual pilot/component tests and manual Windows smoke.

**Dependencies:** 2.2, 6.8, 7.1.
**Likely files:** `src/rudder/tui/app.py`, `src/rudder/tui/projection.py`, `src/rudder/tui/widgets/chat.py`, `src/rudder/tui/widgets/composer.py`, `tests/integration/test_tui_shell.py`.
**Size:** L.

### Task 7.4: Add agent rail, route, and budget views

**Purpose:** Make orchestration and economics legible while work runs.

**Acceptance:**

- [ ] Rail shows task parentage, profile, fixed model, true state, elapsed, and cost.
- [ ] Route view renders the recorded decision and lineage rather than recomputing.
- [ ] Budget view separates authoritative actual, estimate, reserve, available, and lead allowance.
- [ ] Queued, approval-waiting, blocked, cancelled, escalated, and returned states are distinct.
- [ ] Empty/unknown data is explicit, never fabricated.

**Verification:** projection fixtures and component snapshots.

**Dependencies:** 7.3.
**Likely files:** `src/rudder/tui/widgets/agents.py`, `src/rudder/tui/widgets/route.py`, `src/rudder/tui/widgets/budget.py`, `src/rudder/tui/projection.py`, `tests/integration/test_tui_panels.py`.
**Size:** L.

### Task 7.5: Add interactive commands, approvals, questions, and steering

**Purpose:** Complete user control of active work.

**Acceptance:**

- [ ] Required slash commands in `SPEC.md` parse and dispatch.
- [ ] Questions and approvals focus the correct task and resume correctly.
- [ ] Whole-run cancellation is safe in foreground mode.
- [ ] Individual steering/cancel appears only when background adapter supports it.
- [ ] New input classification is visible before replacing active work.

**Verification:** TUI interaction tests plus manual cancellation/resume scenarios.

**Dependencies:** 5.3–5.4, 7.3–7.4, and 1.4 if background is enabled.
**Likely files:** `src/rudder/tui/commands.py`, `src/rudder/tui/app.py`, `src/rudder/tui/widgets/interrupts.py`, `tests/integration/test_tui_commands.py`, `tests/e2e/test_tui_flow.py`.
**Size:** L.

### Checkpoint H — Complete daily-use harness

- [ ] Interactive, print, and JSONL modes share one runtime/event truth.
- [ ] Agent/model/cost/task state is visible and accurate.
- [ ] Approvals, questions, cancellation, compaction, resume, and export work.
- [ ] Windows and Linux end-to-end fake-provider flows pass.

## 11. Phase 8 — Evaluation, hardening, and stable release

### Task 8.1: Build deterministic routing/orchestration evaluation runner

**Purpose:** Compare policies without relying on agent self-report.

**Acceptance:**

- [ ] Fixture schema captures repository, prompt, allowed tools, oracle, and route invariants.
- [ ] Runner compares auto, fixed economy, fixed quality, serial, and no-delegation policies where applicable.
- [ ] Results include completion, total cost, wall time, escalations, interrupts, and safety/state defects.
- [ ] Provider-live evaluation is opt-in and results identify model/catalog revisions.

**Verification:** seeded fake suite gives reproducible report.

**Dependencies:** Checkpoint H.
**Likely files:** `evals/schema.py`, `evals/runner.py`, `evals/report.py`, `tests/unit/test_eval_runner.py`, `scripts/eval_routing.py`.
**Size:** L.

### Task 8.2: Curate the approved coding fixture set

**Purpose:** Build representative trivial, routine, bounded, complex, high-risk, parallel, and failure tasks.

**Acceptance:**

- [ ] At least 50 fixtures after approval, balanced across task/role/risk categories.
- [ ] Every fixture has an executable or independently reviewable oracle.
- [ ] Parallel-eligible fixtures identify truly independent work.
- [ ] Fixtures include Windows/path/shell and provider failure cases.
- [ ] No copyrighted/private project material is included without authorization.

**Verification:** schema validation, oracle mutation tests, and human review sample.

**Dependencies:** 8.1.
**Likely files:** `evals/fixtures/` (data task), `evals/manifest.toml`, `tests/test_eval_fixtures.py`.
**Size:** L/content-heavy.

### Task 8.3: Run quality, cost, and latency gates; tune only from evidence

**Purpose:** Validate product intent and replace hypothetical floors/expected-call values.

**Acceptance:**

- [ ] Auto completion is within the approved margin of fixed quality.
- [ ] Cost per completed task and parallel wall time meet approved gates.
- [ ] Changes to floors/profile estimates cite evaluation deltas.
- [ ] No tuning weakens hard safety, tool, context, or modality requirements.
- [ ] Full raw and summarized results are versioned with catalog/model revisions.

**Verification:** two clean evaluation runs within documented variance bounds.

**Dependencies:** 8.2.
**Likely files:** `src/rudder/routing/defaults.py`, `src/rudder/agents/profiles.py`, `evals/results/`, `docs/rudder/EVALUATION.md`.
**Size:** L/experimental.

### Task 8.4: Security, recovery, and destructive-action hardening

**Purpose:** Adversarially validate workspace, command, trust, extension, secret, and persistence boundaries.

**Acceptance:**

- [ ] Traversal/symlink/junction, command injection, untrusted extension, secret exfiltration, and approval-bypass suites pass.
- [ ] Crash points around assignment/reservation/tool/checkpoint do not duplicate work or lose cost truth.
- [ ] No critical/high unresolved finding remains.
- [ ] Threat model and documented limitations are current.

**Verification:** dedicated security suite and independent code review.

**Dependencies:** 8.1; can run in parallel with 8.2–8.3 after features freeze.
**Likely files:** `tests/security/`, `docs/rudder/THREAT_MODEL.md`, affected fixes limited per finding.
**Size:** L.

### Task 8.5: Performance and context hardening

**Purpose:** Bound overhead introduced by orchestration and observability.

**Acceptance:**

- [ ] Direct-run startup/turn overhead has an approved local baseline.
- [ ] Event persistence and TUI projections remain responsive under three active children.
- [ ] Large tool outputs and child results respect context bounds.
- [ ] Database growth/retention behavior is measured.
- [ ] No optimization bypasses journal, safety, or assignment invariants.

**Verification:** reproducible local benchmarks with thresholds documented, not timing-flaky unit assertions.

**Dependencies:** Checkpoint H.
**Likely files:** `benchmarks/`, `docs/rudder/PERFORMANCE.md`, targeted implementation files based on profiles.
**Size:** M.

### Task 8.6: Packaging, installation, docs, and release candidate

**Purpose:** Produce a Windows/Linux release candidate with honest support claims.

**Acceptance:**

- [ ] Clean installs and uninstall on both platforms.
- [ ] Wheel contains only intended Rudder code/assets.
- [ ] `rudder` first-run, provider auth, models, session, and troubleshooting docs work.
- [ ] Provider support levels and experimental features are labelled.
- [ ] Licenses/notices cover DeepAgents/LangGraph/provider integrations.
- [ ] No old command/config/user-data migration claim exists.

**Verification:** release CI, fresh-machine/container smoke, artifact inspection, documentation command checks.

**Dependencies:** 8.3–8.5.
**Likely files:** `pyproject.toml`, `README.md`, `docs/`, `.github/workflows/release.yml`, `scripts/release_check.py`.
**Size:** L.

### Final checkpoint — Stable Rudder

- [ ] All `SPEC.md` acceptance criteria pass.
- [ ] Evaluation gates pass on approved fixtures.
- [ ] No critical safety/data-loss issue is open.
- [ ] Windows and Linux release artifacts pass end-to-end smoke.
- [ ] LLM Gateway passes streaming/tool/structured-output contract expectations.
- [ ] Background agents and worktrees are either validated, clearly experimental, or absent from stable claims.
- [ ] ADRs and support matrix match shipped behavior.

## 12. Post-stable / isolated features

### Task P.1: Worktree-isolated writers

Implement verified Git worktree creation, task branches, patch/commit artifacts, conflict checks, approval, and cleanup. Never copy/discard uncommitted user work silently. Fall back to the shared single-writer scheduler.

**Dependencies:** 6.4, 7.1, stable Git behavior tests on Windows/Linux.
**Release status:** Optional until separately accepted.

### Task P.2: Background task executor

Productionize the preview adapter only if Task 1.4 proves lifecycle, checkpoint, update, and cancellation behavior. It must use the same task/assignment/budget/result contracts and global semaphore.

**Dependencies:** 1.4, 6.5–6.7, 7.5.
**Release status:** Experimental unless separately accepted.

### Task P.3: Editor protocol

Add ACP or another editor-facing protocol as a presentation adapter over `RunController` and events. It must not introduce a proxy plane or a second runtime truth.

**Dependencies:** stable CLI/TUI contracts.
**Release status:** Post-stable.

## 13. Risk register and stop conditions

| Risk | Detection | Response / stop condition |
|---|---|---|
| DeepAgents cannot bind per-child model before first call | Task 1.2 contract fails | Stop downstream runtime work; revise adapter/ADR. Do not fake task-bound routing. |
| Nested cancellation/checkpoint behavior loses task truth | Tasks 1.3 or 2.6 fail | Keep background/parallel feature disabled until a recoverable boundary exists. |
| LLM Gateway tool streaming is incompatible | Task 3.3 fails | Mark unsupported path precisely; do not claim first-class completion until resolved. |
| Reservations race or duplicate charges | Tasks 4.4–4.6 fail | Block parallel paid execution; keep fake/evaluation mode only. |
| Shared writers can overlap | Task 6.4 fails | Force max write concurrency to one globally before any release. |
| Auto routing has poor completion economics | Task 8.3 misses gates | Do not market automatic savings; retune with evidence or ship manual/fixed modes only. |
| Preview async API changes | Contract suite fails on upgrade | Pin prior supported version or disable background adapter without affecting foreground. |
| Scope drifts toward old proxy architecture | Root server/shim dependency appears | Reject change unless a new product ADR explicitly changes scope. |

## 14. Working rules for implementation agents

1. Read the relevant spec, architecture section, feature contract, and accepted ADR before editing.
2. Query Graphify before unfamiliar repository exploration, then inspect only located files.
3. State assumptions and exact success checks in the task update.
4. Keep framework/provider types at adapters; do not leak them into domain modules.
5. Prefer fake providers and deterministic barriers over paid calls and sleeps.
6. Do not add a dependency, public config key, event variant, or CLI flag without checking the approved contract.
7. Do not consult or copy legacy code unless the task explicitly identifies the concept to reuse.
8. Keep each implementation change within the listed task; split a task if it exceeds roughly five substantive source files.
9. Run focused tests, relevant integration tests, `graphify update .`, and diff checks before marking complete.
10. Record unexpected framework behavior in an ADR/contract test, not only in a code comment.
