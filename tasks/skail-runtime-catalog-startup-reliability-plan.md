# Skail Runtime Catalog and Startup Reliability Plan

## Objective

Make a normal authenticated `skail` launch reach a usable, truthful state on every start. Skail
must refresh the caller-accessible LLMGateway catalog at startup, persist model and pricing metadata
in a local JSON snapshot, fall back safely when refresh is transiently unavailable, and never turn
missing or untrusted evidence into a zero cost or an automatic-routing authorization.

The local file is a cache of the authenticated provider response, not a second hardcoded model or
pricing source. LLMGateway `GET /v1/models?exclude_deprecated=true` remains authoritative.

## Confirmed Diagnosis

The existing implementation already writes
`~/.skail/catalog/llmgateway.json`, but runtime bootstrap cannot use a normal discovered-only
catalog:

- The current local snapshot contains 127 entries. All 127 have prompt and completion prices.
- Every discovered entry is marked `trusted=false` and none has an evaluated `capability` vector.
  Consequently, `ModelCatalog.is_auto_eligible()` returns false for every model.
- `_build_runtime_models()` requires an automatically eligible model before it constructs the
  runtime when no explicit lead model is configured. This makes successful discovery end in a
  startup configuration error.
- The configured models (`deepseek-chat`, `claude-3-5-sonnet`, and `gemini-1.5-pro`) have no exact
  match in the authenticated catalog, so the configured-candidate filter also produces an empty
  set.
- The cache wrapper writes `retrieved_at` in local time without a timezone while entry timestamps
  are UTC. The loader ignores the wrapper timestamp and does not validate provider, endpoint, or
  snapshot completeness.

The focused catalog, bootstrap, and provider contract suite currently passes (43 tests), which
confirms that the real discovered-only startup path and its failure modes are not covered.

## Authority and Invariants

- Provider authority: authenticated LLMGateway `GET /v1/models?exclude_deprecated=true`.
- Cache location: `~/.skail/catalog/llmgateway.json`; no catalog data belongs in project `.skail/`.
- The cache contains no API keys, authorization headers, complete environment, or provider
  responses unrelated to model metadata.
- Provider prices remain `Decimal` in memory and JSON decimal strings on disk.
- Prompt, completion, and cache-read prices are normalized from per-token values to per-million
  fields exactly once.
- Authenticated model availability, context, modalities, transport capability flags, and pricing
  are trusted provider facts. They are not model-quality evidence.
- Automatic routing still requires separate, trusted, current capability evidence. A provider
  model name, price, context size, or `tools=true` flag never creates a quality score.
- A user-selected discovered model is manual routing. It remains executable for future assignments
  even when it lacks automatic-routing evidence.
- Active assignments are immutable. Catalog refresh and model selection affect future assignments
  only.
- Missing, malformed, negative, non-finite, or stale prices cannot authorize a hard-budget route.
- Missing provider-reported cost is unknown until computed from trusted token prices; it is never
  silently recorded as zero.

## Target Startup Flow

1. Resolve provider configuration and credential reference without exposing the credential.
2. Load and fully validate the last local snapshot for fast fallback and diagnostics.
3. Attempt one authenticated catalog refresh with a bounded discovery timeout.
4. On a valid response, parse all accessible models, atomically replace the cache, and construct
   every discovered model.
5. On timeout, connection failure, rate limit, or 5xx, use the validated cache and show a degraded
   warning with its age. On 401/403, malformed success data, or a successful empty access list, do
   not disguise the problem as a transient cache hit.
6. Resolve the default lead in this order: explicit CLI model, persisted `routing.lead_model`, one
   valid explicitly enabled model, otherwise `selection_required` in the TUI. Never choose an
   arbitrary paid model.
7. If selection is required, finish initialization, open the discovered-model picker, and preserve
   queued composer text. Headless mode exits promptly with a stable error and suggested model IDs.
8. Persist a selected default separately from the enabled candidate set. Use that explicit model as
   a manual pin for lead and child first attempts when no evaluated automatic candidates exist.
9. Publish refresh source, timestamp, age, model count, price coverage, and degraded/error state to
   `models list`, the picker, and startup diagnostics.

## Local Snapshot Contract

Introduce a typed versioned envelope rather than treating an arbitrary `entries` array as a usable
catalog:

