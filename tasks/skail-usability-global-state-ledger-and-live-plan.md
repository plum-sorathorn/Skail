# Skail usability, global state, ledger accuracy, themes, and live validation plan

Status: **Ready for review; no implementation or provider-live verification is claimed.**

## Objective

Make Skail reliable in ordinary interactive use by fixing the model picker, guaranteeing a usable
or explicitly blocked lead-agent state, moving all Skail-owned runtime state out of repositories,
loading global and workspace instructions together, making displayed spend match measured usage,
adding three intentional mint/pistachio themes with real screenshots, and validating the completed
product through a bounded live-provider matrix.

This plan does not replace `tasks/skail-adaptive-orchestration-and-release-plan.md`. It is a
focused remediation plan that should be completed before another release candidate is cut.

## Confirmed current behavior

- `ModelPickerOverlay` keeps search and selection as separate interaction concepts. It renders the
  results inside `VerticalScroll`, caps the rendered list at 40 rows, and binds printable keys such
  as `a`, `j`, and `k` to commands. Those bindings conflict with typing while the search input is
  focused.
- Startup can enter `selection_required`, queue a prompt, and wait indefinitely for a manual model
  choice. Later lead routing can also return `RouteFailure`; the controller currently returns an
  empty `RunResult.output` for that path, so the user can see no response.
- Most durable state is already under `~/.skail`, but the CLI still creates repository-local
  `.skail/approvals.sqlite` and `.skail/questions.sqlite`; tool assembly creates
  `.skail/artifacts`, the filesystem boundary creates a local lock, project config is read from
  `.skail/config.toml`, and project profiles are read from `.skail/agents/.../AGENTS.md`.
- The root instruction files requested here are not assembled today. Existing `AGENTS.md` loading
  is profile-specific, not a global `~/.skail/AGENTS.md` plus working-directory `AGENTS.md` stack.
- Generic LangChain usage records token counts with a zero estimated cost. During settlement, any
  non-authoritative usage is replaced by `max(recorded_cost, estimated_attempt_cost)`. A short call
  can therefore be displayed as the full conservative reservation instead of its token-derived
  cost.
- The TUI has fixed Dark, Light, and System themes. Theme preview is not distinct from committing,
  the selection is not persisted as a user preference, and the screenshot script always captures
  Dark.
- Pytest has an opt-in `provider_live` marker and `--run-provider-live` switch, but there are no
  provider-live test modules. The repository `.env` is not loaded by that test machinery.

## Architecture decisions for this work

1. **One physical Skail directory per user.** `~/.skail` is the only directory named `.skail` that
   Skail creates. Workspace-specific state lives below
   `~/.skail/workspaces/<workspace-identity>/`, where the identity is derived from the existing
   canonical workspace identity rather than a user-controlled path fragment.
2. **No silent weakening of the lead capability floor.** Skail automatically chooses the strongest
   enabled candidate that satisfies the lead requirements. If none qualifies, it emits an
   actionable visible error listing the required floor and the best available candidates. It does
   not run an underqualified lead merely to avoid an error.
3. **One keyboard context in the model picker.** The filter input stays focused. Printable keys
   always edit the query; Up/Down changes the highlighted result; Enter selects it; Ctrl+Space
   toggles the highlighted model; Ctrl+Shift+A toggles the filtered set; Escape closes. No Tab or
   mouse transition is required.
4. **No model-list scrollbar.** Results render into a viewport-sized, non-scrollable container.
   Moving the highlight changes the rendered window. Text such as `↑ 12 more` / `↓ 8 more` may
   communicate hidden rows, but no scroll track or scroll thumb is rendered.
5. **Both instruction files are additive and source-labelled.** The order is built-in Skail rules,
   global `~/.skail/AGENTS.md`, then trusted `<workspace>/AGENTS.md`. The workspace file has higher
   precedence on behavioral conflicts but cannot relax safety, approval, budget, or permission
   policy. If the workspace is untrusted, Skail reports that its `AGENTS.md` was found but ignored.
6. **Reservations and spend are different values.** Preflight reservation remains conservative.
   Once token counts exist, estimated actual spend is computed from the assignment's frozen trusted
   prices. The full reservation is used only when usage cannot be measured, and is labelled as an
   estimate. Missing cost is never represented as a genuine zero.
