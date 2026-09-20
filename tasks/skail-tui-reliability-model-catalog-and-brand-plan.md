# Skail TUI Reliability, Model Catalog, and Brand Plan

Date: 2026-09-20

## Objective

Make the composer the stable interaction anchor, make every exposed slash command truthful and
functional, replace the hardcoded LLMGateway model preset with the caller's discoverable catalog and
exact provider pricing, repair the model picker, and finish the existing ATELIER visual direction.
The selected sail logo must appear in both the README and the main TUI masthead.

This is a new plan rather than an edit to `tasks/plan.md`, which the repository identifies as
historical.

## Evidence from the current implementation

- The focused TUI suite passes (`91 passed`), but the controller integration test invokes
  `on_prompt_composer_prompt_submitted()` directly. It does not prove that keyboard or button input
  reaches the controller.
- The mount-first shell leaves the composer interactive while `runtime_factory` is still building
  the controller. A submitted prompt is cleared and recorded, but no worker is started when
  `self.controller is None`.
- `COMMAND_REGISTRY` advertises 15 commands while the dispatcher has 19 command branches. `/agent`,
  `/tasks`, `/mode`, and `/steer` are dispatchable but absent from help and completion.
- App-level handling is incomplete: `/fork` only fabricates a receipt, targeted `/cancel` loses its
  target, `/steer` has no app action, and some commands report success without a corresponding
  state transition.
- The LLMGateway adapter implements `/models`, but runtime bootstrap never calls it. The picker adds
  five hardcoded gateway model names, while the public non-deprecated endpoint currently returns
  270 models.
- Selecting an arbitrary model only changes `TuiProjection`. `RunController` can execute only models
  registered in its model mapping, and its configured-candidate fast path ignores the requested
  future lead model.
- Picker rows use `[x]` in a markup-enabled `Static`; Rich consumes `[x]` as a markup tag, so the
  checked state disappears. Existing tests inspect the source string rather than rendered output.
- The checked-in `current-main.txt` still shows a boxed transcript and a large nested-border
  composer. Those conflict with ATELIER's editorial hierarchy, restrained rules, and compact
  composer band.

## External contract used for model discovery

Use LLMGateway's authenticated `GET /v1/models?exclude_deprecated=true` response as the session's
available-model source. Per the official API reference, an authenticated request returns only
models and provider mappings allowed by the caller's organization, IAM rules, and project access.
The same response carries prompt/completion pricing, context length, maximum output, supported
parameters, structured-output support, deprecation state, and provider mappings.

Sources:

- <https://docs.llmgateway.io/v1_models>
- <https://docs.llmgateway.io/developers>
- `docs/decisions/0004-provider-compatibility-contract.md`

Prices must remain `Decimal` values converted from per-token strings to per-million-token values.
No floating-point conversion or hand-maintained price table is permitted. Cache entries must retain
their retrieval timestamp and provenance; stale cached prices may be displayed as stale but may not
silently authorize a hard-budget route.

## Logo proposals

Each option has a full README/help lockup and a compact masthead form. Use plain monospace text and
stable-width glyphs; do not animate the mark.

### A. Close-hauled — recommended

```text
      /|
     / |
    /  |
   /___|
__/____|__
\________/
  S K A I L
```

Compact: `/| S K A I L`

This is the clearest ship-and-sail silhouette, works in monochrome, and remains recognizable when
reduced to one line.

### B. Pixel canvas

```text
      ■│
    ■■■│
  ■■■■■│
      ▪│
  ━━━━━━━
  S K A I L
```

Compact: `■│ S K A I L`

This preserves the existing pixel language while making the mast and hull more explicit. It is the
closest evolution of the current Windward mark.

### C. Twin sail — selected

```text
     /\|\
    /  | \
   /___|__\
  /____|___\
  \________/
   S K A I L
```

Compact: `/\| S K A I L`

This expresses lead/child collaboration through two sails, but it is busier at small sizes.

**Decision:** Use Twin sail for the README, help/onboarding, and the main TUI. The full lockup is
the authoritative large rendering; `/\| S K A I L` is the compact masthead form.

## Interaction decision

The planned interpretation of “single point of interaction” is:

