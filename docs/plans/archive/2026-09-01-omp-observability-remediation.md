# Implementation Plan: Repair OMP Integration and Make Observability Trustworthy

Status: Completed and archived during Skail specification work on 2026-09-02.

## Scope

Repair the defects exposed by the 2026-09-01 OMP session before expanding the dashboard. The fast router worked, but its telemetry was duplicated, its OMP plugin plane did not report activity, and a large refactor was classified as low-complexity chat. This plan does not add I/O, async work, or model calls to the routing hot path.

## Evidence and Root Causes

| Finding | Evidence | Root cause |
| --- | --- | --- |
| Work never began | Six malformed `todo` calls returned `Invalid todo arguments`; no write or test tool ran. | OMP's task-list tool received a string where its schema required an array. This is an OMP-agent/tool-contract failure, not router dispatch. |
| OMA did not run | The first route recorded `task_type=chat`, `complexity_score=1`, `confidence=0.85`; all routes were `fast_direct`. | The SLM overconfidently downgraded “Refactor … end-to-end” to chat. The deterministic baseline would classify it as `refactor`, complexity 7, but does not constrain contradictory SLM output. |
| Stream telemetry was doubled | 20 of 21 completed turns created paired `openai/qwen3.7-flash` and `qwen3.7-flash` rows with the same tokens and near-identical timestamps. | The LiteLLM recorder and both protocol endpoint handlers write the same streamed completion. They use different model aliases. |
| Dashboard session labels are inaccurate | `stats.jsonl` has no session ID; the TUI loads the latest global 50/100 rows while labelling totals “Session.” | The stats schema/aggregates lack session identity, windows, canonical model identity, cache accounting, and a persistent decision store. |
| OMP plugin telemetry was absent | Plugin and generated extension flags were true, but the ledger was not modified during the session and neither spool nor a usable RAG tool occurred. | The extension was not demonstrably activated, or its runtime event contract did not fire. Tests only assert generated TypeScript text. |
| Escalation could not affect routing | OMP sends its session ID to `/plugin/escalate`; provider config sets only static `x-agent-id`; the router falls back to a different `auto_<hash>` ID. | Plugin bias and routing selection address different session IDs. |

## Decisions

- One upstream completion produces one immutable usage event. The LiteLLM recorder is the only ordinary-completion writer; endpoint handlers translate responses only.
- Extend the append-only stats event with an event ID, canonical upstream model, pseudo-model, session ID, cache usage, latency, and selection explanation. Read legacy rows compatibly; never rewrite them.
- Keep plugin ledger writes off the routing hot path. Telemetry failure degrades to direct routing with bounded diagnostics.
- Do not lower Session Guard's threshold: the 77k-token session was under its configured 80%-of-128k ceiling. Repeated invalid tool calls, not a compaction bug, caused context growth.
- Keep the SLM non-authoritative. Strong deterministic evidence establishes a safe lower-bound classification; price caps and fail-soft selection behavior remain unchanged.

## Dependency Flow

```text
OMP request/session identity       OMP extension heartbeat + tool events
              |                                |
              v                                v
route_target -> selection -> LiteLLM recorder -> canonical stats journal
       |              |                              |
       |              +--> selection/bias evidence   v
       +--> OMA gate (eligible top-level work)   dashboard aggregates
```

## Tasks

### Task 1: Eliminate duplicate completion telemetry

**Description:** Write stream/non-stream protocol tests, choose one recording boundary, and normalize aliases before persistence.

**Acceptance criteria:**

- [ ] A streamed OMP/OpenAI completion produces exactly one event.
- [ ] Anthropic stream and non-stream requests each produce one event.
- [ ] Canonical upstream model and requested pseudo-model coexist without alias-derived duplicates.

**Verification:**

- [ ] `python -m pytest tests/test_server_and_apis.py tests/test_plugin_e2e.py -q`
- [ ] Fake-LiteLLM tests assert one persisted event per request.