```json
{
  "schema_version": 2,
  "provider": "llmgateway",
  "endpoint": "https://api.llmgateway.io/v1/models",
  "query": {"exclude_deprecated": true},
  "retrieved_at": "2026-09-20T23:41:23.705674Z",
  "entries": []
}
```

Each entry retains model ID, source, UTC `as_of`, endpoint provenance, normalized Decimal-string
prices, context/output limits, modalities, structured-output/tool/reasoning flags, stability, and
provider mappings needed for inspection. The cache does not add a quality capability vector.

Writes use a sibling temporary file, flush and close it, then use an atomic replace on Windows. A
failed write leaves the prior valid snapshot intact. A schema-v1 file is read through one explicit
migration path and rewritten as v2 only after successful validation.

## Implementation Tasks

### Task 1: Add failing black-box startup and cache tests

**Dependencies:** None

**Likely files:**

- `tests/unit/test_cli_runtime_config.py`
- `tests/unit/test_cli_boot_split.py`
- `tests/unit/test_tui_interactions.py`
- `tests/contract/test_llmgateway.py`

**Acceptance criteria:**

- A real Textual app with an authenticated discovered-only catalog reaches `ready` or
  `selection_required`; it does not remain `initializing` or enter a misleading no-pricing error.
- A queued composer prompt survives catalog refresh and model selection, then runs exactly once.
- Fresh success, transient refresh failure with cache, auth failure, malformed response, empty
  access list, stale cache, corrupt cache, and first launch with no cache are independently covered.
- Tests prove the on-disk JSON contains model IDs, Decimal-string prices, UTC timestamps, endpoint
  provenance, and no credential material.

**Verification:**

`rtk pytest tests/unit/test_cli_runtime_config.py tests/unit/test_cli_boot_split.py tests/unit/test_tui_interactions.py tests/contract/test_llmgateway.py -q`

### Task 2: Make the catalog snapshot typed, UTC, complete, and atomic

**Dependencies:** Task 1

**Likely files:**

- `src/skail/providers/catalog_sources.py`
- `src/skail/config/paths.py`
- `tests/unit/test_model_catalog.py`
- `tests/unit/test_cli_runtime_config.py`

**Acceptance criteria:**

- Schema v2 validates provider, endpoint, query, UTC retrieval timestamp, bounded entry count, and
  every entry before the snapshot becomes runtime evidence.
- A failed/interrupted write cannot truncate the last valid cache.
- Schema v1 migrates deterministically; unknown future schema versions fail closed with a clear
  diagnostic.
- No accessible entry is silently truncated. An explicit overflow error replaces the current
  sorted `[:5000]` data loss behavior.

**Verification:**

`rtk pytest tests/unit/test_model_catalog.py tests/unit/test_cli_runtime_config.py -q`

### Task 3: Correct LLMGateway discovery evidence and current response parsing

**Dependencies:** Task 2

**Likely files:**

- `src/skail/providers/llmgateway.py`
- `src/skail/providers/catalog.py`
- `tests/contract/test_llmgateway.py`
- `tests/unit/test_model_catalog.py`

**Acceptance criteria:**

- Authenticated availability and price fields are trusted provider evidence while quality
  capability remains absent/manual-only.
- Top-level prices and provider-mapping capability flags from the documented response are parsed
  without inventing support when fields are absent or conflicting.
- Per-token prompt, completion, and input-cache-read prices normalize exactly once to Decimal
  per-million values.
- Missing/malformed prices remain `None`; genuine provider price `0` remains distinguishable from
  missing.

**Verification:**

`rtk pytest tests/contract/test_llmgateway.py tests/unit/test_model_catalog.py -q`

### Task 4: Split refresh policy from runtime model construction

**Dependencies:** Tasks 2-3

**Likely files:**

- `src/skail/cli/main.py`
- `src/skail/providers/errors.py`
- `tests/unit/test_cli_runtime_config.py`
- `tests/unit/test_cli_boot_split.py`

**Acceptance criteria:**

- Every authenticated LLMGateway startup attempts a bounded refresh; the UI cannot wait through
  two 60-second discovery retries.
- Only retry-safe/transient failures may use cache fallback. Authentication and protocol failures
  retain their classified cause and actionable message.
- Successful discovery with no entries is not replaced by models the credential can no longer
  access.