7. **Onboarding is device-global.** Provider choice, selected model, enabled models, theme, and an
   onboarding schema/version receipt persist globally. A new workspace may still require a trust
   decision, but it does not repeat provider/theme onboarding. Secrets are never written to TOML,
   JSON, SQLite diagnostics, screenshots, or test output; an entered key is stored only through the
   OS credential store, with environment variables remaining the first explicit override.
8. **Live tests are bounded and opt-in.** The root `.env` is read only when the explicit live runner
   is invoked. Only an allowlist of credential names is imported, values are never printed, and a
   default cumulative provider-spend ceiling of **$1.00** fails closed unless the user supplies a
   different cap.

The global-state, instruction-precedence, and credential-persistence decisions change accepted
public contracts. Record them in ADR 0007 and update the specification in the same implementation
phase before code changes land.

## Theme directions

All three directions keep status/error colors semantically distinct and use green as identity, not
as the only state signal. Each direction must expand into the existing 36 semantic tokens and pass
contrast checks in the actual terminal UI.

### Option A: Pistachio Night

A dark botanical workshop: restrained charcoal-green surfaces with a pale pistachio focus color.
This is the most dramatic option and preserves the low-glare character of the current Dark theme.

| Role | Color |
|---|---|
| Background | `#101713` |
| Surface | `#18221C` |
| Raised surface | `#203029` |
| Primary text | `#E8F0E8` |
| Muted text | `#A8B8AA` |
| Accent / focus | `#9FD3A9` |
| Soft accent | `#294133` |
| Selection | `#2D4A39` |

Signature: the active model and focus boundary read as a thin pistachio drafting line against deep
green-black, rather than a neon terminal glow.

### Option B: Pistachio Paper

A warm, light editorial palette inspired by seed packets and uncoated botanical paper. It is the
softest and most overtly pastel option.

| Role | Color |
|---|---|
| Background | `#F1F3E7` |
| Surface | `#FAFBF4` |
| Raised surface | `#E4E9D8` |
| Primary text | `#243128` |
| Muted text | `#667468` |
| Accent / focus | `#648F5A` |
| Soft accent | `#DDE8C9` |
| Selection | `#D4E4CC` |

Signature: selected rows feel like translucent pistachio highlighter on paper, while rules and
labels stay typographic and quiet.

### Option C: Mint Porcelain

A cooler, cleaner mint scheme with porcelain surfaces and eucalyptus accents. It is brighter and
more technical than Pistachio Paper without falling into cyan-heavy dashboard styling.

| Role | Color |
|---|---|
| Background | `#E9F0EB` |
| Surface | `#F7FAF7` |
| Raised surface | `#DCE8E1` |
| Primary text | `#1F2E28` |
| Muted text | `#61736A` |
| Accent / focus | `#468E71` |
| Soft accent | `#CFE7DA` |
| Selection | `#C7DED2` |

Signature: mint is concentrated in active rails, links, and focus boundaries; the main transcript
remains porcelain-white for long-session readability.

## Dependency graph

```text
Contract / ADR
    |
    +-- Global path resolver -- Runtime-state relocation -- One-time onboarding
    |                                                    |
    |                                                    +-- Theme persistence
    |
    +-- Instruction loader -- Lead/child prompt integration
    |
    +-- Lead eligibility -- Visible no-lead failure -- Model picker completion
    |
    +-- Usage contract -- Token-priced settlement -- Ledger projection
    |
    +-- Theme tokens/picker -- Three deterministic screenshots
                                                     |
All offline checkpoints -----------------------------+
    |
Live runner -- Provider-live feature matrix -- Fix/retest loop -- Release gates
```

## Implementation tasks

### Task 0: Lock the changed contracts in ADR 0007

**Description:** Record the single-global-directory layout, workspace namespace, onboarding and
credential rules, root-instruction precedence, lead fallback behavior, and measured-versus-reserved
cost semantics before implementation.

**Acceptance criteria:**

- `~/.skail` is the only Skail-created `.skail` directory in the accepted architecture.
- Migration and rollback behavior for existing repository-local state is explicit.
- Global/workspace instruction precedence and trust behavior are explicit.
- Onboarding persistence does not authorize plaintext secret storage.

**Verification:**

- `rtk pytest tests/unit/test_documentation_contracts.py -q`
- Review links and terminology against `SPEC.md`, `ARCHITECTURE.md`, and `FEATURES.md`.