- the composer retains focus on the main screen;
- main transcript and side panels are display-only and cannot receive mouse or keyboard focus;
- `Shift+Tab` cycles Agents → Plan → Route → Budget while focus stays in the composer;
- `/agents`, `/plan`, `/route`, and `/budget` remain valid because they are entered through the
  composer, the single interaction point;
- direct panel clicks and the current `Ctrl+A/B/P/R` panel bindings are removed;
- routing mode moves to `/mode`, because `Shift+Tab` is reassigned to panel navigation;
- modal workflows opened from the composer, such as `/model`, remain keyboard-operable and restore
  focus to the composer when they close.

This interpretation is approved for implementation: view slash commands may switch panels because
they are entered through the composer. `Shift+Tab` remains the only direct panel-navigation gesture.

## Implementation tasks

### Task 1: Add failing black-box characterizations

**Description:** Reproduce the reports through Textual's pilot using the real composer, runtime
initialization path, controller, and rendered picker. Establish a table-driven contract for every
exposed slash command before changing behavior.

**Acceptance criteria:**

- A prompt submitted during runtime initialization has a deterministic visible result and is not
  silently discarded.
- Enter and the Send button both drive a real `RunController` and produce the lead response.
- A rendered checked picker row visibly contains its check marker.
- Every command in the registry has an app-level test for its success, invalid-input, and
  unavailable-capability behavior.

**Verification:**

- `rtk pytest tests\unit\test_tui_interactions.py tests\integration\test_tui_commands.py -q`

**Dependencies:** None

**Files likely touched:**

- `tests/unit/test_tui_interactions.py`
- `tests/unit/test_tui_commands.py`
- `tests/integration/test_tui_commands.py`
- `tests/integration/test_tui_shell.py`

**Estimated scope:** Medium

### Task 2: Make composer submission lifecycle-safe

**Description:** Give submissions explicit `initializing`, `ready`, `running`, and `error` behavior.
Keep a pre-ready prompt visible and queued, execute it exactly once after controller attachment, and
restore the draft with an actionable message if initialization fails. Remove broad exception
swallowing from the submission path where it hides user-visible failures.

**Acceptance criteria:**

- Submitting before the controller is ready never clears and loses the instruction.
- Starting, queued, running, failed, and completed states are visible in the transcript/composer.
- A ready prompt executes once; rapid follow-ups preserve FIFO order.

**Verification:**

- `rtk pytest tests\unit\test_tui_composer.py tests\unit\test_tui_interactions.py tests\integration\test_tui_commands.py -q`

**Dependencies:** Task 1

**Files likely touched:**

- `src/skail/tui/app.py`
- `src/skail/tui/widgets/composer.py`
- `tests/unit/test_tui_interactions.py`
- `tests/integration/test_tui_commands.py`

**Estimated scope:** Medium

### Task 3: Make the slash-command registry authoritative

**Description:** Replace the registry/dispatcher split with one typed command specification that
owns name, aliases, arguments, help, completion, availability, and action dispatch. Retain the
required command contract from `docs/skail/SPEC.md` and the ATELIER overlay commands.

**Acceptance criteria:**

- Help, palette, argument validation, and dispatch enumerate the same commands.
- Unknown and malformed commands return visible errors without mutating state.
- Conditional commands such as `/steer` explain the unavailable capability instead of claiming
  success.
- No command emits a success receipt before its state change succeeds.

**Verification:**

- `rtk pytest tests\unit\test_tui_commands.py tests\unit\test_tui_composer.py -q`

**Dependencies:** Task 1

**Files likely touched:**

- `src/skail/tui/commands.py`
- `src/skail/tui/widgets/composer.py`
- `tests/unit/test_tui_commands.py`
- `tests/unit/test_tui_composer.py`

**Estimated scope:** Medium

### Task 4: Wire every command to a real application action

**Description:** Implement or correct the app boundary for view, mode, model, cancel, steer, resume,
compact, trust, config, missions, theme, and quit. Targeted cancellation must preserve its target.
`/config` must show effective values and provenance without secrets. `/trust` must reflect the
actual store. Because `/fork` is absent from the required command contract and has no durable
backend, remove it from the exposed registry/help/palette instead of retaining its fabricated
receipt. A real fork can return later under a separate persisted-session contract.

