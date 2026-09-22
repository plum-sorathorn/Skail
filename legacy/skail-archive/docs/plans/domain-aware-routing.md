# Domain-aware routing with OpenRouter benchmark snapshots

## Decision

Skail imports OpenRouter Models and Benchmarks data only through an explicit maintenance operation. The imported data is atomically stored at `~/.skail/run/benchmarks.json`, validated, and loaded at configuration/startup time. A routed request reads only the process-memory registry; it never calls OpenRouter or reads the snapshot file.

The registry keeps raw result records with their source, permanent model slug, API version, `meta.as_of`, citation, and raw values. It records model aliases separately from canonical slugs. Scores are normalized only within a source metric and snapshot cohort. Missing or stale coverage is `unknown`, never zero.

## Data contract

`sync_openrouter_snapshot(api_key, path)` retrieves `GET /api/v1/benchmarks` and `GET /api/v1/models` with the Bearer header, validates both responses, then replaces the snapshot with `os.replace`. A malformed response leaves the previous snapshot intact. The documented benchmark endpoint is limited to 30 requests/minute per key and 500/day per account, which is why sync is not part of request routing. [OpenRouter Benchmarks API](https://openrouter.ai/docs/api/api-reference/benchmarks/list-benchmarks)

The snapshot preserves these independent namespaces:

- `aa.coding`, `aa.intelligence`, `aa.agentic`
- `design_arena.{arena}.{category}.{elo|win_rate|rank}`
- `openrouter.{benchmark_type}.{accuracy|accuracy_stddev|total_tasks|avg_cost_per_task|last_run_timestamp}`
- Models metadata: canonical slug, aliases, context length, provider output maximum, supported parameters, modalities, and pricing.

The Models API can resolve aliases to a canonical model and exposes the model metadata needed for eligibility checks. [OpenRouter Models API](https://openrouter.ai/docs/guides/overview/models)

## Current selection policy

The selector uses benchmark policies only among configured, enabled, non-degraded candidates that already meet local capability, context, tool, structured-output, and modality requirements. Local health remains the source of truth for availability.

- Frontend planner: Design Arena builders/UI component first, then optional models/website, intelligence, and coding.
- Frontend implementer: coding, then agentic and code-category signals; UI Arena is only a tie-breaker.
- Backend, debugging, and refactoring: `general_software_engineering` (coding first, agentic second, intelligence third), with no invented specialized benchmark label.
- Research planner: intelligence with optional GPQA Diamond.
- Tool-agent/OMA: agentic with optional tau-bench and Design Arena agents evidence.
- Verifier: coding and intelligence; agentic only as supporting evidence.

If a requested profile lacks coverage, static capability routing remains authoritative and reports `benchmark_coverage_unavailable`. `/stats` reports whether the loaded snapshot is available/fresh, its age, version, and covered-model count. `SelectionInfo` and `RoutingDecision` carry profile, normalized score, coverage state, and snapshot age.

## Deliberately deferred

Multi-agent worktrees, task-plan persistence, patch merge arbitration, approvals, verifier workflow contracts, replay evaluation, and conditional price-override interpretation require their own bounded feature proposal. They are not introduced by benchmark ranking because they would alter the existing two-plane execution model rather than merely enrich local candidate selection.

## Operations

Call synchronization from an explicit CLI/scheduled maintenance command with `OPENROUTER_API_KEY`; do not schedule it from a route handler. On startup, an invalid or stale snapshot is ignored fail-soft and routing uses existing static selection. A valid stale snapshot stays visible in `/stats` but contributes no benchmark score.