**Dependencies:** None

**Files likely touched:**

- `docs/decisions/0007-global-state-and-instruction-precedence.md`
- `docs/skail/SPEC.md`
- `docs/skail/ARCHITECTURE.md`
- `docs/skail/FEATURES.md`

**Estimated scope:** Medium

### Task 1: Add the global workspace-state path contract

**Description:** Add one canonical path service for user state and workspace-scoped state. Derive
the workspace namespace from the existing canonical identity, validate every resolved path remains
under `~/.skail`, and make path functions injectable for tests.

**Acceptance criteria:**

- Two workspaces receive stable, distinct namespaces below the same user data root.
- Moving between subdirectories of the same canonical workspace does not create a second namespace.
- No returned runtime/config/artifact path is inside the working directory.

**Verification:**

- `rtk pytest tests/unit/test_config.py tests/unit/test_trust.py -q`

**Dependencies:** Task 0

**Files likely touched:**

- `src/skail/config/paths.py`
- `src/skail/domain/security.py`
- `tests/unit/test_config.py`
- `tests/unit/test_trust.py`

**Estimated scope:** Medium

### Task 2: Relocate CLI-owned workspace state

**Description:** Move approvals, questions, and project-scoped configuration into the global
workspace namespace. Stop reading or creating `<workspace>/.skail/config.toml`. Import recognized
legacy files once into the global namespace without deleting or modifying the legacy directory.

**Acceptance criteria:**

- Normal TUI, print, JSONL, config, and session commands create no working-directory `.skail`.
- Existing valid local config/state can be imported once, with a source and migration receipt.
- Conflicting global and legacy data fails visibly instead of silently overwriting either copy.

**Verification:**

- `rtk pytest tests/unit/test_cli_boot_split.py tests/unit/test_tui_headless_parity.py tests/e2e/test_cli_e2e.py -q`

**Dependencies:** Task 1

**Files likely touched:**

- `src/skail/cli/main.py`
- `src/skail/config/loader.py`
- `tests/unit/test_cli_boot_split.py`
- `tests/unit/test_tui_headless_parity.py`
- `tests/e2e/test_cli_e2e.py`

**Estimated scope:** Medium

### Task 3: Relocate tool artifacts and filesystem locks

**Description:** Pass the workspace state directory explicitly through runtime/tool assembly, then
place artifacts and boundary locks there instead of below the repository. Keep the actual tool
filesystem rooted at the working directory.

**Acceptance criteria:**

- Tool artifacts and locks are global-state files but retain workspace/task ownership metadata.
- Filesystem reads/writes remain confined to the real workspace and do not gain access to global
  Skail state.
- Shared and isolated worktree modes create no `.skail` inside source or temporary worktrees.

**Verification:**

- `rtk pytest tests/integration/test_filesystem_boundary.py tests/security/test_workspace_boundaries.py tests/unit/test_toolcall_missing_usage_repro.py -q`

**Dependencies:** Task 2

**Files likely touched:**

- `src/skail/runtime/run_controller.py`
- `src/skail/tools/assembly.py`
- `src/skail/tools/filesystem.py`
- `tests/integration/test_filesystem_boundary.py`
- `tests/security/test_workspace_boundaries.py`

**Estimated scope:** Medium

### Task 4: Persist one-time onboarding without plaintext secrets

**Description:** Add a versioned global onboarding receipt and secure credential resolver. Resolve
credentials in this order: explicit environment variable, OS credential store, interactive entry.
Persist non-secret choices globally and write an interactively entered key only through the OS
credential store. Project trust remains a separate per-workspace decision.

**Acceptance criteria:**

- Completing onboarding in workspace A starts workspace B in the ready/initializing flow without
  repeating provider/theme setup.
- Restarting the process restores provider, selected/enabled models, and theme.
- Credential values do not appear in `.skail` files, logs, exceptions, reprs, screenshots, or test
  snapshots.
- If secure storage is unavailable, Skail gives one actionable message and requires an environment
  credential; it never falls back to plaintext storage.

**Verification:**

- `rtk pytest tests/unit/test_tui_onboarding.py tests/unit/test_cli_boot_split.py tests/security/test_resolved_credential_canaries.py -q`

**Dependencies:** Tasks 1-3

**Files likely touched:**