**Acceptance criteria:**

- The command matrix passes through composer submission, not direct dispatcher calls.
- Each successful command produces the expected state transition and a truthful receipt.
- Unsupported background operations are explicit and do not affect the foreground run.
- Session commands persist and can be reconstructed after reopening the journal.

**Verification:**

- `rtk pytest tests\unit\test_tui_commands.py tests\integration\test_tui_commands.py tests\integration\test_compaction.py -q`

**Dependencies:** Task 3

**Files likely touched:**

- `src/skail/tui/app.py`
- `src/skail/tui/commands.py`
- `tests/integration/test_tui_commands.py`

**Estimated scope:** Medium per command group; split session commands from run commands during
implementation.

### Task 5: Promote LLMGateway discovery to runtime bootstrap

**Description:** Fetch the authenticated, non-deprecated LLMGateway catalog during background
runtime initialization, normalize the current schema, merge it with maintained/evaluated/user
evidence, and keep a bounded local cache for offline fallback. Remove the five hardcoded gateway
models from the TUI.

**Acceptance criteria:**

- The available list matches the authenticated `/v1/models?exclude_deprecated=true` response.
- Exact prompt, completion, and cache-read prices are converted to per-million `Decimal` fields.
- Architecture modalities, tool support, structured output, reasoning, context, and output limits
  are normalized from documented fields.
- Malformed or missing price fields are marked unavailable, never coerced to zero.
- A discovery failure uses a timestamped cache or returns a visible provider error; it never falls
  back to invented “standard” models.

**Verification:**

- `rtk pytest tests\contract\test_llmgateway.py tests\unit\test_model_catalog.py tests\unit\test_cli_runtime_config.py -q`

**Dependencies:** None

**Files likely touched:**

- `src/skail/providers/llmgateway.py`
- `src/skail/providers/catalog_sources.py`
- `src/skail/cli/main.py`
- `tests/contract/test_llmgateway.py`
- `tests/fixtures/providers/llmgateway/models.json`

**Estimated scope:** Medium

### Task 6: Make every discovered model genuinely selectable

**Description:** Register constructible model clients for the discovered LLMGateway catalog and
make explicit future-model selection constrain the next lead assignment. Preserve assignment
immutability for active attempts and keep unqualified models manual-only until trusted capability
evidence exists.

**Acceptance criteria:**

- Choosing any accessible discovered model can execute the next prompt without restarting Skail.
- `/model <id>` rejects unknown or inaccessible IDs before changing projection state.
- The selected model constrains the next lead assignment even when bootstrap candidates are used.
- Existing active assignments retain their original provider/model.
- Automatic routing still requires the existing trusted capability and pricing gates.

**Verification:**

- `rtk pytest tests\unit\test_cli_runtime_config.py tests\integration\test_assignment.py tests\integration\test_tui_commands.py -q`

**Dependencies:** Task 5

**Files likely touched:**

- `src/skail/cli/main.py`
- `src/skail/runtime/run_controller.py`
- `src/skail/tui/app.py`
- `tests/unit/test_cli_runtime_config.py`
- `tests/integration/test_assignment.py`

**Estimated scope:** Medium

### Task 7: Rebuild `/model` for a full catalog

**Description:** Replace hundreds of mounted static rows with a searchable, scrollable keyboard
list. Show model ID, selected state, routing-enabled state, input/output price per million, context,
and material capability flags. Keep the current attempt immutable.

**Acceptance criteria:**

- The picker remains responsive with at least 300 entries.
- The check state renders literally and is covered by a rendered-widget assertion.
- Typing filters by model/provider; arrows move; Space toggles routing eligibility; Enter selects;
  Escape closes and restores composer focus.
- Current, enabled, manual-only, stale-price, deprecated, and unavailable states are distinct in
  both text and color.
- Persisted enabled IDs round-trip without provider-prefix corruption.

**Verification:**

- `rtk pytest tests\unit\test_tui_overlays.py tests\unit\test_tui_interactions.py tests\unit\test_tui_perf.py -q`

**Dependencies:** Tasks 5 and 6