**Dependencies:** None.

**Files likely touched:**

- `skail/stats.py`
- `skail/server/server_chat.py`
- `skail/server/server_messages.py`
- `tests/test_server_and_apis.py`

**Estimated scope:** M.

### Task 2: Add versioned, session-aware stats events and aggregates

**Description:** Persist session/request identity, cache usage, routing and selection facts, then aggregate all-time, selected-session, and 15m/1h/1d/7d/30d views, projections, model mix, and latency.

**Acceptance criteria:**

- [ ] Each new event has stable event ID, canonical model, pseudo-model, timestamp, and session ID or explicit `unknown`.
- [ ] Aggregates do not double-count and distinguish all-time, selected session, and windows.
- [ ] Bias/floor/OMA metrics appear only from actual event data, never invented defaults.

**Verification:**

- [ ] Unit tests cover legacy events, sessions, windows, projections, aliases, and cache fields.
- [ ] `python -m pytest tests/test_server_and_apis.py tests/test_tui_components.py -q`

**Dependencies:** Task 1.

**Files likely touched:**

- `skail/stats.py`
- `skail/server/server_router.py`
- `skail/server/server_meta.py`
- `tests/test_server_and_apis.py`
- `tests/test_tui_components.py`

**Estimated scope:** M.

### Checkpoint: Telemetry correctness

- [ ] One provider completion equals one stats event.
- [ ] A fresh-process read gives the same aggregate as a live-process read.
- [ ] Existing `/stats` fields remain available through the schema transition.

### Task 3: Verify and repair the running OMP extension lifecycle

**Description:** Add a bounded activation/heartbeat contract and a real OMP (or supported runtime-fixture) probe. Establish actual OMP extension event API names before changing generated TypeScript.

**Acceptance criteria:**

- [ ] Installation reports a diagnostic if the file exists but OMP did not load it.
- [ ] A loaded extension emits identifiable heartbeat/session and tool-result events.
- [ ] `skail_search` is verified in a running OMP session when RAG is enabled.
- [ ] Disabled plugins remain silent/no-op and never block OMP.

**Verification:**

- [ ] Add runtime contract coverage or a documented manual OMP smoke check beyond source-text assertions.
- [ ] `python -m pytest tests/test_agent_adapters.py tests/test_plugin_shims.py -q`

**Dependencies:** Task 2.

**Files likely touched:**

- `skail/harnesses/omp.py`
- `skail/server/plugin_routes.py`
- `skail/plugin/ledger.py`
- `tests/test_agent_adapters.py`
- `tests/test_plugin_shims.py`

**Estimated scope:** M.

### Task 4: Unify OMP and router session identity

**Description:** Make the ID supplied to OMP events, bias, stats, and routing identical. Prefer a supported dynamic request header; if OMP cannot set one, define and test a documented correlation mechanism rather than using unrelated IDs.

**Acceptance criteria:**

- [ ] Deterministic OMP tool-error escalation changes the next request's bias for that same session.
- [ ] Session dashboard totals contain only that session.
- [ ] Missing identity is marked `unknown` and remains fail-soft; it is not silently correlated to a different external session.

**Verification:**

- [ ] Extend `tests/test_plugin_e2e.py` with OMP-shaped events and request metadata.
- [ ] Prove three identical calls or two consecutive errors produce one bounded escalation for the correlated session.

**Dependencies:** Tasks 2–3.

**Files likely touched:**

- `skail/harnesses/omp.py`
- `skail/server/server_router.py`
- `skail/server/plugin_routes.py`
- `skail/plugin/bias.py`
- `tests/test_plugin_e2e.py`

**Estimated scope:** M.

### Checkpoint: OMP integration

- [ ] A real/contract OMP session shows extension activation, event delivery, and matching session identity at routing and escalation boundaries.
- [ ] Durable lifecycle events reach the ledger without I/O on the routing hot path.

### Task 5: Constrain classification with the deterministic baseline