- `src/skail/config/onboarding.py`
- `src/skail/config/credentials.py`
- `src/skail/tui/app.py`
- `tests/unit/test_tui_onboarding.py`
- `tests/security/test_resolved_credential_canaries.py`

**Estimated scope:** Medium

### Task 5: Load global and workspace root AGENTS.md files

**Description:** Implement a bounded, redacted instruction loader for
`~/.skail/AGENTS.md` and `<workspace>/AGENTS.md`. Return immutable source-labelled components with
content hashes and explicit ignored/omitted reasons.

**Acceptance criteria:**

- Global-only, workspace-only, both-present, missing, oversized, unreadable, and untrusted cases
  are deterministic and tested.
- When both are active, global content precedes workspace content and both hashes are persisted in
  the context packet.
- Workspace instructions cannot widen tools, permissions, write scope, budget, or delegation depth.

**Verification:**

- `rtk pytest tests/unit/test_context_assembly.py tests/integration/test_extension_trust.py tests/security/test_extension_trust_and_secrets.py -q`

**Dependencies:** Tasks 0-1

**Files likely touched:**

- `src/skail/agents/instructions.py`
- `src/skail/agents/context.py`
- `tests/unit/test_context_assembly.py`
- `tests/integration/test_extension_trust.py`
- `tests/security/test_extension_trust_and_secrets.py`

**Estimated scope:** Medium

### Task 6: Inject the instruction stack into lead and child agents

**Description:** Add the loaded instructions to the actual system prompt and persisted context for
the lead and every subagent, while retaining task-local isolation and profile prompts.

**Acceptance criteria:**

- The first lead call receives both active root instruction files exactly once.
- Children receive the same applicable roots plus their profile/task instructions, not the lead's
  full transcript.
- Resume uses the pinned instruction revisions for an in-flight attempt; a later attempt may load a
  newer revision and records the change.

**Verification:**

- `rtk pytest tests/unit/test_context_assembly.py tests/unit/test_lead_decision_tool_exposure.py tests/integration/test_delegation_controls.py -q`

**Dependencies:** Task 5

**Files likely touched:**

- `src/skail/agents/lead.py`
- `src/skail/runtime/run_controller.py`
- `src/skail/tools/assembly.py`
- `tests/unit/test_lead_decision_tool_exposure.py`
- `tests/integration/test_delegation_controls.py`

**Estimated scope:** Medium

### Task 7: Guarantee a lead or an actionable no-lead result

**Description:** Add a single lead-resolution function used by TUI and headless startup. It chooses
the strongest enabled candidate satisfying the lead's hard requirements, with stable deterministic
ties. If none qualifies, persist and render a typed `lead_unavailable` failure rather than returning
an empty answer.

**Acceptance criteria:**

- The strongest lead-qualified enabled model is selected automatically when no explicit lead is
  pinned.
- A persisted explicit model that is inaccessible or below the lead floor is diagnosed before the
  first provider call.
- TUI transcript/status and headless stderr include the required capability, best available models,
  and how to enable/select a capable model.
- A queued prompt is retained and runs once after the model set becomes valid.

**Verification:**

- `rtk pytest tests/unit/test_cli_runtime_config.py tests/unit/test_tui_interactions.py tests/unit/test_selector.py tests/integration/test_assignment.py -q`

**Dependencies:** Task 0

**Files likely touched:**

- `src/skail/routing/selector.py`
- `src/skail/cli/main.py`
- `src/skail/runtime/run_controller.py`
- `tests/unit/test_cli_runtime_config.py`
- `tests/unit/test_tui_interactions.py`

**Estimated scope:** Medium

### Task 8: Make the model picker one continuous keyboard surface

**Description:** Keep the filter input focused while navigation, selection, and model enabling work
through non-printable chorded keys. Replace `VerticalScroll` with viewport-window rendering and
explicit hidden-result counts.

**Acceptance criteria:**

- Typing any printable character, including `a`, `j`, `k`, and spaces, edits the filter and never
  triggers a picker command.
- Up/Down, Enter, Ctrl+Space, Ctrl+Shift+A, and Escape work without moving focus from the input.
- Wide, narrow, and short terminal tests find no vertical/horizontal scrollbar or scroll thumb.
- The highlighted row remains visible as navigation crosses the rendered window; filtering to zero
  results gives a clear empty state.