- All valid discovered models are constructed independently of the configured enabled subset.
- DevPass follows its documented shared-endpoint discovery flow under its distinct provider
  identity, or is explicitly rejected with a tested unsupported-state message until that contract
  exists.

**Verification:**

`rtk pytest tests/unit/test_cli_runtime_config.py tests/unit/test_cli_boot_split.py tests/contract/test_llmgateway.py -q`

### Task 5: Make default selection explicit and persistent

**Dependencies:** Task 4

**Likely files:**

- `src/skail/config/persistence.py`
- `src/skail/cli/main.py`
- `src/skail/tui/app.py`
- `tests/unit/test_tui_interactions.py`
- `tests/unit/test_config.py`

**Acceptance criteria:**

- Stale configured model IDs are reported and ignored as unavailable; they cannot filter the
  discovered catalog to zero.
- A picker or `/model provider:model` selection persists `routing.lead_model` atomically and is
  restored at the next launch.
- Provider enabled models and the selected default are distinct configuration concepts.
- A selected manual-only model runs the next lead assignment and first child assignments without
  being mislabeled as automatically eligible.
- Config parse/write failure preserves the original config and is shown to the user instead of
  being swallowed.

**Verification:**

`rtk pytest tests/unit/test_config.py tests/unit/test_cli_runtime_config.py tests/unit/test_tui_interactions.py tests/integration/test_assignment.py -q`

### Task 6: Let initialization complete without weakening routing evidence

**Dependencies:** Task 5

**Likely files:**

- `src/skail/tui/app.py`
- `src/skail/tui/overlays/model_picker.py`
- `src/skail/runtime/run_controller.py`
- `tests/unit/test_cli_boot_split.py`
- `tests/unit/test_tui_interactions.py`

**Acceptance criteria:**

- No evaluated automatic candidate is a selection state, not a startup crash or endless loader.
- The composer, retry action, and model picker remain responsive; overlays restore composer focus.
- The picker differentiates accessible, enabled, selected, automatic-eligible, stale-price, and
  missing-price states. Checked rows do not claim automatic eligibility when the model is
  manual-only.
- Headless mode fails promptly and deterministically when an explicit model is required.
- Selecting a model never mutates an active assignment.

**Verification:**

`rtk pytest tests/unit/test_cli_boot_split.py tests/unit/test_tui_interactions.py tests/unit/test_tui_overlays.py -q`

### Task 7: Fix unpriced manual execution and missing-cost accounting

**Dependencies:** Tasks 3 and 6

**Likely files:**

- `src/skail/domain/usage.py`
- `src/skail/providers/openai_compatible.py`
- `src/skail/routing/assignment.py`
- `tests/contract/test_llmgateway.py`
- `tests/integration/test_assignment.py`

**Acceptance criteria:**

- A manually selected accessible model with unknown price can run only when no run/task hard
  budget requires a reservation; the route and ledger explicitly show unknown cost.
- Any hard budget rejects unknown, untrusted, malformed, or stale pricing before provider launch.
- When LLMGateway reports token counts but no cost, Skail computes estimated actual cost from the
  assignment's frozen trusted prices, or records unknown. It never writes estimated zero merely
  because the provider omitted `usage.cost`.
- A genuine zero-priced model remains representable and distinguishable from unknown.

**Verification:**

`rtk pytest tests/contract/test_llmgateway.py tests/unit/test_budget.py tests/unit/test_model_usage_events.py tests/integration/test_assignment.py -q`

### Task 8: Make catalog state inspectable and credential detection accurate

**Dependencies:** Tasks 4-7

**Likely files:**

- `src/skail/cli/commands.py`
- `src/skail/tui/onboarding.py`
- `src/skail/tui/app.py`
- `tests/unit/test_cli_commands.py`
- `tests/unit/test_tui_onboarding.py`

**Acceptance criteria:**

- `skail models list` reads the local snapshot and reports source, refresh time/age, model count,
  price coverage, selected model, and automatic/manual eligibility instead of listing only fake
  models.
- `skail models show provider:model` reports normalized prices and provenance without secrets.
- `auth check` either performs its documented reachability check or is renamed so its behavior is
  truthful.
- TUI credential detection honors configured `api_key_env` names and DevPass rather than only
  three hardcoded environment variable names.
- Startup and fallback warnings are redacted and visible in both TUI and headless output.

**Verification:**

