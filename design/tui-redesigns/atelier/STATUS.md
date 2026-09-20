# ATELIER Implementation Status (P1–P8)

Branch: `skail-tui-rework` · Spec: `IMPLEMENTATION_PLAN.md` (same directory) · Recorded: 2026-09-19

| Phase | Scope | Commit(s) | Status |
|---|---|---|---|
| P1 | Theme token migration — "Ink & Bone" (dark) / "Newsprint" (light), zero hardcoded hex | `33f9166` | Done |
| P2 | Chrome & layout — masthead, dateline, 80/1/39 split, transcript header, AtelierFooter | `dce64fa`, `42d2063`, `d7c09ee`, `9c90680` | Done |
| P3 | Transcript — four-column grid, role-variant tints, collapse/fold glyph, streaming shimmer + new-events dock copy | `d4353ef`, `e49a1f8`, `5abd0f2` | Done |
| P4 | Margin — tab strip, agent ledger, budget LEDGER/panel, plan/route panels | `eaeb027` (tab strip, landed early), `6bed555`, `2bf42f0`, `e645749`, `7673c13`, `fc08ef8`, `e801415` | Done |
| P5 | Full-bleed approval band + composer band (only boxed element; no side borders) | `c762b3a`, `42e8538` | Done |
| P6 | Overlays — shared overlay shell + onboarding dress | `0dcc911` | Done |
| P7 | Narrow behavior — screen-level narrow/wide, margin → drawer, dateline wraps to two rows | `0c442e5`, `0fac935` | Done |
| P8 | Finalization — refreshed current-page captures, plan + this status record | `b29fe98`, (this commit) | Done |

## Final verification (2026-09-19)

| Check | Result |
|---|---|
| `python -m pytest tests/unit -q` | 621 passed, 2 skipped (exit 0) |
| `rtk pytest tests/contract -q` | 120 passed, 2 failed (install-env: smoke script / installed console script) |
| `rtk pytest tests/integration -q` | 218 passed, 4 failed (pre-existing), 1 skipped |
| `python -m ruff check src tests` | All checks passed |
| `python -m mypy src\skail` | Success: no issues found in 123 source files |
| `python scripts\smoke.py --fake-provider` | ok |

Pre-existing integration failures: `test_live_child_failure_monitor_escalates_repeated_tool_calls` (`test_headless_core.py`) and 3× `test_tui_shell.py` (`#composer-input` NoMatches). Not ATELIER regressions; tracked separately.

## Residual limitations

- **Active-tab letterspacing skipped** — the mock's tracked-letterspacing on the active margin tab is not replicated (only section-head letterspacing where permitted; README honest #3 / R1).
- **Integrations rail renders a name list, not workspace ids** — `WorkspaceIntegrationItem` surfaces names only; id-level fidelity deferred.
- **Role-floor 0.50 ambiguity** — the 0.50 role-floor semantics in the margin/role weighting remain documented-but-unresolved; implementation follows the existing projection behavior.
- **Narrow drawer is display-only** — the drawer shows the active panel and the Shift+Tab gesture;
  panel navigation remains composer-focused and does not depend on clicking the drawer.
- **D-12(2) flags residual** — r8 remediation cleared D-3/D-6/D-12(1) and hardened D-5; the D-12(2) flag decisions remain recorded as residual/accepted (`6c76dbc`).

## Accepted fidelity deltas (mock ↔ terminal)

Enumerated in `IMPLEMENTATION_PLAN.md` §9: 2px inset focus → 1-cell border (R2), kbd chips as `$surfaceRaised` fill without border/radius (R12), dateline/LEDGER meter rounding (R7), footer 8+`?` hint overflow (deliberate), 18-binding `?` overlay superset, 9 light-theme tokens sourced from the README table (R8), mock-only fields rendered only when the projection supplies them (R6), `Screen:focus-within` outline retained for a11y, narrow shows no panel content (design intent, R15).

## Reliability and catalog follow-up (2026-09-20)

The composer is now the main-screen interaction anchor. Passive transcript and side panels do not
take focus or respond to direct panel navigation; `Shift+Tab` cycles Agents, Plan, Route, and
Budget while restoring focus to the composer. View slash commands remain composer-driven, and the
removed Ctrl+A/B/P/R bindings are not part of the surface.

The model picker consumes the authenticated provider catalog, renders a bounded scroll window for
large catalogs, filters by provider/model, and preserves literal checked markers. The visual
confirmation covered 120×40 and 88×30 dark frames, light and reduced-motion variants, empty,
loading, error, approval, running/long-content, and a 300-model picker state.
