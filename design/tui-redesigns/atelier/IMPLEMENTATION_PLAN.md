# IMPLEMENTATION PLAN — ATELIER (redesign-1) → Skail Textual UI

- **Branch:** `skail-tui-rework` @ `27ace87` ("fix(cli): collect scoped unit tests and lazy-load the help path")
- **Design source of truth:** `design/tui-redesigns/redesign-1.html` (ATELIER — "Ink & Bone" dark / "Newsprint" light; wide 120×40 + narrow 88×30 + `?` overlay + token-state strip)
- **Contract source:** `design/tui-redesigns/README.md` (57-feature coverage table, honest-limitations list, widget mapping)
- **Current implementation:** `src/skail/tui/app.py`, `widgets/{chat,agents,composer,interrupts,plan,route,budget,onboarding}.py`, `overlays/{transcript,shortcuts,theme_picker,model_picker,missions}.py`, `theme.py`
- **Textual:** 1.0.0. TCSS lives **inline**: `app.CSS` (app.py:125-186) + per-widget `DEFAULT_CSS`. There are no `.tcss` files.
- **Baseline screenshots already exist:** `design/tui-redesigns/current/current-main.svg` (+`-narrow.svg`, `.txt`) captured by `scripts/dev_tui_screenshot.py` at HEAD.

> How to use: execute phases in order (§2). Each phase ends green (tests + lint + types + its verify command) and lands as its own Conventional-Commit so it is independently revertible. Line anchors are exact at `27ace87`; re-locate by the quoted symbol if the file has moved.

---

## 1. Goal, constraints, and the ATELIER→Textual mapping

### 1.1 Goal

Replicate ATELIER **exactly**: a printed-page editorial terminal — hairline rules, a 4-column timestamp-gutter transcript, *marginalia* instead of panels, exactly **one tinted element** (the full-bleed approval band) and exactly **one boxed element** (the composer band). Ships both palettes (dark "Ink & Bone" / light "Newsprint") from the existing 36-token `REQUIRED_TOKENS` set, keeps every one of the 57 inventoried features, and keeps the test contract.

**Non-goals:** no new runtime/projection semantics beyond the flagged additive data surprises in §6/§8; no ThemeTokens API change; no DataTable rewrite (that is redesign-3); touching `legacy/skail/` (forbidden by AGENTS.md).

**Hard constraints (from the task + repo rules):**
1. Test ids/classes survive: `#composer-input`, `#agent-rail`, `#tabs` + `tab-agents|tab-plan|tab-route|tab-budget`, `#chat-transcript`, `#plan-view`, `#route-view`, `#budget-view`, `#prompt-composer`, `#btn-approve`, `#btn-reject`, `#onboarding-key`; classes `role-*`, `collapsed`, `approved`/`rejected`, `*-header` (`.rail-header`, `.plan-header`, `.route-header`, `.budget-header`); `#transcript-new-events`; widget **class names** (`TranscriptItemWidget`, `ActivitySpinner`, `ChatTranscript`, `AgentRail`, `PromptComposer`, `InterruptWidget`, `PlanView`, `RouteView`, `BudgetView`, `OnboardingPanel`) are never renamed. `#status-strip` is *not* asserted — it becomes `#dateline`.
2. **Pure helper signatures never change.** All current pure functions (e.g. `role_edge_for_item`, `transcript_diff`, `spinner_frame`, `agent_row_text`, `render_budget_lines`, `render_route_lines`, `budget_token_for_ratio`, `reduced_motion_enabled`, `validate_theme`) keep name, args, and semantics. New behavior = **new** pure helpers alongside.
3. Source-inspection tests keep passing — several tests read the *source text* of modules (`test_chat_module_has_no_hardcoded_hex`, `test_chat_module_has_keyed_reconciliation`, `test_composer_module_conventions`, `test_agent_select_never_jumps_to_route`, `test_agent_rail_messages_do_not_switch_tabs`, `test_missions_confirm_required_source`, `test_ctrl_t_reconciled_missions_wins`). Before editing any inspected module, read the inspecting test (§2, Phase 0).
4. Rich-markup **color names keep working**: `SkailApp.get_css_variables` (app.py:340-356) dual-registers `--token` *and* bare `token` — this mechanism must not change; markup like `[budgetFill]`/`[on $surfaceRaised]` resolves at paint time, which is also what makes theme switching free.
5. All 36 token names are *already* exactly the design's 36 (`theme.py:22-59` = redesign-1's token set). **This is a value retune, not a token-schema migration** — the single biggest risk reduction in the whole plan.
6. Budget thresholds stay `BUDGET_WARNING_THRESHOLD = 0.75` / `BUDGET_CRITICAL_THRESHOLD = 0.90` (theme.py:62-63). Reduced motion stays `reduced_motion_enabled()` + the `.reduced-motion` screen class (app.py:173-175, 374-377). `alt+T` ships as `alt+t` (never `⌥T`) in TCSS/labels.
7. Preserve: direct launch, immutable per-attempt model assignment, ≤2 child attempts, ≤3 concurrent children, no shared-writer overlap — these are all projection/runtime invariants the UI never touches (route tab stays read-only, missions keeps confirm-before-cancel).

### 1.2 ATELIER region → Textual widget mapping (all 12 regions)