`rtk pytest tests/unit/test_cli_commands.py tests/unit/test_tui_onboarding.py tests/unit/test_tui_interactions.py -q`

### Task 9: End-to-end reliability matrix and documentation

**Dependencies:** Tasks 1-8

**Likely files:**

- `docs/skail/FEATURES.md`
- `docs/skail/ARCHITECTURE.md`
- `docs/skail/CLI.md`
- `docs/decisions/0004-provider-compatibility-contract.md`
- `tests/e2e/test_cli_e2e.py`

**Acceptance criteria:**

- A fake authenticated provider proves first launch, restart with fresh refresh, transient offline
  restart, stale cache, corrupt cache, revoked credential, empty access list, explicit model,
  selection-required TUI, manual-only execution, and hard-budget rejection.
- Wide/narrow TUI checks cover loading, degraded cache, selection required, ready, and startup error.
- Documentation states the cache path/schema, refresh/fallback policy, model-selection order,
  pricing trust/freshness rules, and recovery commands.
- No test or fixture requires a real provider credential; provider-live verification remains
  explicit and opt-in.

**Verification:**

`rtk pytest tests/e2e/test_cli_e2e.py tests/unit/test_tui_atelier.py -q`

## Checkpoints

### Checkpoint A: Catalog integrity (Tasks 1-3)

- Discovery response and local JSON round-trip without precision loss.
- Cache writes are atomic and malformed snapshots fail closed.
- Provider facts are trusted independently from quality capability evidence.

### Checkpoint B: Startup usability (Tasks 4-6)

- Startup refresh is bounded and classified.
- A discovered-only catalog reaches a usable selection/ready state.
- A persisted explicit model survives restart and runs lead plus child work manually.

### Checkpoint C: Budget truth (Task 7)

- Unknown cost is never zero.
- Hard-budget routing requires current trusted prices.
- Unpriced manual execution is permitted only without a hard budget.

### Checkpoint D: Operator confidence (Tasks 8-9)

- CLI/TUI expose the same catalog state and remediation.
- Full offline suite and end-to-end startup matrix pass.

## Final Verification Order

1. `python -m ruff check src tests scripts evals`
2. `python -m mypy src/skail`
3. `rtk pytest tests/unit tests/contract -m "not provider_live" -q`
4. `python scripts/smoke.py --fake-provider`
5. `rtk pytest -q`
6. Optional, explicitly authorized: provider-live discovery and one minimal manual assignment.
7. `graphify update .`
8. `rtk git diff --check`

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Treating provider metadata as quality evidence | Unsafe automatic routing | Trust provider facts by field; require evaluated capability vector for auto |
| Refresh delays every launch | Apparent startup hang | Explicit short timeout, one retry policy, visible progress, validated cache fallback |
| Cache corruption during write | No models on next launch | Atomic replace and full-envelope validation |
| Revoked access hidden by cache | Calls inaccessible models | Never fallback on auth failure or successful empty access list |
| Arbitrary default incurs unexpected spend | User surprise | Require explicit persisted selection when no auto candidate exists |
| Old configured IDs filter all current models | Startup failure | Reconcile and warn; never use old IDs as the discovery allowlist |
| Missing usage cost undercounts spend | Budget breach | Compute from frozen trusted prices or record unknown; never synthesize zero |
| Broad exception handling hides regressions | False degraded mode | Classify provider failures and let programming/schema errors fail visibly |

## Out of Scope

- A checked-in standard LLMGateway model or pricing table.
- Inferring quality scores from model names, price, context length, or marketing metadata.
- Mutating active assignments after refresh or picker selection.
- Background catalog polling after startup; startup refresh plus explicit retry is sufficient here.
- Reading or copying credentials into the cache, logs, diagnostics, tests, or fixtures.

## Remaining Product Limitation

The authenticated models endpoint supplies access, price, context, modality, and transport-feature
evidence; it does not supply Skail's coding/reasoning/tool-reliability quality vector. Therefore this
plan can make every accessible model executable through explicit manual selection, but it cannot
truthfully make all discovered models eligible for `auto`, `economy`, or `quality` routing. Those
modes remain limited to models with separately maintained or evaluated capability evidence. Creating
that evidence requires an explicit evaluation/promotion task and cannot be replaced by model-name or
price heuristics without violating ADR 0004.
