# Runtime Catalog and Startup Reliability Todo

- [x] Task 1: Add failing discovered-only startup, refresh-failure, cache, and queued-prompt tests.
- [x] Task 2: Introduce the typed UTC schema-v2 cache envelope and atomic Windows-safe writes.
- [x] Task 3: Trust authenticated provider facts, parse current LLMGateway metadata, and preserve
      Decimal pricing without adding quality capability evidence.
- [x] Checkpoint A: Catalog integrity tests pass.
- [x] Task 4: Separate bounded refresh/fallback policy from runtime model construction and classify
      failures correctly.
- [x] Task 5: Reconcile stale configured IDs and persist explicit default selection separately from
      enabled candidates.
- [x] Task 6: Complete startup in ready/selection-required/degraded states and keep the TUI
      responsive.
- [x] Checkpoint B: A discovered-only catalog starts; a selected model survives restart and runs.
- [x] Task 7: Support unpriced manual routes only without hard budgets and remove missing-cost zero
      accounting.
- [x] Checkpoint C: Unknown/stale pricing cannot authorize hard-budget work.
- [x] Task 8: Expose real local catalog/refresh state through CLI and TUI; honor configured
      credential environment names.
- [x] Task 9: Run the complete offline startup matrix, visual states, docs, and repository checks.
- [x] Checkpoint D: Full verification passes and limitations are documented with evidence.