**Description:** Retain the SLM as a signal, but reject or raise classifications that contradict strong explicit user intent. Add the reference “Refactor … end-to-end” prompt as a regression case.

**Acceptance criteria:**

- [ ] An explicit refactor cannot be downgraded to low-complexity chat solely by SLM output.
- [ ] Capability floors stay within price-cap and fail-soft constraints.
- [ ] Ordinary chat/recon prompts retain expected fast routing.

**Verification:**

- [ ] `python -m pytest tests/test_slm_planner.py tests/test_phase1a_router.py -q`
- [ ] An eligible reference request meets OMA's gate predicate when OMA is enabled.

**Dependencies:** None.

**Files likely touched:**

- `skail/routing/slm_planner.py`
- `skail/routing/dispatcher.py`
- `skail/server/server_router.py`
- `tests/test_slm_planner.py`
- `tests/test_oma_integration.py`

**Estimated scope:** M.

### Task 6: Make OMA gate/outcomes observable

**Description:** Record not-eligible, started, completed, and failed-soft outcomes plus re-entry protection. Do not make OMA authoritative.

**Acceptance criteria:**

- [ ] Dashboard/API distinguishes all four OMA outcomes using real evidence.
- [ ] Re-entrant `x-oma-sidecar`/depth traffic never starts another sidecar.
- [ ] No OMA result is fabricated when execution does not run.

**Verification:**

- [ ] `python -m pytest tests/test_oma_integration.py tests/test_plugin_runtime.py -q`
- [ ] `python scripts/end_to_end_smoke.py --plugin`

**Dependencies:** Tasks 2 and 5.

**Files likely touched:**

- `skail/server/server_router.py`
- `skail/plugin/runtime.py`
- `skail/stats.py`
- `tests/test_oma_integration.py`
- `tests/test_plugin_runtime.py`

**Estimated scope:** M.

### Task 7: Rebuild the dashboard on verified aggregates

**Description:** Replace global-last-N views with explicit all-time/current-session/window aggregates. Render actual model mix, decisions, savings, latency, projections, session status, floor/bias, and OMA facts; remove any visual implication unsupported by data.

**Acceptance criteria:**

- [ ] “Current session” is session-filtered rather than global last-N history.
- [ ] Refresh works live and all-time figures survive restart.
- [ ] Empty, disabled-plugin, unknown-cost, and unknown-session states are explicit rather than mocked.

**Verification:**

- [ ] TUI component tests render empty, legacy, and populated aggregate states.
- [ ] Manual smoke: create two sessions, restart server, and confirm all-time/current totals differ correctly.

**Dependencies:** Tasks 1, 2, and 6.

**Files likely touched:**

- `skail/tui/dashboard.py`
- `skail/tui/dashboard_widgets.py`
- `skail/tui/dashboard_screens.py`
- `skail/server/server_meta.py`
- `tests/test_tui_components.py`

**Estimated scope:** M.

## Final Checkpoint

- [ ] `python -m pytest`
- [ ] `python scripts/end_to_end_smoke.py`
- [ ] `python scripts/end_to_end_smoke.py --plugin`
- [ ] Manual OMP session proves single-write stats, extension heartbeat/event delivery, correlated escalation, and observable OMA eligibility.

## Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| OMP cannot set a dynamic request session header | Establish supported OMP metadata in Task 3 before selecting a correlation design; document an intentional no-correlation fallback if unavailable. |
| Removing endpoint recording loses protocol-specific usage | Cover both protocols and stream modes with fake LiteLLM responses before removing any writer. |
| Classification change over-escalates ordinary prompts | Apply a deterministic lower bound only to strong explicit verbs; retain caps and test chat/recon controls. |
| Extra telemetry slows routing | Use already-available metadata and off-path queued writes; run hot-path checks. |

## Non-Goals

- No slow-path planner, task graph, or LLM authority.
- No replan caused solely by long healthy tool loops.
- No retroactive rewrite of existing stats journal rows.