**Files likely touched:**

- `src/skail/tui/overlays/model_picker.py`
- `src/skail/tui/app.py`
- `src/skail/config/persistence.py`
- `tests/unit/test_tui_overlays.py`
- `tests/unit/test_tui_interactions.py`

**Estimated scope:** Medium

### Task 8: Make the composer the main-screen focus owner

**Description:** Convert transcript and margin panels to passive views, remove direct panel focus and
click activation, and cycle panels with `Shift+Tab` while retaining composer focus. Remove
`Ctrl+A/B/P/R` and move routing mode control to `/mode`.

**Acceptance criteria:**

- Mouse clicks in transcript, tabs, and side panels do not move focus or change the active panel.
- `Shift+Tab` cycles all four panels in a stable order and leaves focus on `#composer-input`.
- View slash commands remain usable through the composer under the interaction decision above.
- Overlay dismissal and resize always restore composer focus.
- Approval and other required workflows remain keyboard-complete without requiring panel focus.

**Verification:**

- `rtk pytest tests\unit\test_tui_interactions.py tests\unit\test_tui_overlays.py tests\integration\test_tui_shell.py -q`

**Dependencies:** Tasks 2 through 4

**Files likely touched:**

- `src/skail/tui/app.py`
- `src/skail/tui/widgets/chat.py`
- `src/skail/tui/widgets/agents.py`
- `src/skail/tui/widgets/plan.py`
- `tests/unit/test_tui_interactions.py`

**Estimated scope:** Medium; split passive-widget changes from binding changes if more than five
files are required.

### Task 9: Apply the Twin sail identity

**Description:** Replace the current Windward constants with the Twin sail full and compact lockups.
Use the full mark in the README and help/onboarding, and the compact form in the always-visible main
masthead. Keep a one-color fallback.

**Acceptance criteria:**

- README and TUI derive from one authoritative text-grid definition or an exact synchronized copy.
- The compact logo remains visible at narrow widths without hiding model, budget, or run state.
- No ambiguous-width emoji, image dependency, or logo animation is introduced.

**Verification:**

- `rtk pytest tests\unit\test_tui_masthead.py tests\unit\test_tui_commands.py tests\unit\test_tui_onboarding.py -q`
- Manual README monospace rendering check.

**Dependencies:** None; Design C (Twin sail) was selected on 2026-09-20

**Files likely touched:**

- `src/skail/tui/logo.py`
- `src/skail/tui/app.py`
- `README.md`
- `tests/unit/test_tui_masthead.py`
- `tests/unit/test_tui_commands.py`

**Estimated scope:** Small

### Task 10: Finish the ATELIER visual pass

**Description:** Compare the running 120×40 and 88×30 TUI against
`design/tui-redesigns/redesign-1.html` and its ATELIER contract. Repair hierarchy and spacing after
behavior is stable: compact the composer, remove nested borders, align transcript columns, clarify
the active panel, tighten masthead/dateline typography, and keep status visible without visual
noise.

**Acceptance criteria:**

- The transcript reads as an editorial grid rather than a boxed card stack.
- The composer occupies only the required 3–8 rows and has one intentional band boundary.
- Wide and narrow layouts preserve model, mode, budget, run state, and active-agent count.
- Focus, error, approval, and selection remain legible without relying on color alone.
- Dark, light, reduced-motion, empty, loading, running, approval, error, and long-content states are
  reviewed in one bounded visual pass and confirmed once after fixes.

**Verification:**

- `rtk pytest tests\unit\test_tui_atelier.py tests\unit\test_tui_atelier_bands.py tests\unit\test_tui_theme.py tests\integration\test_tui_shell.py -q`
- Capture and compare wide, narrow, dark, light, and reduced-motion terminal artifacts.
- Run the Impeccable detector once over changed TUI targets after implementation.

**Dependencies:** Tasks 2, 7, 8, and 9

**Files likely touched:**

- `src/skail/tui/app.py`
- `src/skail/tui/widgets/composer.py`
- `src/skail/tui/widgets/chat.py`
- `src/skail/tui/theme.py` only if an existing token is insufficient
- `tests/unit/test_tui_atelier.py`