**Verification:**

- `rtk pytest tests/unit/test_tui_overlays.py tests/unit/test_tui_interactions.py tests/integration/test_tui_boot_pilot.py -q`

**Dependencies:** Task 7

**Files likely touched:**

- `src/skail/tui/overlays/model_picker.py`
- `src/skail/tui/overlays/shell.py`
- `tests/unit/test_tui_overlays.py`
- `tests/unit/test_tui_interactions.py`
- `tests/integration/test_tui_boot_pilot.py`

**Estimated scope:** Medium

### Task 9: Represent measured tokens without inventing zero cost

**Description:** Update normalized usage so observed token counts can exist when provider-reported
cost is absent. Preserve whether cost was reported, token-derived, unknown, or conservative
attempt-estimated.

**Acceptance criteria:**

- Generic LangChain responses with usage metadata retain their input/output/cache token counts and
  do not claim a zero-dollar actual.
- A genuine provider-reported zero cost remains distinguishable from absent cost.
- Mixed authoritative and estimated response chunks aggregate without upgrading authority.

**Verification:**

- `rtk pytest tests/unit/test_model_usage_events.py tests/contract/test_llmgateway.py tests/integration/test_assignment.py -q`

**Dependencies:** Task 0

**Files likely touched:**

- `src/skail/domain/usage.py`
- `src/skail/providers/langchain.py`
- `src/skail/providers/openai_compatible.py`
- `tests/unit/test_model_usage_events.py`
- `tests/contract/test_llmgateway.py`

**Estimated scope:** Medium

### Task 10: Settle token-derived actuals from frozen assignment prices

**Description:** Freeze the selected model's trusted input/output/cache prices into assignment
evidence. At settlement, compute per-call estimated actual cost from observed tokens. Use the full
attempt reservation only for calls with no usable token measurement, and label that fallback.

**Acceptance criteria:**

- A regression shaped like the reported `hi` call settles near `$0.006` from its observed tokens,
  not the roughly `$0.30` reservation.
- Multi-call attempts sum token-derived call costs exactly once and release unused reservation.
- Stale/missing/untrusted prices yield unknown cost unless the provider reports authoritative cost.
- The footer, ledger, budget gate, session resume, and export agree on authoritative, token-derived,
  conservative-estimated, reserved, and unknown amounts.

**Verification:**

- `rtk pytest tests/unit/test_budget.py tests/unit/test_toolcall_missing_usage_repro.py tests/integration/test_assignment.py tests/integration/test_budget_concurrency.py tests/unit/test_tui_projection.py -q`

**Dependencies:** Task 9

**Files likely touched:**

- `src/skail/routing/assignment.py`
- `src/skail/routing/budget.py`
- `src/skail/tui/projection.py`
- `tests/integration/test_assignment.py`
- `tests/unit/test_tui_projection.py`

**Estimated scope:** Medium

### Task 11: Add the three mint/pistachio themes and persist commits

**Description:** Expand all three proposed directions into complete semantic token sets. Add them to
the theme picker and onboarding, separate live preview from commit, and persist only committed
selection in global onboarding/config state.

**Acceptance criteria:**

- Pistachio Night, Pistachio Paper, and Mint Porcelain expose all 36 tokens and pass token validity
  and contrast checks.
- Moving through the picker previews; Escape restores the prior committed theme; Enter persists the
  chosen theme across restart.
- Status, diff, approval, warning, and error colors remain distinguishable without relying only on
  hue.

**Verification:**

- `rtk pytest tests/unit/test_tui_theme.py tests/unit/test_tui_overlays.py tests/unit/test_tui_onboarding.py -q`

**Dependencies:** Task 4

**Files likely touched:**

- `src/skail/tui/theme.py`
- `src/skail/tui/overlays/theme_picker.py`
- `src/skail/tui/widgets/onboarding.py`
- `tests/unit/test_tui_theme.py`
- `tests/unit/test_tui_overlays.py`

**Estimated scope:** Medium

### Task 12: Capture and review three real TUI screenshots

**Description:** Parameterize the existing deterministic Textual screenshot harness and export one
wide PNG plus its SVG source for each new theme using identical populated content.

**Acceptance criteria:**