| # | ATELIER region (redesign-1.html) | Current Textual | Target | New/Existing | Ids / classes |
|---|---|---|---|---|---|
| 1 | Masthead: letterspaced `S K A I L` + version + `[ANTHROPIC]` chip + `FRI 18 SEP · 14:32:07` (L223) | `Header(show_clock=True)` (app.py:279) | `Static` `#masthead`, 1 row, rebuilt by 1 Hz timer; then a 1-row strong rule (`.rule-strong`, `border-bottom: double $borderStrong`) | **New** (Header subclass rejected: its Bar/icon/stepper internals fight a 1-row letterspaced wordmark; nothing asserts `Header` in `test_tui_shell.py` — grep-verify, §2 P0) | `#masthead`, `.rule-strong`, `.provider-chip` |
| 2 | Dateline: `MODEL auto · MODE quality · SPEND $x/$y ▓▓░░░░░░░░ 0.3% · AGENTS ●1 running · 2 queued` (L226) + hairline rule under | `Static #status-strip` (app.py:280, 758-759; rendered by `_render_status_strip` L659-676 with **named** Rich styles "bold yellow"…) | `Static` `#dateline` (rename), 1 row, `border-bottom: solid $border`, **token markup** (`[$token]…`) instead of named colors; right-aligned `AGENTS` cluster via ljust; narrow → 2 rows | **Existing, renamed + rewritten** (detail §4) | `#dateline` (replaces `#status-strip`) |
| 3 | Main split `80ch 1ch 39ch` with 1-col vertical hairline `.vr` (L125-126, 230-254) | `#main-container` Horizontal; `#chat-container` 60% + `border-right`; `#sidebar-container` 40% (app.py:135-147, 281-294) | `#chat-container{width:1fr; padding-right:2}` · new 1-col `#hairline{width:1; background:$border}` · `#sidebar-container{width:39; padding-left:2}`; interrupts reparented out (row 8); narrow hides `#hairline`+`#sidebar-container` (existing `.narrow` mechanism, app.py:324-337, extended) | **Edit + 1 new 1-cell widget** | `#main-container`, `#chat-container`, `#hairline` (new), `#sidebar-container` |
| 4 | Transcript column header `TRANSCROFT…` → `TRANSCRIPT` + right `run-1 · 41 events · pinned` + thin rule (L232-233) | — (absent) | 1-row `Static` `#transcript-header` inside `#chat-container`, above the scroll; letterspaced label (baked spaces) + faint right-hand stats; `border-bottom: solid $border 55%` | **New** | `#transcript-header` |
| 5 | Transcript entry grid `clock(9) │ fold(2) │ role(10) │ measure(flex)` (L104-122) + role variants (you/lead/tool/err/apr/rcp/sub/sub2) | `TranscriptItemWidget` (chat.py:149-265): single-`Text` `render()`, `border-left` per role, ▸/▾ inside the text, `.collapsed` = opacity 70% | Same widget, **composition change**: row = 4 fixed `Static` children (`.msg-clock` 9, `.msg-fold` 2, `.msg-role` 10, `.msg-measure` 1fr); role-cell colors + error/approval row tints move into TCSS `role-*` selectors; fold glyph = new pure `fold_glyph()` (+/−/└/blank); `role_edge_for_item` (chat.py:76-97) **unchanged**, its `│┃┊` edges simply stop being *rendered* | **Edit (same class)** | keeps `role-*`, `collapsed`, adds `.msg-*`, `.streaming`, `.shim-peak` |
| 6 | Streaming: shimmerBase→shimmerPeak two-colour toggle + `$accent` caret `▌`; reduced-motion → static `$textFaint` + accent caret (L249, 482, 490; README honest #1) | `update_body()` in-place content swap (chat.py:228-231); `ActivitySpinner` 5-cell ping-pong (chat.py:267-292) | `.streaming` class on the last updating row; **one** 500 ms interval on `ChatTranscript` toggles `.shim-peak`; TCSS: `.streaming .msg-measure{color:$shimmerBase}` / `.streaming.shim-peak .msg-measure{color:$shimmerPeak}` / `.reduced-motion .streaming .msg-measure{color:$textFaint}`; caret = trailing `▌` `$accent` in the measure. `ActivitySpinner` class + `spinner_frame()` untouched (contract) | **Edit** | `.streaming`, `.shim-peak`, `.msg-caret` |
| 7 | Scroll-pin dock: `──── ↓ 4 new events · End to re-pin ────` (L251, 81) | `#transcript-new-events` docked Static, bg `$surfaceRaised`, copy `↓ N new events  (End)` (chat.py:308-315, 381-394) | Same id; copy → `↓ {n} new events · End to re-pin` (narrow: `↓ {n} new · End`); TCSS: transparent bg, `$textFaint`, flanking `─` runs via markup | **Edit (copy + TCSS)** | `#transcript-new-events` |
| 8 | Margin: tab strip (letterspaced, active = text + 2px `$accent` underline, no box) (L136-138, 258) | `TabbedContent #tabs` + 4 `TabPane` ("Agents/Plan/Route/Budget", app.py:286-294) | Keep `TabbedContent` (ids `#tabs`, `tab-*` are contract). TCSS strips Tab/TabPane/ContentSwitcher chrome; active = `border-bottom: heavy $accent`; **active tab label baked-letterspaced** (`A G E N T S`) via a `TabsTabActivated` handler — only ever one active label is spaced, so the 37-char margin never overflows (README honest #3) | **Edit** | `#tabs`, `tab-*` (ids unchanged; labels → uppercase) |
| 9 | Agent ledger rows: `●  AGENT 1  RUNNING  $0.0142` + task line + slot-coloured progress; `✓/✕/⊘/∙` states; `⏎ detail · M mission control` hint (L260-276) | `AgentRail` (VerticalScroll) rows = single Static, pipe-format from `agent_row_text()` (agents.py:54-65, 162-182), `>` selected marker, "AGENT RAIL" header | Same widget. New row = 1 ledger line (glyph 2ch / name 9ch / status word / cost right) + task continuation line, selected row = `background: $selection` (replaces `>`); status glyph map extends to `● ∙ ✓ ✕ ⊘` (running/waiting/complete/failed/cancelled — feature 31); hint row added; `.rail-header` **kept** as the hairline section header `A G E N T S`; `agent_row_text()` and friends untouched (tested) | **Edit + new pure helpers** | `#agent-rail`, `.ledger-row`, `.selected`, `.rail-header` |
| 10 | LEDGER block pinned to margin foot: `── LEDGER ──` / `$0.0142 of $5.00  0.3%` / 23-cell `▓/░` meter / `warn ┊ 75%   critical ┊ 90%` (L279-284, 508) | — (budget lives only in `#budget-view` tab; `budget_meter()`/`budget_view_model()` in projection) | New `BudgetLedger(Static)` in widgets/budget.py, mounted after `#tabs` inside `#sidebar-container` (always visible, `height: auto`), fed from the same `projection.budget_item` in `update_views()`; meter = 23 cells, fill token = `budget_token_for_ratio()`; BUDGET tab keeps the full breakdown (feature 41) | **New widget + new pure helper** | `#budget-ledger`, `.ledger-hd` |
| 11 | PLAN / ROUTE / BUDGET mini-panels: hairline section heads (`REVISIONS`, `INTEGRATIONS`, `RECEIPTS`, `ELIGIBLE`, `EXCLUDED`, `ROLE FLOORS`, `ASSIGNMENT`, `BREAKDOWN`), left-barred proposed-plan prompt, `A/R/C` acts + dashed note input (L406-472) | `PlanView` / `RouteView` / `BudgetView` = VerticalScroll of Static lines; accent headers; `.plan-proposed` = round box (plan.py:79-83); integrations received but never rendered (plan.py:116-131) | Keep widgets + `update_*` signatures; restyle: headers → letterspaced + hairline (`*-header` kept), no round borders, receipt/exclusion/integration sections as hairline kv blocks, proposed = left-bar `$approval` + `$approvalSurface` + `Accept A / Reject R / Change C` + dashed `#plan-change-note` Input; budget tab = money line + 23-cell meter + legend + BREAKDOWN from existing `BudgetViewItem` fields (reserved/authoritative/estimated/unknown, plan-able today, widgets/budget.py:94-98) + `thresholds 0.75 / 0.90` from theme constants | **Edit (no signature changes)** | `#plan-view`, `#route-view`, `#budget-view`, `.plan-header`…, `#plan-change-note` (new) |
| 12 | Approval: **full-bleed band** below the split — 1-cell `$approval` left bar on `$approvalSurface`, dashed-underline answer `Input`, underlined acts + `A/R/E`, `esc keeps pending` top-right (L150-154, 289-299; README honest #5) | `InterruptWidget` round box, lives **inside** `#chat-container` (60%); composed of `#btn-approve/#btn-reject/#btn-instruct` + `#interrupt-input` + hint (interrupts.py:92-136, 202-223); `#interrupt-container` also hosts `OnboardingPanel` (app.py:546-555) | Move `yield Container(id="interrupt-container")` out of `#chat-container` to sit between `#main-container` and `#prompt-composer` (app.py:284 → 295.5); band styling on the widget: `background:$approvalSurface; border-left: heavy $approval;` (2px→1-cell, documented), `border: none` elsewhere; Input → dashed underline, transparent; Buttons → flat underlined words; `esc keeps pending` moves into the title row (right-aligned); A/R/E + Esc + approved/rejected/`collapsed`-class logic **byte-identical** | **Edit + 1-line compose relocation** | `#interrupt-container` (id kept; now top-level), all inner ids kept |
| 13 | Composer: the only boxed band — top/bottom `solid $borderStrong` rules, `$surface` bg; `QUEUED 2 · ^ take back · newest runs after this one` ($approval); `›` prompt gutter; 3→8-row TextArea; meta `44 chars · / commands · ? shortcuts` + `[MODE <mode>]` chip (`$modeQuality`-bordered) + `[SEND ⏎]` chip (`$accentSoft`) (L156-168, 302-306) | `PromptComposer` (composer.py:210-284): `#composer-outer > #composer-queue`, `#composer-card` (**round** border, `$surfaceRaised`), `#composer-input` (min3/max8 ✓), `#composer-palette` (round), `#composer-actions` = `#composer-status` + `#composer-mode` + `#composer-send` (Button "Send") | Keep every id; `#composer-card` loses the round box (band = `#prompt-composer` itself: `border-top/bottom: solid $borderStrong; background: $surface;` + `:focus-within` flips both rules to `$focusRing`, replacing the current `outline:`), `›` = new 2ch `.composer-prompt` Static ($accent) left of the TextArea, meta reordered to `N chars · / commands · ? shortcuts` + right MODE/SEND chips (MODE colored by `modeQuality/Economy/Manual`), SEND label → `SEND ⏎`, queue line copy extended + `$approval` tint, palette → flat (`border-top: solid $border`, no round). 3–8-row growth, history, take-back, stash, palette, `should_send_on_enter` **unchanged** | **Edit** | `#prompt-composer`, `#composer-queue`, `#composer-outer`, `#composer-card`, `#composer-input`, `#composer-palette`, `#composer-actions`, `#composer-status`, `#composer-mode`, `#composer-send`, `.composer-prompt` (new) |
| 14 | Footer: 8 bindings + `⋯` + `? all shortcuts` (L93, 310-311; README honest #7); narrow = 4 + `⋯` + `? all` | `Footer()` (app.py:296) | New `AtelierFooter(Horizontal)` in widgets/footer.py: `Static.kbd` (`border: none; background: $surfaceRaised;` — 1px border/radius impossible in TCSS, documented) + label pair per binding; renders the 8 (`^C quit · ^B budget · ^A agents · ^P plan · ^R route · ^T missions · ^O transcript · alt+T theme`) + `⋯` + `? all shortcuts`; derivation from `App.BINDINGS` (no duplication of keys), `Screen.narrow` swaps to the 4-key narrow set. All 12+ stay in the `?` overlay (feature 50) | **New widget** (replaces bare `Footer`; nothing in the tests asserts `Footer` — grep-verify §2 P0) | `#app-footer`, `.kbd`, `.foot-…` |
| 15 | Overlays: `?` shortcuts = `$surfaceInset`-backdrop page, `SHORTCUTS` + `esc closes` + strong rule + 36/1/36 two-column kbd/desc grid + closing focus-note; `^O ⌥T ⌥P ^T` = same shell (L365-400) | 5 plain `Screen`s composing bare `Static`s, **zero** TCSS (overlays/*.py); shortcuts = Input `#shortcuts-filter` + grouped lines; theme = rows; model = rows; missions = header+rows; transcript = `ChatTranscript#transcript-full` | Shared TCSS: `.ovl-head` (letterspaced title + right hint), `.ovl-rule-strong`, `.ovl-grid` (two `width:36` columns + 1-col `#hairline`), `.ovl-foot`; shortcuts gets the 2-col kbd/desc composition (all groups from `ACTION_REGISTRY` — a documented superset of the mock's 12+4 rows); `esc closes` hint on every head; Screen→ModalScreen deliberately **not** migrated (tests drive these screens via `_test_app` doubles; the `$surfaceInset 80%` backdrop reads as the dim, and `background: $surfaceInset 80%` needs no ModalScreen) | **Edit (markup + TCSS only)** | `#shortcuts-filter` kept; new `.ovl-*` |
| 16 | Narrow 88×30: hairline+margin hidden, clock gutter hidden (role 11ch), dateline 2 rows + `^A ^P ^R ^B` tab-drawer strip, approval/composer full-bleed, `Add instr.`, `QUALITY` chip, 4-key footer (L96-98, 317-361) | `.narrow`/`.wide` classes on `#main-container` via `_check_screen_width()` at width<100 (app.py:324-337) + 2 narrow rules | Same trigger; additionally set the class on the **Screen** so out-of-`#main-container` widgets (dateline, drawer, footer) can react; new rules: `.narrow #hairline{display:none}`, `.narrow .msg-clock{display:none}`, `.narrow .msg-role{width:11}`, `#margin-drawer` (1-row: active tab name + 4 kbd chips, `display:none` in wide — panels intentionally invisible in narrow, per the design frame; state keeps switching invisibly), dateline/masthead/footer/`#composer-mode`/approval-compact narrow variants | **Edit + 1 new 1-row widget** | `#margin-drawer` (new) |
| 17 | Theme: "Ink & Bone"/"Newsprint" 36-token retunes; alt+T live preview; reduced-motion row | `DARK_THEME`/`LIGHT_THEME` (theme.py:126-202), `apply_theme`/`preview_theme`/`restore_theme` (app.py:358-397), `ThemePickerOverlay` | Pure value swap in `theme.py` (§3) — schema, `validate_theme`, `get_css_variables` dual registration, `apply_theme` mechanics, theme-picker preview/commit/Esc-restore flow all untouched. Markup uses names ⇒ theme switch needs no re-render fixes; the only paint-time token resolutions outside markup are `AgentRail`'s inline `styles.border_left` and the slot-colored ledger glyphs → add a defensive `refresh()` of `#agent-rail`+`#budget-ledger` in `apply_theme` | **Value-only edit** | (none) |

### 1.3 Test contract inventory (what must keep passing, where)

| Area | Tests | Care points |
|---|---|---|
| Theme | `tests/unit/test_tui_theme.py` | **Pins all 36 dark hexes** (L36-65+) and presumably the light set — the value migration *rewrites those expectation dicts*; also `validate_theme`/`REQUIRED_TOKENS`/thresholds assertions |
| Chat | `tests/unit/test_tui_transcript.py` | `role_edge_for_item` labels/edges/tokens (`test_role_edges_per_spec`, `test_agent_edge_uses_slot_glyph`) — function untouched; `test_chat_module_has_no_hardcoded_hex` — chat.py must stay 100% `$token`; `test_chat_module_has_keyed_reconciliation` — keyed mount logic stays; diff/pin/preview/export tests — helpers untouched |
| Composer | `tests/unit/test_tui_composer.py` | All-pure today (constants, ghost ranks, FIFO, recall) + `test_composer_module_conventions` (source-inspection). Copy changes (`QUEUED…`, status line, `SEND ⏎`) touch no pinned constant — verify `COMPOSER_PLACEHOLDER` etc. stay |
| Approval | `tests/unit/test_tui_approval.py` | Pure key-map tests (`approval_keyboard_action`) — untouched |
| Panels/rail | `tests/unit/test_tui_overlays.py` L120-260, `tests/unit/test_tui_sidebar.py` | `test_agent_rows_from_children_view`/`test_agent_row_text_cost` (pipe format — keep fn), `test_agent_select_never_jumps_to_route`, `test_agent_rail_messages_do_not_switch_tabs`, `test_budget_meter_cells` (projection cell count — our 23-cell LEDGER is a **new** helper, does not touch it), `test_plan_*`, `test_route_*` — if any asserts panel *headers* ("AGENT RAIL"/"ROUTE DECISIONS"/"BUDGET & USAGE") those assertions are updated in P4 |
| Overlays | `tests/unit/test_tui_overlays.py` L272-500 | `test_shortcuts_groups_and_filter`, `test_theme_rows_and_esc_restore`, `test_model_picker_*`, `test_missions_confirm_required_source`, `test_footer_hints_mention_overlays` (reads `ACTION_REGISTRY`, not the `Footer` widget — safe), `test_transcript_overlay_*` |
| Integration | `tests/integration/test_tui_shell.py` | `test_tui_shell_mounts_and_renders` (queries `#route-view`), `test_tui_shell_responsive_narrow_fallback` (width<100 → sidebar hidden — our class extension preserves it), `test_tui_shell_keyboard_navigation_and_prompt_submit` + `…_plan_navigation_ctrl_p_and_slash` (`#tabs.active` switching — untouched), `test_tui_shell_route_shadow_labels` (**asserts the last mounted Static of `#route-view`** — if P4 appends sections after it, either insert before it or update the test), `test_tui_shell_early_events_before_mount`, `…_real_projection_updates`, `…_resume_snapshot`, `…_cancellation_preserves_state` |
| Boot/onboarding | `tests/integration/test_tui_boot_pilot.py`, `tests/unit/test_tui_onboarding.py` | `#interrupt-container` relocation + full-bleed onboarding: read both files in P0 and P5; `#onboarding-key` mechanics (widgets/onboarding.py:153-176, app.py:996-999) untouched |
| Perf/security/parity | `test_tui_perf.py`, `test_tui_security.py`, `test_tui_headless_parity.py`, `test_tui_projection.py` | Headless parity = projection-level (untouched); perf: keyed reconciliation stays O(diff); security: secret redaction paths untouched |

**New tests to add (each phase, collected in `tests/unit/test_tui_atelier.py` + phase-specific files):** `format_masthead` clock/letterspacing; `render_dateline`/`render_dateline_narrow` markup+tokens; `fold_glyph` map; `ledger_row` fields; `ledger_meter` 23-cell + threshold tokens at 0.74/0.75/0.89/0.90; `budget_ledger_lines`; narrow-class wiring (`_check_screen_width` sets `Screen.narrow`); `AtelierFooter` shows exactly 8+`⋯`+`?` (and 4 in narrow); approval band TCSS (widget classes after `approved`/`rejected`);composer band no-round + `:focus-within` border flip; overlay head/foot markup; shimmer class toggling + reduced-motion selector presence.

---

## 2. Phase ladder (order, gates, verification)

Dependency-ordered, fail-fast, each phase independently green and independently revertible. The first three phases correspond to the README's suggested 3-commit landing; we keep finer commits inside them.

| Phase | Scope | Depends on | Primary risk | Gate |
|---|---|---|---|---|
| **P0 — Baseline & contract freeze** | Read the 4 source-inspecting tests; regenerate/confirm baseline SVGs; record pass/fail of the affected suites; add `tests/unit/test_tui_atelier.py` skeleton with the new-helper tests (red) | — | stale assumptions | full targeted suite green before any edit |
| **P1 — Tokens (§3)** | 36+36 value retune in `theme.py` + `test_tui_theme.py` expectations; nothing else | P0 | pinned hexes | `rtk pytest tests\unit\test_tui_theme.py -q` + unit+integration suite; **visual**: everything still renders (colors only) |
| **P2 — Chrome & layout (§4)** | masthead + strong rule, `#status-strip`→`#dateline` (token markup), 80/1/39 + `#hairline`, `#transcript-header`, `AtelierFooter`, narrow/Screen-class wiring, TCSS background=$background | P1 | compose-tree/DOM shifts | integration shell+boot suites; SVG diff vs baseline |
| **P3 — Transcript (§5)** | 4-column row, role-* TCSS, fold glyph, collapse, shimmer/caret, new-events dock | P2 | row layout + source-inspection tests | transcript unit + `test_tui_shell_transcript_collapse_click` |
| **P4 — Margin (§6)** | tab strip, agent ledger, `BudgetLedger`, Plan/Route/Budget mini-panels (+ additive sections), header copy | P2 | last-Static/label assertions in tests | sidebar/overlay/panels suites |
| **P5 — Approval + composer (§7)** | interrupt relocation (full-bleed band), dashed input, flat acts, composer band + `›` gutter + MODE/SEND chips + palette/queue restyle | P2 (P3 for full-bleed width sanity) | relocation vs boot-pilot/onboarding tests | approval/composer + `test_tui_boot_pilot` + `test_tui_shell_early_events_before_mount` |
| **P6 — Overlays (§8.1-8.2)** | shared `.ovl-*` shell, `?` 2-col shortcuts, theme/model/missions/transcript dressing | P1 (needs tokens) | Markup-only risk, tests are doubles-driven | overlay unit suite |
| **P7 — Narrow (§8.3)** | drawer strip, clock-gutter hidden, role 11, dateline 2-row, compact approval/composer, narrow footer | P2-P5 | TCSS specificity | `test_tui_shell_responsive_narrow_fallback` + new narrow tests |
| **P8 — Polish & docs (§9.0)** | reduced-motion sweep, focus discipline, accent-usage audit, `--out` flag on screenshot script, docs/plan updates | all | — | acceptance checklist §9.2 + DoD §10 |

**Checkpoint after every phase:** `rtk pytest -q` (full offline suite) + `python -m ruff check src tests scripts` + `python -m mypy src\skail` + `graphify update .` (repo rule after code changes) + regenerate the phase's SVG evidence.

---

## 3. Theme token migration (Phase 1) — both palettes, value-only

### 3.1 Mechanics (what must not change)

- `REQUIRED_TOKENS` (theme.py:22-59) already equals the design's 36 names, 1:1. **No names added/removed/renamed.**
- `ThemeTokens` frozen dataclass (theme.py:73-112) — fields unchanged; only the two constructions change.
- `validate_theme` (theme.py:221-229) enforces `^#[0-9A-Fa-f]{6}$` + full coverage — every new value must be a 6-digit hex. Note: redesign-1.html declares `--diffAddedSurface:#18211400` (8-digit, L62) — **ship `#182114`** (the README palette table agrees).
- `get_css_variables` (app.py:340-356) dual-registers `--{name}` **and** bare `{name}` (camelCase, via `as_dict`) — unchanged; this is what keeps Rich/Textual markup names like `[approval]`, `[on $surfaceRaised]`, `[b]$accent` working and what makes theme switches resolve at paint time.
- `apply_theme` (app.py:358-384) — mechanics unchanged; **add one defensive line**: after the class/refresh block, `try: self.query_one("#agent-rail").refresh(); self.query_one("#budget-ledger").refresh() except: pass` — these are the only widgets resolving tokens outside markup (inline `styles.border_left` / `Text(style=slot_token)`, the existing `slot_style_inline` pattern).
- `BUDGET_WARNING_THRESHOLD = 0.75` / `BUDGET_CRITICAL_THRESHOLD = 0.90` (theme.py:62-63) — untouched; `budget_token_for_ratio` (theme.py:301-309) untouched.
- `reduced_motion_enabled` (theme.py:273-280) + `SKAIL_REDUCED_MOTION` — untouched; the shimmer honors it via the `.reduced-motion` TCSS selector (§5.4), no Python.

### 3.2 DARK — "Ink & Bone" (replaces `DARK_THEME`, theme.py:126-163)

| token | hex | | token | hex | | token | hex |
|---|---|---|---|---|---|---|---|
| background | `#14110E` | | budgetFill | `#C9A227` | | agentOne | `#7FB3D5` |
| surface | `#1B1714` | | budgetWarning | `#D98E4A` | | agentTwo | `#B39DDB` |
| surfaceRaised | `#221D19` | | budgetCritical | `#E0645A` | | agentThree | `#82C9A5` |
| surfaceInset | `#100D0A` | | budgetEmpty | `#2C2620` | | shimmerBase | `#6E6154` |
| border | `#322A24` | | diffAdded | `#8FBF7A` | | shimmerPeak | `#F6E7D0` |
| borderStrong | `#4F4238` | | diffAddedSurface | `#182114` | | focusRing | `#E8B978` |
| text | `#EDE4D6` | | diffRemoved | `#E0645A` | | selection | `#3A2F22` |
| textMuted | `#9A8C7B` | | diffRemovedSurface | `#2A1614` | | link | `#8FC7E8` |
| textFaint | `#6E6154` | | dimmed | `#6E6154` | | | |
| accent | `#D98E4A` | | error | `#E0645A` | | | |
| accentSoft | `#2E2318` | | errorSurface | `#2A1614` | | | |
| modeQuality | `#B39DDB` | | approval | `#D9A441` | | | |
| modeEconomy | `#82C9A5` | | approvalSurface | `#241E14` | | | |
| modeManual | `#D9A441` | | delegation | `#B39DDB` | | | |

Contrast: 12.6:1 for `#EDE4D6` on `#14110E` (README accessibility table). `AGENT_SLOT_TOKENS` (theme.py:66-70) unchanged — `agentOne/Two/Three` are deliberately close to the shipped values so per-slot identity stays stable.

### 3.3 LIGHT — "Newsprint" (replaces `LIGHT_THEME`, theme.py:165-202)

| token | hex | | token | hex | | token | hex |
|---|---|---|---|---|---|---|---|
| background | `#F4F0E7` | | budgetFill | `#8A6A0C` | | agentOne | `#2F6E92` |
| surface | `#FBF8F1` | | budgetWarning | `#9E5518` | | agentTwo | `#5E46A0` |
| surfaceRaised | `#EDE7DA` | | budgetCritical | `#AE3227` | | agentThree | `#2C7355` |
| surfaceInset | `#E7E0D2` | | budgetEmpty | `#DCD4C5` | | shimmerBase | `#A99C87` |
| border | `#D6CCBB` | | diffAdded | `#2C7355` | | shimmerPeak | `#241E17` |
| borderStrong | `#A99C87` | | diffAddedSurface | `#DDF3E6` | | focusRing | `#7A3F0E` |
| text | `#241E17` | | diffRemoved | `#AE3227` | | selection | `#E3D3BC` |
| textMuted | `#6E6154` | | diffRemovedSurface | `#F6E2DE` | | link | `#2F6E92` |
| textFaint | `#948878` | | dimmed | `#948878` | | | |
| accent | `#9E5518` | | error | `#AE3227` | | | |
| accentSoft | `#F0E0CB` | | errorSurface | `#F6E2DE` | | | |
| modeQuality | `#5E46A0` | | approval | `#8A6200` | | | |
| modeEconomy | `#2C7355` | | approvalSurface | `#FAEEC9` | | | |
| modeManual | `#8A6200` | | delegation | `#5E46A0` | | | |

⚠ **Source discrepancy, resolved here:** the HTML's light override block (redesign-1.html:76-83) *omits* `modeQuality/Economy/Manual`, `delegation`, `diffAdded(+Surface)`, `diffRemoved(+Surface)` — they would silently inherit the dark values in the mockup. The authoritative light values are the README palettes table (README L373-407) = the tables above (and the task spec agrees). Recorded in the risk register (§9.1, R8).

### 3.4 Edits + tests

1. `theme.py`: rewrite the 36 kwargs of `DARK_THEME` and `LIGHT_THEME` (L126-163, L165-202). No other theme.py line moves. `validate_theme` runs unchanged over the new values (all 6-digit, all 36 present ⇒ no `ValueError`).
2. `tests/unit/test_tui_theme.py`: replace the expected-hex maps (L36-65+; read the full file — the light expectations continue past the grep cutoff) with the tables above; keep/add a round-trip: `as_dict(DARK_THEME)`/`as_dict(LIGHT_THEME)` == expectation, `validate_theme` raises on a deliberately 8-digit value (`#18211400`) and on a missing token.
3. No widget edits in this phase — the codebase's rule "no raw hex outside theme.py" (theme.py:1-7) means the whole UI recolors for free.
4. New tests in `tests/unit/test_tui_atelier.py::TestTokens`: both themes validate; 36/36 names; markup names still resolvable through `SkailApp.get_css_variables` (assert `base["--approval"]` and `base["approval"]` both present and equal).

**Verify:** `rtk pytest tests\unit\test_tui_theme.py tests\unit\test_tui_atelier.py -q` → `rtk pytest tests\unit tests\integration -q` → screenshots (`current-main.svg` must differ only in colors) → `graphify update .` → commit `feat(tui): adopt ATELIER "Ink & Bone" / "Newsprint" token palettes`.

---

## 4. Phase 2 detail — Chrome & layout, incl. `#status-strip` → dateline

**Files:** `src/skail/tui/app.py` (compose L278-296; `CSS` L125-186; `_render_status_strip` L659-676; `update_views` L758-759; `_check_screen_width` L324-337; `BINDINGS` L188-201 untouched), new `src/skail/tui/widgets/footer.py`, new tests.

### 4.1 Compose-tree edits (app.py)

```
compose()  # app.py:278-296, becomes:
yield Static(id="masthead")                       # NEW — see 4.2
yield div-rule →1-row Static(classes="rule-strong")  # NEW: border-bottom: double $borderStrong
yield Static(id="dateline")                       # renamed from #status-strip (L280)
with Horizontal(id="main-container"):
    with Vertical(id="chat-container"):           # width 1fr, padding-right 2
        yield Static(id="transcript-header")      # NEW (P2 mounts it empty; P3 fills it)
        yield ChatTranscript(id="chat-transcript")            # (moved) was L283
    yield Static(id="hairline")                   # NEW 1-col, background $border
    with Vertical(id="sidebar-container"):        # width 39, padding-left 2
        (TabbedContent #tabs unchanged at L286-294; #budget-ledger appended here in P4)
yield Container(id="interrupt-container")         # RELOCATED out of #chat-container (was L284; see §7.1)
yield PromptComposer(id="prompt-composer")        # unchanged L295
yield AtelierFooter(id="app-footer")              # replaces Footer() L296
```
- Delete the now-unused `Footer`/`Header` imports (app.py:22) — orphaned by *this* change only. `COMPACT_MARK` import (L35) stays (still used by `TITLE` L123).
- `on_mount` (L298-322) gains: `self._last_run_id: str | None = None`, the 1 Hz masthead timer (`self.set_interval(1.0, self._tick_masthead)`), and the initial `_refresh_dateline()`. `apply_event` (L776-779) gains one line: `self._last_run_id = str(event.run_id)` — transcript-header stats (§4.3). No other behavioral change.

### 4.2 New pure helpers + masthead (app.py, module level)

```python
ATELIER_WORDMARK = "S K A I L"            # letterspacing baked (TCSS has none; README honest #3)
_KEBAB = str.maketrans({" ": "·"})        # not used for the wordmark; see below

def letterspaced(label: str) -> str:
    """Bake 1-space tracking into a short section/tab label: 'AGENTS' -> 'A G E N T S'."""
    return " ".join(label)

def format_masthead(now: datetime, version: str, provider: str = "", narrow: bool = False) -> str:
    """Masthead line. Wide: 'S K A I L  0.1.0  [ANTHROPIC]   FRI 18 SEP · 14:32:07'.
    Narrow drops the date part (88-col frame, redesign-1.html L322)."""
```
Rendering: one `Text`/markup Static — `[$text]S K A I L[/] [$textFaint]0.1.0[/]` + (if provider) `[on $surfaceRaised] [$text]ANTHROPIC[/] [/]` + right-hand clock via computed pad. Provider = `self.onboarding_state.provider.upper()` when truthy (chip hidden otherwise — the badge is *optional*, feature 3); 1 Hz `set_interval` updates `#masthead` only. Height 1, no border.

### 4.3 Dateline (replaces `_render_status_strip`, app.py:659-676 → new `_render_dateline(narrow: bool) -> str`)

Token-markup (the mandated Rich→token migration; markup, not `Text.append`, so names resolve at paint):

```python
def _render_dateline(self) -> str:
    f = self.projection.footer_data
    used = float(f.session_cost_usd); limit = f.budget_limit_usd
    ratio = (used / float(limit)) if limit else 0.0
    token = budget_token_for_ratio(ratio if limit else None)      # theme.py:301-309
    filled = max(1, round(ratio * 10)) if (limit and used > 0) else 0   # 10-cell dateline meter
    meter = f"[{token}]" + "▓" * filled + f"[/][budgetEmpty]" + "░" * (10 - filled) + "[/]"
    mode_tok = {"quality": "modeQuality", "economy": "modeEconomy",
                "manual": "modeManual"}.get(f.routing_mode, "text")
    spend = (f"SPEND [text]${used:.4f} / ${float(limit):.2f}[/] {meter} "
             f"[textFaint]{ratio * 100:.1f}%[/]") if limit else \
            (f"SPEND [text]${used:.4f}[/]")
    agents = (f"[$agentOne]●{f.active_agents_count}[/] [textFaint]running[/] "
              f"· [textMuted]{len(self.projection.queue)} queued[/]")
    if narrow:  # two rows, redesign-1.html L324-325
        return (f"[textFaint]MODEL[/] [text]{f.lead_model}[/] [textFaint]· [/]"
                f"[textFaint]MODE[/] [${mode_tok}]{f.routing_mode}[/]  …[dim]SPEND row 2[/]")
    return (f"[textFaint]MODEL[/] [text]{f.lead_model}[/]   [textFaint]·   MODE[/] "
            f"[${mode_tok}]{f.routing_mode}[/]   [textFaint]·   [/]{spend}"
            f"   ·   [textFaint]AGENTS[/]  {agents}")
```
(Space-pad the MODEL→AGENTS clusters to right-align the AGENTS group at 120 cols; use `Text`/`ljust` on the plain prefix if markup pad-math gets fiddly — the *design* right-aligns it, L226's `<span class="sp">`.) Keeping/renaming: the id becomes `#dateline`; `update_views()` L758-759 renames its `query_one("#status-strip", Static)` → `#dateline`; the onboarding/initializing/error state prefixes (L662-667) survive as a `$modeManual`-colored lead-in word. Called from `update_views()` **and** from `_check_screen_width()` (narrow flip).

Known rounding note (DoD): the mock paints `▓▓` at 0.3% — decorative; implementation uses `round(ratio*10)` with a 1-fill minimum when spend > 0.

### 4.4 TCSS (replaces/extends `app.CSS` L125-186; keep `Screen.theme-light`, `.reduced-motion *`, `Screen:focus-within`)

```css
Screen { background: $background; color: $text; }        /* was $surface; .theme-light rule likewise */
#masthead   { height: 1; padding: 0 1; }
.rule-strong{ height: 1; border-bottom: double $borderStrong; }
#dateline   { height: 1; padding: 0 1; border-bottom: solid $border; }
#dateline.narrow { height: 2; }
#chat-container { width: 1fr; padding-right: 2; }         /* was 60% + border-right */
#hairline   { width: 1; background: $border; }
#sidebar-container { width: 39; padding-left: 2; }        /* was 40% */
#transcript-header { height: 1; border-bottom: solid $border 55%; color: $textFaint; }
.narrow #hairline, .narrow #sidebar-container { display: none; }
.narrow #chat-container { width: 100%; padding-right: 0; }
.wide #sidebar-container { display: block; }
#interrupt-container { width: 100%; height: auto; }        /* unchanged; now top-level */
```
(`55%` = the mock's `color-mix` hairline, L91 — TCSS percentage-qualifier colors; if the installed Textual 1.0.0 rejects the qualifier, fall back to plain `$border` and note it.)

### 4.5 `AtelierFooter` (new `src/skail/tui/widgets/footer.py`)

- `Horizontal` subclass; compose = for each of the 8 derived bindings (`ctrl+c quit, ctrl+b budget, ctrl+a agents, ctrl+p plan, ctrl+r route, ctrl+t missions, ctrl+o transcript, alt+t theme` — filtered from `ACTION_REGISTRY`/`BINDINGS`, never hardcoded keys): `Static(" ^C ", classes="kbd")` + `Static("quit", classes="foot-label")`; then `Static("⋯", classes="foot-ellipsis")`, spacer, `Static(" ? ", classes="kbd") + Static("all shortcuts", classes="foot-label")`. Keys render **`alt+T`** (alt glyph `⌥` is macOS-flavored — README honest #6).
- TCSS: `.kbd { background: $surfaceRaised; color: $text; }` (no border/1px/radius — documented fidelity delta, same as the mock's own `.kbd` impossible-in-TCSS cousin); `.foot-… { color: $textFaint; }`; `#app-footer { height: 1; background: $background; }`; `Screen.narrow #app-footer` swaps to the 4-key set (`^C quit · ^T missions · ^O transcript · alt+P model` + `⋯` + `? all`, redesign-1.html L360).
- Rebuild, don't subclass: `Footer` renders all bindings contextually and cannot show 8+⋯+`?`; the 12+ bindings stay truthful in the `?` overlay (feature 50). Pre-read `test_footer_hints_mention_overlays` (test_tui_overlays.py:481) — it reads `ACTION_REGISTRY`, not the widget, but *verify*.

### 4.6 Narrow wiring (also §8.3)

`_check_screen_width()` (app.py:324-337) additionally: `self.screen.add_class("narrow"|"wide")` (Screen-level; the existing `#main-container`-level toggling **stays** so `test_tui_shell_responsive_narrow_fallback` and the legacy TCSS selectors keep their contract), then calls `self._refresh_dateline()` and `self._tick_masthead()`. `on_resize` (L324-325) unchanged.

### 4.7 Tests (P2)

Update: any integration test referencing `#status-strip` (grep: none in `test_tui_shell.py`; sweep `tests/` once in P0 — expected zero-to-few, the contract doesn't pin it); `test_tui_shell_mounts_and_renders` if it asserts a `Header`. Add (`tests/unit/test_tui_atelier.py::TestChrome`): `format_masthead` wide/narrow/provider-optional/day-`%a`-upper; `letterspaced("AGENTS") == "A G E N T S"`; `_render_dateline` contains `MODEL/MODE/SPEND/AGENTS`, uses only bare token names (no hex — mirrors `test_chat_module_has_no_hardcoded_hex`), meter token switches at 0.75/0.90; narrow = 2 lines; `AtelierFooter` = 8 kbd+label pairs + `⋯` + `?` (narrow = 4); `#hairline`/`#masthead`/`#dateline`/`#transcript-header`/`#app-footer` presence after mount.

**Verify:** `rtk pytest tests\integration\test_tui_shell.py tests\integration\test_tui_boot_pilot.py tests\unit\test_tui_atelier.py -q` → `python -m ruff check src tests` → `python -m mypy src\skail` → `python scripts\dev_tui_screenshot.py` → `graphify update .` → commit `feat(tui): atelier chrome — masthead, dateline, 80/1/39 split, hairline, atelier footer`.

---

## 5. Phase 3 detail — Transcript: the four-column grid, collapse, streaming

**Files:** `src/skail/tui/widgets/chat.py` (module L1-146, `TranscriptItemWidget` L149-265, `ActivitySpinner` L267-292, `ChatTranscript` L295-408), `src/skail/tui/app.py` (transcript-header feeding, §4.1), `tests/unit/test_tui_transcript.py`, `tests/unit/test_tui_atelier.py`. Data prerequisite: `TranscriptItem.timestamp` **already exists** (projection.py:37, `datetime`, defaults `now(UTC)`) — the clock column needs no projection change. Roles today: `lead, user, task, tool, error, approval, system` (+ `agent`/`receipt` handled by `role_edge_for_item`).

### 5.1 Row composition (rewrite `TranscriptItemWidget`, chat.py:149-265 — class name, messages, keybindings, `collapsed`/`role-*` mechanics kept)

```python
def compose(self):                       # replaces the single-Text render() (L233-249)
    yield Static(self._clock(),  classes="msg-clock")     # width 9,  $textFaint, %H:%M:%S
    yield Static(self._fold(),   classes="msg-fold")      # width 2,  centered, $borderStrong
    yield self._role_cell()                                # width 10, bold, letterspace-ish
    yield Vertical(classes="msg-measure-wrap")            # 1fr:
        #   .msg-measure  (Static)   # $text; wraps in-place → continuation lines inherit the
        #                             # measure offset for free (README signature move, L48-49)
        #   .msg-sub2      (Static)   # role=tool, content lines 2+: $textFaint, padding-left 3
        #   .msg-caret     (Static)   # "▌" only while .streaming, $accent
```
- `_clock()`: `f"{item.timestamp:%H:%M:%S}"`, empty for sub-rows (mock L239-244: sub rows have no clock); blank under `.narrow` (TCSS hides, §8.3).
- `_fold()` — **new pure helper** (testable, unit-tested):
```python
def fold_glyph(item: TranscriptItem, collapsed: bool) -> str:
    """ATELIER fold cell: '+/−' when collapsible, '└' for sub-rows (tool), '' otherwise."""
    if item.role == "tool": return "└"
    if not item.can_collapse: return ""
    return "+" if collapsed else "−"
```
- `_role_cell()`: label = `role_edge_for_item(item)[0]` (**unchanged helper** — its `│┃┊` edges/`▸▾` indicator stop being rendered, L237-241); label = `f"AGENT {slot} ●"`+slot token when running (existing `_slot_from_item`, L100-105, + `agent_slot_token`); for `role=agent` set the color via the existing inline pattern (`Text(label, style=slot_token)` — same mechanism `agents.py:172` proves works and `test_agent_rail_slot_style_uses_token` endorses); all other roles get their color from TCSS only (no Python).
- Tool rows: measure shows `item.content` line 1 (`$textMuted`); lines 2+ → `.msg-sub2` (`$textFaint`, 3ch indent) — exactly the mock's `sub`/`sub2` rows (L241-244).
- Interaction: `on_key` (L251-264) and `on_click` (L262-264) untouched; `update_body` (L228-231) now also refreshes the measure/`sub2` children (in-place, never remounts — the perf contract) and adds the `.streaming` convergence of §5.4.
- `role-*` classes: **unchanged** (constructor L202). `.collapsed` add/remove (L208-218) unchanged; `.collapsed` TCSS switches from `opacity: 70%` to `$textMuted` measure + `+` fold + (existing) first-line preview via `collapsed_preview` (L65-73, untouched, still feeds the measure).

### 5.2 Role-variant TCSS (replaces the `border-left`-based DEFAULT_CSS L154-194; zero hex, satisfies `test_chat_module_has_no_hardcoded_hex`)

```css
TranscriptItemWidget { width: 100%; height: auto; }                  /* no border-left, no padding 0 1 */
.msg-clock  { width: 9;  color: $textFaint; }
.msg-fold   { width: 2;  text-align: center; color: $borderStrong; }
.msg-role   { width: 10; color: $textMuted; text-style: bold; }
.msg-measure{ width: 1fr; color: $text; }
.role-user   .msg-role { color: $accent; }                            /* ochre #1: YOU */
.role-lead   .msg-role { color: $text; }
.role-task .role-system .msg-role { color: $textMuted; }
.role-tool   .msg-role { color: $agentOne; }  .role-tool .msg-measure { color: $textMuted; }
.role-agent  .msg-role { /* inline slot token; see 5.1 */ }
.role-receipt .msg-role { color: $diffAdded; } .role-receipt .msg-measure { color: $textMuted; }
.role-error  { background: $errorSurface; }  .role-error  .msg-role, .role-error  .msg-measure { color: $error; }
.role-approval{ background: $approvalSurface; } .role-approval .msg-role, .role-approval .msg-measure { color: $approval; }
TranscriptItemWidget:focus-within { border-left: heavy $focusRing; }  /* mock: 2px inset → 1 cell (README honest #2 analog) */
TranscriptItemWidget.collapsed .msg-measure, .collapsed .msg-sub2 { color: $textMuted; }
.msg-sub2 { color: $textFaint; padding-left: 3; }
```
(One selector per line in code — the layered `.a .b` chains above arerolled into separate rules; specificity warning: write `.role-error .msg-role` as a full descendant rule. Accent discipline audit: `$accent` appears only on YOU, composer prompt/SEND, active-tab underline, streaming caret, focus-ish accents — matches README L505-506.)

### 5.3 ChatTranscript (chat.py:295-408) — recon, pin, new-events dock

- Keyed reconciliation, `transcript_diff`, `should_stay_pinned`, `PIN_THRESHOLD_LINES`, End-to-re-pin `on_key` (L396-408): **all untouched** (tested + perf + source-inspection).
- `_show_new_events_hint` (L381-394): copy → `f"↓ {n} new events · End to re-pin"` with flanking `$border`-run markup (`"─" * 24` each side; narrow copy `↓ {n} new · End`); DEFAULT_CSS `#transcript-new-events`: `background: $background; color: $textFaint;` (was `$surfaceRaised`/`$accent`).
- Streaming (mock L249, 482, 490; README honest #1 — the gradient itself is unshippable, the *two-colour toggle* is the shipped effect):
  - `update_from_view_model` (L334-375): when the last `to_keep`/`to_add` item changed, add class `streaming` to that widget and remove it from the previously-streaming one.
  - One `self.set_interval(0.5, self._toggle_shim)` in `ChatTranscript.on_mount`: flips `shim-peak` on the current `.streaming` widget only when `not self.app.reduced_motion`.
  - TCSS: `.streaming .msg-measure { color: $shimmerBase; }` · `.streaming.shim-peak .msg-measure { color: $shimmerPeak; }` · `.reduced-motion .streaming .msg-measure { color: $textFaint; }` · `.msg-caret { color: $accent; }` (caret = static `$accent` block; under reduced-motion the *body* is the static part — exactly "static `$textFaint` + `$accent` caret", README accessibility row).
  - `ActivitySpinner` (L267-292) and `spinner_frame` (L136-146): **byte-identical** (contract; the `✻`-glyph SPINNER_GLYPH stays).

### 5.4 Transcript header + tests

`#transcript-header` (mounted in P2, fed here): `_refresh_transcript_header()` in `update_views()` → letterspaced `T R A N S C R I P T` + right-hand `f"{self._last_run_id or '—'} · {len(self.projection.transcript_items)} events · {'pinned' if self.query_one('#chat-transcript')._pinned else 'unpinned'}"` in `$textFaint` (mock L232; `_pinned` read additively — no semantics change).

Tests: extend `test_tui_transcript.py` (no existing assertions break — `role_edge_for_item` untouched): `fold_glyph` truth table (tool→`└`; collapsible+expanded→`−`; +collapsed→`+`; notice→``); measure/two-colour/reduced-motion class assertions; sub2 split for multi-line tool content; clock formatted from `timestamp`; narrow hides `.msg-clock` via TCSS (assert the *rule exists* in `TranscriptItemWidget.DEFAULT_CSS` — source-inspection-friendly). New integration: `test_tui_shell_transcript_collapse_click` (existing, L54) must still pass — collapse click + `ItemToggled` + `collapsed` class.

**Verify:** `rtk pytest tests\unit\test_tui_transcript.py tests\unit\test_tui_atelier.py tests\integration\test_tui_shell.py -q` → screenshots → `graphify update .` → commit `feat(tui): atelier transcript — 4-column entry grid, fold gutter, shimmer, pinned-dock`.

---

## 6. Phase 4 detail — Margin: tab strip, agent ledger, LEDGER, Plan/Route/Budget

**Files:** `widgets/agents.py`, `widgets/budget.py`, `widgets/plan.py`, `widgets/route.py`, `app.py` (compose: `#budget-ledger`; `update_views()` L688-769: one extra ledger feed), `tests/unit/test_tui_sidebar.py`, `tests/unit/test_tui_overlays.py` (L120-260 panel tests), `tests/integration/test_tui_panels.py`, `tests/integration/test_tui_shell.py::test_tui_shell_route_shadow_labels`.

### 6.1 Tab strip (app.py + `app.CSS`; ids untouchable)

```css
#tabs { height: 1fr; }                       /* stays (L148-154); #tabs ContentSwitcher/TabPane height 1fr stays */
#tabs Tabs { border: none; background: $background; }
#tabs TabsTab { border: none; background: $background; color: $textFaint; padding: 0 1; }
#tabs TabsTab.-active { color: $text; border-bottom: heavy $accent; text-style: bold; }
#tabs TabPane, #tabs ContentSwitcher { background: $background; border: none; padding: 0; }
```
- Pane titles → uppercase `AGENTS/PLAN/ROUTE/BUDGET` (app.py:287-293); **the active tab's label gets baked letterspacing** (`letterspaced("AGENTS")` → `A G E N T S`) exactly as the mock's tab row (L65, 258) — only one label is ever spaced, so 37 cols never overflow (README honest #3). Implement via a small `on_tabs_tab_activated`-style handler on the app: reset all four labels, space the active one. `#tabs`/`tab-*` ids untouched; **verify**: integration tests switch tabs by id (L97-134) and `dispatch_slash_command` maps `/plan`→`tab-plan` (app.py:901-905) — label-only change, but grep tests for the literal labels `"Agents"` first.
- Verify note: `-active` / `#tabs-underline` selector names are Textual-version-sensitive; wrong selector = silent no-op caught by the SVG, so this is a *runtime-verify* item (§9.1, R3).

### 6.2 Agent ledger (`widgets/agents.py`; keep every pure helper + `#agent-rail` + messages + "never switches tabs" behaviour)

- Keep: `ALLOWED_STATUSES`, `agent_glyph`, `agent_label`, `normalize_status`, `agent_row_text`, `render_agent_rows`, `slot_style_inline`, `AgentRail.{AgentSelected,AgentDetailRequested,MissionControlRequested}`, `select_child/open_detail/open_missions/on_key/on_click` (L22-77, 102-199, 220-223) — the source-inspection tests (`test_agent_select_never_jumps_to_route`, `test_agent_rail_messages_do_not_switch_tabs`) and pipe-format tests depend on them.
- **New pure helpers** (the ledger): `status_glyph(status) -> str` (`● ∙ ✓ ✕ ⊘` for running/waiting/complete/failed/cancelled — feature 31's glyph+word pairing, accessibility: never colour-only) and `ledger_row(child) -> tuple[str, str, str, str]` (glyph, `AGENT n`, status word, `$0.0000` 4dp — mock L261). `_mount_child_rows` (L162-182) switches to compose one `Static` per ledger line (markup: `[$slotToken]●[/]  [$text]AGENT 1[/]  [$textFaint]RUNNING[/]  [textMuted]$0.0142[/]`) + a task continuation line (`$textMuted`, 3ch indent — the `.tk` row) +, **when the projection carries it**, the progress line `[$slotToken]▓×k[/][budgetEmpty]░×(10-k)[/] 8/12 steps · 2 children` (mock L263).
- Selected row: `background: $selection` via a `selected` class keyed off `focused_task_id` (replaces the `>` glyph, L169-171 — mock ledger has no `>`; the token-states strip pins *selection bg* as the focus affordance, L487). Focused/`$selection` = the rail's focus ring.
- `.rail-header` (L92-96) stays but becomes the hairline section head: `Static(letterspaced("AGENTS"), classes="rail-header")` + `border-bottom: solid $border` — this preserves the required `*-header` class *and* reads as the mock's `.led .hd`.
- New hint row after the ledger (mock L276): `Static("[$text]⏎[/] detail · [on $surfaceRaised] M [/] mission control", classes="ledger-hint")` — see `test_agent_rows_from_children_view`/`test_agent_row_text_cost` before/while editing; update those assertions if they pin row-1 = "AGENT RAIL" (flagged in §1.3).
- Pre-read: `tests/unit/test_tui_overlays.py` L120-170 (rail/rows/marker assertions).

### 6.3 LEDGER block (`widgets/budget.py`) — the always-on budget (README L50-53, 507-508)

- New `BudgetLedger(Static)` (new class, new id `#budget-ledger`): `height: auto`; compose = 3 markup lines:
  1. `[$textFaint]LEDGER[/] ` + `─`-run (hairline, the `.led .hd`),
  2. `[textMuted]${used:.4f} of ${limit:.2f}[/]` + right-padded `[$text]{pct:.1f}%[/]` + `▲` when `ratio ≥ 0.75` (`▲▲` when `≥ 0.90`) — the mock's token-state markers (L479-480, coverage #42/#43),
  3. meter: 23 cells — `[$fill]▓×k[/][budgetEmpty]░×(23−k)[/]` with `k = round(ratio*23)`, fill token = `budget_token_for_ratio(ratio)`; then legend `[textFaint]warn ┊ 75%   critical ┊ 90%[/]` (L283).
- **New pure helpers** (old ones untouched): `ledger_meter(ratio: float | None, cells: int = 23) -> str` and `ledger_lines(used, limit) -> list[str]`. Constant `BUDGET_LEDGER_CELLS = 23`. (`projection.budget_meter`/`budget_view_model` and `render_budget_lines` keep their signatures + tests — `test_budget_meter_cells` is about *projection* cells.)
- Mount: `app.py` compose → after `TabbedContent` inside `#sidebar-container`: `yield BudgetLedger(id="budget-ledger")`. Feed: in `update_views()` next to the `#budget-view` update (L725-726): `self.query_one("#budget-ledger", BudgetLedger).update_ledger(self.projection.budget_item)` (same additive pattern as the interrupt container). Hidden entirely under `.narrow` (TCSS `display: none` — margin collapses, feature 51).
- BUDGET tab (`BudgetView.update_budget` L78-125) redesign to the mock's breakdown (L459-470): money+pct row, 23-cell meter + legend (reuse `ledger_lines`), then `── BREAKDOWN ──` kv rows from fields that *already exist*: `reserved_usd`, `committed = authoritative+estimated`, `unknown_cost_usd`, `per_agent_costs`, plus `Remaining:`; final `[textFalt]⌘… thresholds {BUDGET_WARNING_THRESHOLD} / {BUDGET_CRITICAL_THRESHOLD}[/]` line (theme constants, L470). Rows the projection can't derive today (`burn`, `headroom`) are **omitted, not invented** — flagged in §9.1 (R6) with the additive-ChildView/`BudgetViewItem` note.

### 6.4 PLAN / ROUTE mini-panels (widgets/plan.py, widgets/route.py — signatures unchanged)

- PLAN (`_refresh` L133-164): header → `.plan-header` = hairline + letterspaced `P L A N` + state word; body rows: glyph `✓ ▌ ⊘` (plan.py:13-15 — note design's current-row glyph is `▌` where the code has `●` — switch `GLYPH_CURRENT` to `"\u258c"`; `plan_row_kind`/`plan_glyph`/`plan_header`/`plan_progress`/`render_plan_rows` signatures preserved, only the glyph constant + row markup change, so `test_plan_header_and_glyphs`/`test_plan_progress_counts_done` are updated *values-wise*), objective + faint agent tag. New hairline sections fed from **already-passed** `update_plan` inputs (app.py:709-717): `── REVISIONS ──` (`r{revision}` + state; history lines only if receipts carry `r\d → r\d` shapes — else just the current revision, documented), `── INTEGRATIONS ──` (`" · ".join(integrations)` — currently received, never rendered: closes that gap, feature 36), `── RECEIPTS ──` (each receipt, 2-line: text + faint indented continuation, mock L420-422).
- Proposed prompt (L141-148): `.plan-proposed` → `background: $approvalSurface; border: none; border-left: heavy $approval;` + acts row `Accept A · Reject R · Change C` (underlined words style, §7.2) + **new** `Input(id="plan-change-note", placeholder="optional change note…")` (dashed-underline, §7.2 TCSS); `PlanChangesRequested` gains `note: str = ""` (additive, default-`""` — call sites at app.py:1089-1094 unaffected; note is surfaced in the transcript event copy). A/R/E/Enter keys (L178-205) unchanged.
- ROUTE (`update_routes` L58-70): keep the 5 guaranteed lines (`render_route_lines` — pure, tested, untouched) but mount them as the mock's sections: `── ASSIGNMENT ──` (immutable + fallback), `policy` lead row (`auto → lead`), `── ELIGIBLE ── / ── EXCLUDED ── / ── ROLE FLOORS ──` rendered **only when** the `RouteViewItem`/projection carries the data (pre-read projection.py:RouteViewItem + the envelopes used by `test_tui_projection.py`; if absent, ship the additive survey result: optional defaulted fields populated from the routing snapshot, else sections omitted — nothing invented). Keep `.route-header` (hairline, letterspaced) — required class. `test_tui_shell_route_shadow_labels` pins the **last** mounted `Static` → insert new sections *before* the shadow-label tail or update that test (§1.3).

### 6.5 Tests (P4)

`tests/unit/test_tui_atelier.py::TestMargin`: `status_glyph` 5-map; `ledger_row` field order/4dp; `ledger_meter(ratio, 23)` at 0/0.3%/0.749/0.75/0.899/0.90/1.0 → token+`▲`-markers; `BudgetLedger.update_ledger` markup contains `LEDGER`, `of $`, legend, and only token names (no hex); Plan: INTEGRATIONS/RECEIPTS render when fed; note-Input only in proposed state; ROUTE: sections conditional; `#budget-ledger` mounted + narrow-hidden. Update: header-copy assertions (`AGENT RAIL`→hairline head, `BUDGET & USAGE`, `ROUTE DECISIONS`, `PLAN · n/m`), `route_shadow_labels` if pinned-last, glyph `●`→`▌` expectations.

**Verify:** `rtk pytest tests\unit\test_tui_sidebar.py tests\unit\test_tui_overlays.py tests\unit\test_tui_atelier.py tests\integration\test_tui_panels.py -q` → screenshots → `graphify update .` → commit `feat(tui): atelier margin — letterspaced tabs, agent ledger, pinned LEDGER, mini-panels`.

---

## 7. Phase 5 detail — Full-bleed approval band + composer band

**Files:** `app.py` (compose relocation), `widgets/interrupts.py` (DEFAULT_CSS L92-136, compose L202-223), `widgets/composer.py` (DEFAULT_CSS L215-284, compose L328-341, `_refresh_queue` L360-373, `_refresh_status` L375-380, `on_button_pressed` L550-556), tests: `tests/unit/test_tui_approval.py`, `tests/unit/test_tui_composer.py`, `tests/integration/test_tui_boot_pilot.py`, `test_tui_shell_early_events_before_mount` / `..._cancellation_preserves_state`.

### 7.1 Approval → full-bleed band (README honest #5: *the* structural change; everything else is TCSS)

1. **Relocation (app.py:284 → after the `with Horizontal(id="main-container")` block):** `#interrupt-container` becomes a top-level sibling between `#main-container` and `#prompt-composer` — approvals gate the *run*, not the 60%-column (mock: the band spans all 120). All id-based lookups (`update_views` L761-767, `_mount_onboarding` L546-555) keep working unchanged. ⚠ OnboardingPanel is *also* mounted into `#interrupt-container` (L546-555) — it becomes full-bleed too. Consequence: pre-read `tests/integration/test_tui_boot_pilot.py` + `tests/unit/test_tui_onboarding.py`; if either asserts the panel inside `#chat-container`, change the mount target to `#chat-container` instead (one-line, id-agnostic) — decide by *reading those tests first*, not by assumption.
2. `InterruptWidget.DEFAULT_CSS` (L92-136) → band:
```css
InterruptWidget { width: 100%; height: auto; background: $approvalSurface;
                  border: none; border-left: heavy $approval; padding: 1 2; }   /* 2px → 1 cell, documented */
InterruptWidget:focus-within { border-left: heavy $focusRing; }                  /* was: round→round */
.interrupt-title { text-style: bold; color: $approval; }                          /* + letterspaced 'APPROVAL REQUIRED' */
.interrupt-question { margin: 1 0; color: $text; }
.interrupt-actions { width: 100%; height: auto; margin-top: 1; }
.interrupt-hint, .interrupt-esc  { color: $textMuted; }
#interrupt-input { border: none; border-bottom: dashed $borderStrong;            /* the ainput, mock L153 */
                   background: $approvalSurface; padding: 0 1; height: 1; }
#btn-approve, #btn-reject, #btn-instruct {                                        /* flat underlined words */
    border: none; background: transparent; color: $accent;                        /* mock .act, L102, 297 */
    min-width: 0; height: 1; text-style: underline; }
#btn-approve:focus, #btn-reject:focus, #btn-instruct:focus { text-style: bold; }
```
(The mock's `.focus`-ring lives on the band; theButton variants `success/error/primary` (L209-211) are overridden to flat — keep the Buttons, ids `#btn-approve/#btn-reject/#btn-instruct` + Input `#interrupt-input` are the contract.)
3. Copy/layout deltas: title row → `Horizontal` of `.interrupt-title` (`A P P R O V A L  R E Q U I R E D  [command:run-1]`) + right-aligned `.interrupt-esc` (`esc keeps pending` — moves from the hint, mock L293); hint (L216-219) → `Approve [A] · Reject [R] · Add instruction [E]` (keys *after* the words, mock L297); narrow: 4th act reads `Add instr.` and `esc keeps pending` rejoins the acts row (mock L351) — one narrow branch in `compose()` keyed on `self.screen.has_class("narrow")`.
4. Behaviour: `approved_keyboard_action`/`is_decision_terminal`/typing-guard/Tab-Order/Esc-dismiss/`approved`/`rejected` classes + disable-after-submit (L166-345) — **zero behavioural edits**; only TCSS + the two copy/structure touches above. Terminal rebuild path (`update_interrupt` L225-249) untouched.

### 7.2 Composer band (the ONLY boxed element — and even it keeps no side borders, mock L156-158)

1. `PromptComposer.DEFAULT_CSS` (L215-284):
```css
PromptComposer { width: 100%; height: auto; padding: 0 1; background: $surface;
                 border-top: solid $borderStrong; border-bottom: solid $borderStrong; }
PromptComposer:focus-within { border-top: solid $focusRing; border-bottom: solid $focusRing; }  /* replaces outline, L223-225 */
#composer-queue   { background: $surface; color: $approval; padding: 0 1; }        /* mock .q: $approval! */
#composer-card    { border: none; background: $surface; padding: 0 0; }            /* round box → band-internal */
#composer-input   { min-height: 3; max-height: 8; background: $surface; color: $text; }  /* 3→8 growth: already correct, L251-258 */
#composer-palette { background: $surface; border: none; border-top: solid $border; }  /* flat, was round */
#composer-status  { color: $textFaint; }
#composer-mode    { border: solid $modeQuality; color: $modeQuality; background: $surfaceRaised;
                    padding: 0 1; }                                                  /* the chip, mock L166 */
#composer-send    { border: solid $accent; color: $accent; background: $accentSoft;
                    min-width: 10; margin-left: 1; }                                  /* SEND ⏎ chip, mock L167 */
```
2. Structure: `#composer-actions` (L338-341) gains a leading `Static("›", classes="composer-prompt")` — no: the `›` gutter belongs beside the *input* (mock L304): insert `Static("›", classes="composer-prompt")` (`$accent`, 2ch) into `#composer-card` before the `TextArea` (a 1-row Horizontal, or Grid `2 | 1fr`); `.composer-prompt { width: 2; color: $accent; }` — ochre spend #2.
3. Copy: `_refresh_queue` (L370) → `QUEUED {n} · ^ take back · newest runs after this one` (wide; narrow drops the tail, mock L355) in `$approval`; `_refresh_status` (L378) → `f"{n} chars · / commands · ? shortcuts"` (order per mock L305); `#composer-mode` label already `MODE {mode}` → uppercase +, when narrow, just the mode word (`QUALITY`, mock L357); `Button("Send")` → `Button("SEND ⏎", id="composer-send")` (mock L305). Mode→chip color: `set_mode_token()`-style pass in `update_views` — the app already knows `routing_mode`; map quality/economy/manual → `modeQuality/Economy/Manual` (same dict as the dateline), else `$text`.
4. Behaviour: history/take-back/stash/palette/ghost/Enter-vs-Ctrl+Enter/`should_send_on_enter`/`on_button_pressed` (L457-556) — **no logic edits**; `on_button_pressed` id check (`composer-send`, L551) survives the label change. `COMPOSER_PLACEHOLDER`/`COMPOSER_VALIDATING_TEXT`/`STASH_RECEIPT`/`MAX_PALETTE_ROWS` constants untouched (`test_placeholder_constant_exact` etc.).
5. ⚠ `#composer-mode`/`#composer-send`/`#composer-status` ids are not in the pinned list but are queried by tests/integration — grep before renaming anything (plan: nothing renamed).

### 7.3 Tests (P5)

Add `tests/unit/test_tui_atelier.py::TestBands`: composer TCSS contains `border-top: solid $borderStrong` + `:focus-within` flip and **no `round`** (source-inspection-friendly, mirrors `test_composer_module_conventions`); queue/status copy shapes; approval band: `.approval-band` classes present, `esc keeps pending` in title row, narrow `Add instr.` branch, `InterruptWidget` keeps `approved`/`rejected`/`collapsed`-free contract classes after `update_interrupt` (regression-cangle existing `test_tui_approval.py`); relocation: `#interrupt-container` is a child of `Screen` (not `#chat-container`) and `OnboardingPanel` still mounts into it (or the documented alternative) — assert via `app.query_one("#interrupt-container").parent`. Integration: `test_tui_shell_early_events_before_mount`, `..._cancellation_preserves_state`, `test_tui_boot_pilot` must stay green (the relocation is the risky one — that's why it's isolated in P5, *after* P2/P3/P4 are independently stable).

**Verify:** `rtk pytest tests\unit\test_tui_approval.py tests\unit\test_tui_composer.py tests\unit\test_tui_atelier.py tests\integration -q` → screenshots → `graphify update .` → commit `feat(tui): atelier approval band + composer band (full-bleed interrupts)`.

---

## 8. Phase 6 detail — Overlays + narrow behavior

### 8.1 Shared overlay shell (all 5, `src/skail/tui/overlays/*.py` — markup + new TCSS, zero logic)

Every overlay gains a `DEFAULT_CSS`/`CSS` block + a 3-part composition, keeping every Screen class, method, constant, and `on_key` as-is:

```
.ovl-head  → 1 row: letterspaced TITLE ($text, bold) + right hint ($textFaint, e.g. 'esc closes')   [mock L370]
.ovl-rule  → 1 row: border-bottom: double $borderStrong (the strong rule, L371)
content    → (per overlay below)  1-col #hairline between 36-col columns where the mock splits (L372)
.ovl-foot  → 1 row: $textFaint focus/a11y note (mock L398)  +  Screen { background: $surfaceInset 80% }
```
- TCSS: `Screen { background: $surfaceInset 80%; }` + `.ovl-head/.ovl-foot { color: $textFaint; }` + kbd spans via `[on $surfaceRaised]` markup. Deliberately **not** migrating `Screen`→`ModalScreen` (§1.2 #15: the doubles-driven unit tests + the `$surfaceInset 80%` self-dim achieve the design; the mock's "dimmed page behind" is a backdrop, which a non-modal full-bleed screen also paints). Esc closes, focus-restore (`close_overlay`) — untouched.
- `?` shortcuts (overlays/shortcuts.py): keep `group_shortcuts`/`filter_shortcuts`/`render_shortcut_lines` + `#shortcuts-filter` Input (tests L315-346) and the type-to-filter; the *composed* view becomes the two-column kbd/desc grid (36/1/36 — mock L372-395) fed from the same grouped registry: `Static(f"[on $surfaceRaised] {binding} [/]  {desc}")` rows, left column = Run/Composer/Navigation, right = Agents/Approvals/Session/Display (GROUP_ORDER is the grouping — the mock's 12+approval-keys rows are a subset; shipping the full 18 is a documented superset). Footer note = `focus ring = $focusRing token · status is never colour-only (glyph + word)` (mock L398 verbatim).
- Theme picker (theme_picker.py): rows + `Dark/Light/System` + `●` marker + move-preview/commit/Esc-restore (L29-111, tested) — dressing only: `.ovl-head` `T H E M E` + hint `enter commits · esc restores`; each option row shows a 3-swatch line (`[on $background]  [/][on $surface]  [/][on $accent]  [/]`) — the mock's "light token set + in-page toggle" proof. Live preview keeps calling `apply_theme_preview` (app.py:1142-1147) — which now also refreshes the rail/LEDGER (§3.1), so the *preview must re-run* `budget_token_for_ratio` (README honest #10) — it does, because the dateline/ledger markup re-render on `refresh_css()`; add the defensive ledger/rail refresh here too (§3.1).
- Model picker / Missions / Transcript overlays: `.ovl-head` + rule + their existing rows (missions keeps `missions_header`/`missions_rows`/`can_spawn`/`detail_lines`/confirm-C-Esc flow + `MAX_CHILDREN = 3` — all pinned by tests L430-480); transcript overlay = `ChatTranscript#transcript-full` (already inherits the P3 row redesign) + `.ovl-head` `T R A N S C R I P T` + `esc closes · ^⇧O pager` + the pager-fallback copy constants (L19-23, tested by `test_transcript_pager_fallback_copy`).

### 8.2 Onboarding (`widgets/onboarding.py`) — dress only

`OnboardingPanel` keeps: steps/ladder, `#onboarding-key` Input (L157, 163-176), F/T/R/B/V keys, secret masking (L1-7 contract). Restyle only: `.onb-head` letterspaced step ladder (the `SETUP` line, L72) + hairline, the trust/theme/ready steps on `$background` (no box), the theme-step swatch row mirrors §8.1 theme-picker. **No** copy or step-order changes (`tests/unit/test_tui_onboarding.py` + boot-pilot integration).

### 8.3 Narrow behavior (Phase 7; trigger + class plumbing already done in §4.6)

Width < 100 (existing `_check_screen_width`, app.py:324-337 → also sets `Screen.narrow`). TCSS + the 3 narrow branches from P2/P5, plus:

| Narrow rule (mock L96-98, 317-361) | Mechanism |
|---|---|
| `#hairline` + `#sidebar-container` (+ `#budget-ledger`) hidden | `.narrow #hairline, .narrow #sidebar-container, .narrow #budget-ledger { display: none; }` (extends the legacy `.narrow #sidebar-container` rule, app.py:163-165 — kept for the integration test) |
| `#main-container`→`#chat-container` full-width, no rules | existing (L159-162) + new padding-0 |
| Clock gutter hidden; role cell 11ch; sub2 keeps 3ch indent | `.narrow .msg-clock { display: none; }` + `.narrow .msg-role { width: 11; }` (roles stay → status never colour-only, accessibility row) |
| Dateline wraps to 2 rows | markup branch in `_render_dateline(narrow=True)` (§4.3) + `#dateline.narrow { height: 2; }` |
| Tab-drawer strip `A G E N T S … ^A ^P ^R ^B` | new 1-row `#margin-drawer` (`Horizontal`, `display:none` in wide): letterspaced *active-tab* label + 4 `[on $surfaceRaised]` kbd chips.fed from the same tab-activation handler as §6.1 (single source of the active name). The TabbedContent itself stays mounted-but-hidden — `^A/^P/^R/^B` keep switching state invisibly; **panels are intentionally not shown in narrow** (the 88×30 frame shows none; documented in DoD). |
| Masthead drops the date, keeps `HH:MM:SS` | `format_masthead(..., narrow=True)` (§4.2) |
| Approval/composer compact | P5 narrow branches (`Add instr.`, `esc` → acts row, queue tail dropped, `N chars · / cmds · ? keys`, `QUALITY` chip) |
| Footer 4+⋯+`? all` | `AtelierFooter` narrow set (§4.5) |
| `↓ {n} new · End` dock | P3 narrow copy branch |

### 8.4 Tests (P6/P7)

`tests/unit/test_tui_atelier.py::TestOverlaysNarrow`: `.ovl-head`/`esc closes` presence in all five overlays' compose-markup; shortcuts 2-col + kbd markup; theme/model/missions/trainscript dressings don't change `rows()`/`header()` outputs (regression vs existing unit tests); drawer = active-tab name + 4 kbd; TCSS-assertions for every narrow rule above (source-inspection friendly: assert the *rule strings* exist in the module sources, the established pattern); integration: `test_tui_shell_responsive_narrow_fallback` extended to assert `Screen.narrow` + drawer presence + `#hairline` hidden at width 99.

**Verify:** `rtk pytest tests\unit\test_tui_overlays.py tests\unit\test_tui_atelier.py tests\integration\test_tui_shell.py -q` → narrow+wide screenshots → `graphify update .` → commits `feat(tui): atelier overlays — shortcuts/theme/model/missions/transcript dressing` and `feat(tui): atelier narrow mode (drawer, 11-col roles, compact bands)`.

---

## 9. Phase 8 — polish, risk register, rollback, acceptance

### 9.0 Polish (P8) — the "exactly" pass

1. **Reduced-motion sweep:** with `SKAIL_REDUCED_MOTION=1` — no shim timer toggling (`ChatTranscript` gate, §5.3), `ActivitySpinner` renders the reduced frame (existing), `.reduced-motion *` transition-kill (app.py:173-175) retained, streaming = static `$textFaint` + `$accent` caret. Screenshot variant + unit assert on the TCSS strings.
2. **Focus discipline:** row/band/chip focus = `border-left: heavy $focusRing` (rows), border-flip (composer), `$selection` (rail); `Screen:focus-within` outline (app.py:183-185) retained deliberately (a11y; the mock shows no screen-level ring — listed as a conscious retention).
3. **Accent-discipline audit:** grep the final TCSS for `$accent` — allowed only: YOU role, composer `›`/SEND, active-tab underline, streaming caret, approval act words (mock's `.act`), error/approval *focus* inversions. Anything else = fix.
4. **Width budget proofs (unit):** 120-col: 9+2+10+flex measure = 78-2 padding = 76 chars of prose; margin: spaced active tab + 3 plain + gaps ≤ 37; drawer/fits; LEDGER 23+legend ≤ 37. These are the letterspacing-bake hazards (README honest #3).
5. **Screenshot tooling:** extend `scripts/dev_tui_screenshot.py` with `--out DESIGN_DIR` (default `current`) and `--theme dark|light` + `--reduced-motion` (boot-args to `SkailApp(theme_name=…, reduced_motion=…)`); capture `design/tui-redesigns/atelier/atelier-main.svg` (120×40), `atelier-main-narrow.svg`, `atelier-main-light.svg`, + `.txt`. Before-SVGs already archived at `27ace87` under `current/`.
6. **Docs:** update `tasks/plan.md` (acceptance record), the TUI feature contract under `docs/skail/`, and add an "implemented" note + pointer in `design/tui-redesigns/README.md`. Commit: `docs(tui): record atelier implementation`.

### 9.1 Risk register (Textual-1.0.0 limits → mitigations)

| # | Risk | Likelihood | Impact | Mitigation / fallback |
|---|---|---|---|---|
| R1 | TCSS has no `letter-spacing`; baked spacing changes character budgets | certain (by design) | overflowing 37-col margin | Bake **only** the 4 tab labels (active only — one at a time) + section heads; unit-assert widths (§9.0.4); plain+bold+`$textMuted` everywhere else (README honest #3 prescribes exactly this) |
| R2 | No `box-shadow`; 2px inset focus ≈ 1-cell border | certain | 1-col layout shift inside rows when focused | Mock's own honest list (README #2) declares this a fidelity degradation carrying no information; row children are fixed-width so the `1fr` measure absorbs the 1-col border |
| R3 | `TabsTab.-active` / `#tabs-underline` selector names drift in 1.0.0 | medium | underline silently missing | Runtime-verify via SVG after P4; wrong selector = no-op; fallback: keep `text-style: bold; color: $text` on `-active` (degraded-but-legible), never rebuild the TabbedContent (ids are contract) |
| R4 | `ContentSwitcher`/`TabPane` internals keep默认 borders/背景 | medium | stray boxes in a borderless design | Component-scoped TCSS (`#tabs TabPane`, `#tabs ContentSwitcher` — the latter already targeted at app.py:151-154); visually verify; accept a 1px `Tabs` underline if un-killable, logged as fidelity delta |
| R5 | `›` gutter beside a growing `TextArea` (3→8 rows) | low | gutter misalignment on focus/scroll | `content-align: left top` + the TextArea keeps 100% of the *remaining* width; the prompt glyph is static 1×1 — the mock shows it once (L304), continuation lines are inside the TextArea |
| R6 | Projection data gaps: ChildView progress (8/12 · 2 children), RouteItem eligible/excluded/floors, revision *history*, budget burn/headroom | medium | design shows fields we may not have | **Omit, never invent.** Sections render only when the underlying view model carries the data; optional defaulted dataclass fields (survey step in P4) are additive and populate through the existing event flow; burn/headroom explicitly conditional |
| R7 | Meter rounding vs mock (▓▓ at 0.3%; cells 20/22/23 across the mock's own frames) | certain | "not exactly the picture" | Adopted rule: dateline = 10 cells, margin contexts = 23 cells (`BUDGET_LEDGER_CELLS`), `round(ratio*cells)`, ≥1 fill when spend>0; documented in DoD as the mathematical reading of the artwork |
| R8 | HTML light-override block omits 9 tokens (mode*/delegation/diff*) | certain (already) | wrong light colors if implemented from the HTML | §3.3: README palettes table is authoritative; both palettes here are complete 36/36; test round-trips guard it |
| R9 | `#interrupt-container` relocation changes where `OnboardingPanel` renders; boot-pilot/shell integration may be position-sensitive | medium | P5 failures | Read `test_tui_boot_pilot.py` + `test_tui_onboarding.py` **first** (P0 checklist); if they anchor inside `#chat-container`, retarget the mount (1 line) instead of the relocation; the relocation is isolated in its own commit |
| R10 | Source-inspection tests (no-hex, conventions, "never jumps to Route", missions-confirm) | medium | quiet red suite | P0 freezes the inspected patterns; edits keep zero hex (tokens only), keep every inspected symbol/flow; copy changes that *must* break an assertion are the sanctioned "update tests" of the task — each such update is listed in the phase that causes it |
| R11 | `$border 55%` percentage-qualifier colors may not parse in 1.0.0 TCSS | low | rule crash at boot | Fallback = plain `$border` (one-keystroke diff); caught immediately by the first SVG/boot |
| R12 | Replacing `Footer()` with `AtelierFooter` loses contextual key hints | certain | none functional (keys handled by App/Screen, not Footer) | Display-only widget; all 12+ bindings truthful in the `?` overlay; `Binding(priority=True)` handling unaffected; `test_footer_hints_mention_overlays` reads `ACTION_REGISTRY`, not the widget (verify in P0) |
| R13 | Added timers (1 Hz masthead, 0.5 Hz shim) vs `test_tui_perf.py` | low | perf regression | Shim interval created once, toggles one class; if perf slips, gate the shim timer to exist only while a `.streaming` row exists |
| R14 | Theme switch leaves stale *inline* token resolutions (rail slot colors, ledger border) | medium | wrong colors until next repaint | §3.1 defensive `refresh()` of `#agent-rail`/`#budget-ledger` in `apply_theme`; verified by the alt+T preview unit + a manual light/dark toggle |
| R15 | Narrow hides panels by design; `^P` etc. switch invisibly | certain | UX surprise | Documented design consequence (mock's 88×30 frame shows no panel); drawer shows the active tab name so state is legible; pane-in-narrow = approved follow-up, not scope creep |

**Two-strike rule:** any failure that survives two consecutive focused fixes stops the phase → report to the orchestrator (per the working agreement); do not self-escalate, do not broaden the diff.

### 9.2 Rollback

- Land `atelier/baseline` tag at `27ace87` (P0). Each phase = exactly one Conventional-Commit (messages: `feat(tui): adopt ATELIER token palettes`, `feat(tui): atelier chrome…`, `feat(tui): atelier transcript…`, `feat(tui): atelier margin…`, `feat(tui): atelier approval band + composer band…`, `feat(tui): atelier overlays…`, `feat(tui): atelier narrow mode…`, `feat(tui): atelier polish & docs`) — mirrors the README's 3-commit suggestion, finer-grained.
- Targeted revert: `rtk git revert <sha>` — phases are independent because P1 touches only `theme.py`+theme-tests, P2-P7 touch disjoint compose/TCSS regions, and every phase's suite is green *before* the next starts.
- Full rollback: `rtk git reset --hard atelier/baseline` (unpublished branch work); screenshot evidence lives under `design/tui-redesigns/` (additive files, no conflicts).
- Theme-only rollback (if the retune itself is rejected): reverting P1 restores the old palette *without* touching later phases — values are name-compatible by construction.

### 9.3 Acceptance checklist

**Before (already archived):** `design/tui-redesigns/current/current-main.svg` + `-narrow.svg` + `.txt` @ `27ace87`.
**After (P8):** `design/tui-redesigns/atelier/atelier-main.svg`, `atelier-main-narrow.svg`, `atelier-main-light.svg` (+ `.txt`) via `python scripts/dev_tui_screenshot.py --out design/tui-redesigns/atelier [--theme light] [--reduced-motion]`; eyeball-diff each against the corresponding redesign-1.html frame.

- [ ] P0: contract freeze read (4+ source-inspection tests, boot-pilot, onboarding, panels) + baseline suits green + `atelier/baseline` tag
- [ ] P1: 36/36+36/36 values, `validate_theme` green incl. 6-digit/8-digit rejection, dual registration assertions, theme tests rewritten; **no other file touched**
- [ ] P2: masthead+strong rule; `#dateline` token markup (no hex — audited); 80/1/39 + `#hairline`; `#transcript-header`; `AtelierFooter` 8+`⋯`+`?`; narrow/Screen class plumbing; shell+boot integration green
- [ ] P3: 4-col grid (9/2/10/1fr), `role-*` TCSS tints, `fold_glyph` (+/−/└), `collapsed` visuals, shimmer+caret + reduced-motion, dock copy; keyed-recon + no-hex + collapse-click tests green
- [ ] P4: tab underline + active-letterspacing; ledger rows + `$selection`; `#budget-ledger` (23 cells, 0.75/0.90, `▲`); plan/route/budget sections + `#plan-change-note`; panel tests updated where pinned
- [ ] P5: `#interrupt-container` full-bleed relocation + `$approvalSurface`+`$approval` left-bar band; dashed answer input; flat acts; composer band (top/bottom rules only), `›`, MODE/SEND chips, queue/status copy; approval/composer/headless-parity suites green
- [ ] P6: all 5 overlays + onboarding dressed via `.ovl-*`; shortcuts 2-col; note-level copy only
- [ ] P7: every narrow rule of §8.3, drawer strip, 11-col roles, 2-row dateline, compact bands, 4-key footer; `responsive_narrow_fallback` extended+green
- [ ] P8: reduced-motion variant, accent audit, width proofs, screenshots (before/after), docs, `graphify update .`
- [ ] Final: `rtk pytest -q` (full offline), `python -m ruff check src tests scripts evals`, `python -m mypy src\skail`, `python scripts\smoke.py --fake-provider`, complete-diff self-review (AGENTS.md)

---

## 10. Definition of done — "ATELIER replicated exactly"

Done when **every** checkbox below is true, and every consciously-accepted fidelity delta is recorded (the list at the end). Feature numbering = the README coverage table.

- [ ] **1-8, 57** Masthead (`S K A I L` + version + optional provider chip + `FRI 18 SEP · 14:32:07`), strong rule; dateline `MODEL · MODE · SPEND+10-cell meter+pct · AGENTS ●n running · n queued` in `$modeQuality/Economy/Manual`, `$budgetFill/Warning/Critical`, `$agentOne`; hairline rule; 1 row wide / 2 rows narrow; both palettes = full 36-token retunes; switching (dark/light/system, alt+T preview, Esc-restore) intact
- [ ] **9** 80/1/39 split + 1-col hairline (67/33); narrow → single column
- [ ] **10** Margin tab strip: borderless, letterspaced active label, 2-cell `$accent` underline; ids `#tabs`/`tab-*` + ctrl/`/`-command switching unchanged
- [ ] **11-12, 21-22** Transcript: 4-column `clock(9)│fold(2)│role(10)│measure(flex)`; scroll/pin/End-re-pin; `+/−` collapse in the fold gutter (`.collapsed`), in-place streaming (no remount), `↓ n new events · End to re-pin` dock
- [ ] **13-20** Roles: YOU `$accent` · LEAD `$text` · `AGENT n ●` slot-colored · TASK · `TOOL ▸` (+sub2 detail) · ERROR on `$errorSurface` · APPROVAL on `$approvalSurface` · RECEIPT `$diffAdded` — glyph+word, never colour-only; role/timestamp data from the existing projection (`timestamp` since projection.py:37)
- [ ] **23-29** Approval: full-bleed band below the split, 1-cell `$approval` bar on `$approvalSurface` (the only tinted element), `A P P R O V A L  R E Q U I R E D [command:run-1]` + question + workspace/reason + dashed-underline answer + underlined `Approve A / Reject R / Add instruction E` + `esc keeps pending`; A/R/E/Esc/typing-guard/approved/rejected semantics untouched
- [ ] **30-33** Margin ledger: `● ∙ ✓ ✕ ⊘` + words + slot tokens, task lines, (conditional) slot-colored step progress, `$selection` focus, `⏎ detail · M mission control`; select-never-switches-tab; M → Mission Control
- [ ] **34-40** PLAN: items `✓ ▌ ⊘` + REVISIONS/INTEGRATIONS/RECEIPTS hairline sections + left-barred proposed prompt `Accept A / Reject R / Change C` + note field. ROUTE: policy/ELIGIBLE/EXCLUDED/ROLE FLOORS/ASSIGNMENT (conditional where unpopulated) + immutable/fallback lines. Both read-only; A/R/E keys preserved
- [ ] **41-43** Budget: dateline meter + pinned LEDGER (`$x of $y`, pct+`▲(▲)`, 23-cell `▓/░`, `warn ┊ 75%  critical ┊ 90%`) + BUDGET tab breakdown + `thresholds 0.75 / 0.90`; tokens flip at 0.75/0.90 via `budget_token_for_ratio`
- [ ] **44-49** Composer: `$approval` queue line (`QUEUED n · ^ take back · newest runs after this one`); 3→8-row `#composer-input` under a `›` gutter; meta `n chars · / commands · ? shortcuts`; `$modeQuality`-bordered `MODE <MODE>` chip; `SEND ⏎` on `$accentSoft`; slash palette + history/take-back/stash + Enter/Ctrl+Enter semantics intact; the only bordered band, focus = border flip to `$focusRing`
- [ ] **50** Footer: 8 bindings + `⋯` + `? all shortcuts` (`alt+T` shipped as-is); all 12+ in the `?` overlay
- [ ] **51** Narrow (<100): margin+hairline+LEDGER hidden; drawer `A G E N T S … ^A ^P ^R ^B`; clock gutter hidden, role 11ch; 2-row dateline; full-bleed approval/composer; compact acts/meta; 4-key footer
- [ ] **52-56** Overlays: `?` shortcuts as the 36/1/36 two-column kbd/desc screen with `$surfaceInset 80%` backdrop + focus-note; `^O` transcript pager, `alt+T` theme (live preview), `alt+P` model, `^T` missions (3-cap, confirm-C, Esc) — all behaviors bit-identical, dresses only
- [ ] **Accessibility:** 12.6:1 dark contrast; `$textFaint` = metadata only; focus = border/`$selection` + never colour-only states; reduced-motion = static caret mode; light = complete 36-token set
- [ ] **Tests:** existing suites (unit+integration, `rtk pytest -q`) green; source-inspection contracts intact; `tests/unit/test_tui_atelier.py` + per-phase additions green; theme expectations = the new palettes
- [ ] **Evidence:** before/after SVG+txt artifacts (§9.3), phase-by-phase green screenshots, docs/plan updates, `graphify update .` history

**Recorded, accepted fidelity deltas (mock→terminal):** letterspacing baked only where permitted (active tab + section heads) — R1; 2px inset focus → 1-cell border — R2; kbd chips = `$surfaceRaised` fill without 1px border/radius (footer) — R12/§4.5; dateline meter rounding (▓▓@0.3% → round/min-1 rule) — R7; LEDGER 23 / dateline 10 / states-illustrative-20 — R7; footer 8+⋯ (12 exceed one row — README honest #7) — deliberate; `?` overlay = 18-binding superset of the mock's 12+4 — deliberate; light-theme values from the README table where the HTML override omits 9 tokens — R8; mock-only fields (progress/eligible/burn/headroom/revision-history) rendered only when the projection supplies them — R6; `Screen:focus-within` outline retained for a11y — §9.0.2; narrow shows no panel content (design intent) — R15.

**Done = ATELIER replicated exactly** ⇒ after this checklist: every region of `redesign-1.html` (wide 120×40, narrow 88×30, `?` overlay, both palettes, token-state semantics) is present in the Textual app, every feature of the 57-row coverage table survives with its test, and the only deviations are the ones enumerated directly above — each traced to a Textual/TCSS limitation the design's own honest list anticipated.

*— end of plan —*