**Estimated scope:** Medium

### Task 11: Update contracts and run release-level verification

**Description:** Update the public TUI, command, model-discovery, pricing, and navigation contracts.
Record the selected logo and remove documentation for deleted bindings or fake model presets.

**Acceptance criteria:**

- Specs, feature contracts, README, help, and actual bindings agree.
- New provider assumptions have contract tests and ADR 0004 is amended if trust/provenance rules
  change.
- No secret, unrestricted provider response, or generated cache is committed.
- Graphify is updated after the final code change.

**Verification:**

1. `python -m ruff check src tests scripts evals`
2. `python -m mypy src\skail`
3. `rtk pytest tests\unit tests\contract -m "not provider_live" -q`
4. `python scripts\smoke.py --fake-provider`
5. `rtk pytest -q`
6. `graphify update .`
7. `rtk git diff --check`

**Dependencies:** Tasks 1 through 10

**Files likely touched:**

- `docs/skail/SPEC.md`
- `docs/skail/FEATURES.md`
- `docs/skail/TUI_REVAMP_DRAFT.md`
- `docs/decisions/0004-provider-compatibility-contract.md` if required
- `design/tui-redesigns/atelier/STATUS.md`

**Estimated scope:** Medium

## Checkpoints

### Checkpoint A — behavior foundation (Tasks 1–4)

- Composer-to-controller flow passes through real UI events.
- The registry and executable command set are identical.
- Every command has a truthful outcome and visible failure behavior.

### Checkpoint B — catalog and model selection (Tasks 5–7)

- Authenticated discovery drives the list.
- Provider prices are exact and provenance-bearing.
- Any accessible model can be selected and used on a future assignment.
- The 300-entry picker meets the responsiveness check.

### Checkpoint C — interaction and finish (Tasks 8–10)

- Composer owns main-screen focus.
- Panel clicking/focus is disabled and `Shift+Tab` navigation is complete.
- Chosen sail identity is visible in README and masthead.
- ATELIER wide/narrow visual comparisons pass.

### Checkpoint D — complete (Task 11)

- Full offline suite, lint, types, smoke, and graph update pass.
- Documentation and captured evidence describe the shipped behavior.

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Tenant-specific model catalogs vary | Tests accidentally assume the public 270-model set | Contract-test schema and filtering with fixtures; assert response-driven membership, not a fixed production count |
| Catalog prices change | Stale budget estimates | Refresh on provider bootstrap, preserve timestamps, label cache age, and disallow stale/unknown prices for hard-budget authorization |
| Hundreds of rows slow Textual | `/model` becomes unusable | Filter before mounting and use a virtualized/list widget; keep a 300-entry performance test |
| Explicit model selection bypasses routing gates | Wrong or unavailable assignment | Validate constructibility/access first; use manual assignment with recorded provenance; retain hard gates for automatic routing |
| Focus trapping breaks approvals or overlays | Required actions become inaccessible | Add black-box keyboard tests for every modal/interrupt state and restore composer focus only after dismissal |
| Silent `except Exception` blocks diagnosis | User sees another no-op | Replace broad swallowing on critical paths with scrubbed, visible error receipts and tested fallback behavior |
| `/fork` has no durable backend contract | False success or large scope growth | Remove it from help/palette in this change; implement it later only with a persisted-session contract |
| Visual polish regresses narrow mode | Lost status or clipped composer | Capture 120×40 and 88×30 in the same visual pass and enforce content-width assertions |

## Definition of done

- The chatbox never silently loses a prompt and a real provider/controller response is covered by a
  composer-level integration test.
- Every command shown in help and completion has a tested real action or an explicit capability
  error; no fabricated success remains.
- `/model` lists the complete authenticated LLMGateway catalog, renders checked state correctly,
  shows exact provider pricing, and can use the chosen model on the next assignment.
- Main-screen focus stays in the composer; panels are passive and cycle with `Shift+Tab`.
- The Twin sail identity appears consistently in README, help/onboarding, and the main TUI.
- The running TUI meets the ATELIER hierarchy and polish criteria in wide and narrow captures.
- Lint, strict typing, focused suites, smoke, full offline tests, and `graphify update .` pass.