- The three images show the same transcript, agents, plan, route, and ledger state at 120x40.
- PNG production is required; converter absence fails the task instead of silently skipping it.
- Automated checks confirm the expected labels are present and no content is clipped.
- Outputs are written under `design/tui-themes/` and are ready to show directly to the user.

**Verification:**

- `python scripts/dev_tui_screenshot.py --themes pistachio-night pistachio-paper mint-porcelain`
- Visual inspection of all three PNGs at original resolution.

**Dependencies:** Task 11

**Files likely touched:**

- `scripts/dev_tui_screenshot.py`
- `tests/unit/test_tui_theme.py`
- `design/tui-themes/pistachio-night.png`
- `design/tui-themes/pistachio-paper.png`
- `design/tui-themes/mint-porcelain.png`

**Estimated scope:** Small

### Task 13: Add a secret-safe, spend-bounded live test runner

**Description:** Create an explicit live runner and provider-live suite. The runner reads only
allowlisted keys from the repository `.env`, injects them into the child test process, redacts all
diagnostics, isolates HOME/USERPROFILE and Skail state, and enforces the cumulative spend ceiling.

**Acceptance criteria:**

- `.env` is read only for `--run-provider-live`; routine pytest never reads it.
- No value or partial value from `.env` appears in stdout, stderr, junit, cache, snapshots, or git
  diff.
- The runner records model IDs, timestamps, token counts, cost authority, and pass/fail evidence,
  but no prompts containing secrets or unrestricted provider payloads.
- A missing credential, unsupported model, or exhausted spend cap skips/blocks explicitly rather
  than falling back to fake execution.

**Verification:**

- `rtk pytest tests/provider_live -m provider_live --run-provider-live -q`
- Secret-canary scan of captured output and generated evidence.

**Dependencies:** Tasks 1-12

**Files likely touched:**

- `tests/conftest.py`
- `tests/provider_live/test_llmgateway_live.py`
- `scripts/live_check.py`
- `tests/security/test_resolved_credential_canaries.py`

**Estimated scope:** Medium

### Task 14: Exercise the supported feature matrix live

**Description:** Run the smallest real-provider scenarios that validate provider-dependent
behavior, while using real-runtime offline/pilot tests for visual and deterministic-only features.
Every discovered defect receives a deterministic regression when feasible, then the focused live
case is rerun. Continue until the matrix is green or an external provider condition is explicitly
identified.

**Live scenarios:**

1. Authenticated catalog refresh, cache write, and restart from the global directory.
2. Automatic strongest-qualified lead selection and explicit no-capable-lead error.
3. A minimal direct `hi` response with token/cost reconciliation.
4. A bounded read-only tool task against a temporary workspace.
5. One forced delegated task and final synthesis, respecting the three-child/two-attempt limits.
6. Global plus workspace `AGENTS.md` canaries observed in the actual model context.
7. Session persistence/resume without duplicate provider calls or duplicate charges.
8. Manual model selection followed by one prompt, proving queued-prompt release and model stickiness.

**Non-provider scenarios in the same final matrix:**

- One-time onboarding across two temporary workspaces.
- No repository-local `.skail` after CLI, TUI, tool, resume, and failure flows.
- Model picker keyboard flow at wide/narrow/short terminal sizes with no scrollbar.
- All three theme screenshots and committed theme restart.
- Approval, question, budget block, provider error, cancellation, and JSONL terminal events.

**Acceptance criteria:**

- Every matrix row has a recorded command, outcome, and evidence class (live provider or
  deterministic real runtime).
- All provider calls stay below the approved cumulative cap and use the fewest calls needed.
- The final rerun has no unexplained failure, skip, empty response, duplicate charge, or leaked
  secret.

**Verification:**

- `python scripts/live_check.py --max-cost-usd 1.00`
- Focused regression suites for every issue found.

**Dependencies:** Task 13

**Files likely touched:**

- `tests/provider_live/test_llmgateway_live.py`
- `tests/e2e/test_cli_e2e.py`
- `tests/integration/test_tui_boot_pilot.py`
- `out/live-validation/` (generated, never committed)

**Estimated scope:** Medium

### Task 15: Run release gates and update operator documentation

**Description:** Reconcile CLI/help/config docs with the shipped global paths, onboarding,
instruction precedence, lead diagnostics, cost labels, theme names, and live-test command. Run the
complete repository verification sequence after the last live fix.

**Acceptance criteria:**

- Documentation and `--help` contain no repository-local runtime `.skail` guidance.
- Cost displays consistently distinguish reserved, authoritative, token-derived estimate,
  conservative estimate, and unknown.
- The repository root remains free of runtime `.skail`; `.env` and live evidence remain untracked.
- All focused, full offline, smoke, screenshot, and bounded live checks pass.

**Verification order:**

1. `python -m ruff check src tests scripts evals`
2. `python -m mypy src/skail`
3. `rtk pytest tests/unit tests/contract -m "not provider_live" -q`
4. `python scripts/smoke.py --fake-provider`
5. `rtk pytest -q`
6. `python scripts/dev_tui_screenshot.py --themes pistachio-night pistachio-paper mint-porcelain`
7. `python scripts/live_check.py --max-cost-usd 1.00`
8. `python scripts/package_check.py`
9. `python scripts/release_check.py`
10. `graphify update .`
11. `rtk git diff --check`

**Dependencies:** Tasks 0-14

**Files likely touched:**

- `README.md`
- `docs/skail/CLI.md`
- `docs/skail/FEATURES.md`
- `docs/skail/ARCHITECTURE.md`
- `tests/unit/test_documentation_contracts.py`

**Estimated scope:** Medium

## Checkpoints

### Checkpoint A: Contracts and global state (Tasks 0-4)

- A second workspace reuses onboarding and creates no local `.skail`.
- Every Skail-owned path resolves below the one global root.
- Legacy state migration is recoverable and non-destructive.
- Secret persistence uses only environment variables or the OS credential store.

### Checkpoint B: Instructions and lead reliability (Tasks 5-8)

- Global and trusted workspace instructions reach lead and children with pinned revisions.
- Every prompt either gets a lead response or an actionable typed failure.
- The picker supports uninterrupted type/navigate/select operation with no scrollbar.

### Checkpoint C: Accounting truth (Tasks 9-10)

- The short-call reproduction settles from measured tokens near the expected real cost.
- Reservations are released and never displayed as provider-authoritative spend.
- Resume/export/UI all agree on the same usage rows.

### Checkpoint D: Visual choice (Tasks 11-12)

- Three complete themes pass contrast and state-distinction checks.
- Three comparable PNG screenshots are available to the user.
- Theme preview/cancel/commit/restart behaves correctly.

### Checkpoint E: Product confidence (Tasks 13-15)

- Offline gates pass before the first paid call.
- The bounded live matrix passes after all discovered defects are fixed.
- No credentials, local runtime state, or live evidence enter the repository.

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Global workspace namespaces collide or drift | Wrong project receives approvals/artifacts | Reuse canonical workspace identity, persist its source, test moves and collisions |
| Moving state loses existing sessions or approvals | User-visible data loss | Import known legacy files non-destructively, verify counts/digests, never auto-delete legacy data |
| Persistent onboarding stores a secret in plaintext | Credential exposure | OS credential store only; environment override; redaction canaries; fail closed when unavailable |
| Workspace `AGENTS.md` weakens safety | Policy bypass | Treat instructions as prompt context only; code-owned gates remain authoritative; require trust |
| “Strongest model” bypasses lead requirements | Silent low-quality failure | Rank only after hard compatibility filtering; show actionable error when none qualifies |
| Token-derived price uses a changed catalog | Incorrect historical cost | Freeze trusted price evidence on the assignment before the call |
| Reservation fallback still appears as actual spend | Continued ledger distrust | Separate authority enum/display buckets and assert snapshot/event/export parity |
| Pastel colors reduce readability | Inaccessible TUI | Contrast tests, actual 120x40 screenshots, status glyphs/text in addition to color |
| Live tests spend unexpectedly | Cost surprise | Offline-first gate, minimal calls, cumulative `$1.00` default cap, fail closed |
| Provider instability causes endless fix loops | Unbounded work/spend | Retry only classified transient failures within the cap; report external blocker separately |

## Out of scope

- Inferring capability from model name, popularity, context length, or price.
- Selecting an underqualified lead to suppress an error.
- Deleting an existing repository-local `.skail` automatically.
- Persisting API keys in TOML, JSON, SQLite, logs, fixtures, or screenshots.
- Running every accessible provider model; the live matrix validates product features, not the
  provider's full model catalog.
- Treating screenshots or fake-provider tests as evidence of provider quality.
