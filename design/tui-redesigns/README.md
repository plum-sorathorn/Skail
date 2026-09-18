# Skail TUI — Main Chat Page: Three Redesign Directions

Three complete, self-contained redesigns of the Skail Textual main chat page. Each is a
zero-dependency HTML mockup (inline CSS only, no network, no images, no JS) that renders a real
terminal frame at **120 columns**, plus a **narrow-mode frame at 88 columns**, plus one **overlay
frame**, plus a **token-state strip**. Every one of the 57 inventoried features is placed in every
design — see [Feature coverage](#feature-coverage-all-57-inventoried-features--all-three-redesigns).

| # | File | Name | Direction | One-line pitch |
|---|------|------|-----------|----------------|
| 1 | [`redesign-1.html`](./redesign-1.html) | **ATELIER** | Refined editorial-terminal | A printed page: hairline rules, a timestamp gutter, marginalia instead of panels. Almost nothing is boxed. |
| 2 | [`redesign-2.html`](./redesign-2.html) | **MERIDIAN** | Dark-tech glassy HUD | Three surface depths replace borders; an agent **lifeline spine** colours the transcript gutter; budget becomes a vertical column. |
| 3 | [`redesign-3.html`](./redesign-3.html) | **FOUNDRY** | Dense pro-dashboard | The transcript becomes a **tabular log grid**; the agent rail is permanent; a one-line **status ticker** says more than the old strip. |

> **Filename note.** The brief suggested `redesign-1-<name>.html`; the acceptance check pins
> `design/tui-redesigns/redesign-1.html`. The short names are used so the exact-path check passes;
> each design's name is the first thing printed inside its file (`ATELIER · REDESIGN 1`, …) and in
> this README.

Open any file in a browser and use the chips at the top: **Both / Wide 120×40 / Narrow 88×30** and a
**dark / light** theme toggle (pure CSS, `:has()` — no script). The light variant is a real second
token set, not a filter, because Skail ships `DARK_THEME` and `LIGHT_THEME` in
`src/skail/tui/theme.py`.

All three consume the **exact 36 token names** from `REQUIRED_TOKENS` in
`src/skail/tui/theme.py` (`background … link`, including the ones the brief omitted:
`surfaceInset`, `textFaint`, `accentSoft`, `modeQuality/Economy/Manual`, `delegation`,
`budgetEmpty`, `diffAdded(+Surface)`, `diffRemoved(+Surface)`, `dimmed`, `errorSurface`,
`shimmerBase/Peak`, `selection`). Budget thresholds stay at the source-of-truth values
`BUDGET_WARNING_THRESHOLD = 0.75` / `BUDGET_CRITICAL_THRESHOLD = 0.90`, and each mockup shows a
`REDUCED MOTION` row because `reduced_motion_enabled()` is part of the contract.

---

## Redesign 1 — ATELIER
### Refined editorial-terminal · "Ink & Bone" / "Newsprint"

**Rationale.** The current page is a stack of boxes: a boxed sidebar, a boxed approval card, a boxed
composer. Boxes cost columns (2 per side) and they flatten hierarchy — everything ends up equally
loud. ATELIER removes almost all of them and rebuilds hierarchy the way print does: **rhythm,
rules, indentation and a fixed gutter**. The transcript reads like a typescript with a clock in the
margin; the sidebar becomes *marginalia*; the approval becomes a **rubricated band** (a 2px ochre
margin bar) — the only tinted element on screen, which is why it wins attention without shouting.
One accent (ochre) is spent on exactly three things: the `YOU` role tag, the composer prompt / SEND,
and the active tab underline. Everything else is bone on warm charcoal.

**Signature moves**
- **Four-column entry grid**: `clock (9) │ fold (2) │ role (10) │ measure (flex)`. Continuation lines
  inherit the measure offset for free, so wrapped prose and `└` sub-rows align perfectly.
- **Dateline instead of a status strip**: model · mode · spend+meter · agents on one letterspaced line
  between two rules.
- **LEDGER block pinned to the foot of the margin** — the budget meter is always visible without
  leaving the chat; the BUDGET tab keeps the full breakdown.
- **Approval as a full-bleed band** with a 2px `$approval` left margin, dashed-underline answer field,
  and actions as underlined words + `kbd` glyphs.
- **Composer as a bordered band** (top/bottom rules only) with a `›` prompt gutter and a 3-row minimum
  input that grows to 8.

**ASCII wireframe (120 × 40)**
```
S K A I L  0.1.0                                    [ANTHROPIC]   FRI 18 SEP · 14:32:07
════════════════════════════════════════════════════════════════════════════════════════════════
MODEL auto · MODE quality · SPEND $0.0142 / $5.00 ▓▓░░░░░░░░ 0.3% · AGENTS ●1 running · 2 queued
────────────────────────────────────────────────────────────────────────────────────────────────
 TRANSCRIPT                             run-1 · 41 events · pinned ║ A G E N T S  PLAN  ROUTE  BUDGET
─────────────────────────────────────────────────────────────────  ║ ───────
14:32:01  +  TASK      ✻ Starting Skail runtime…                   ║ ●  AGENT 1  RUNNING       $0.0142
14:32:04  −  YOU       Fix the failing budget tests, then summ…    ║    survey tui layout + patch budget
14:32:05  −  LEAD      Reproducing first, then patching the two…   ║    ▓▓▓▓▓▓▓▓░░ 8/12 · 2 children
            └          plan r3 accepted · 3 items · revision 2/3   ║ ∙  AGENT 2  WAITING       $0.0000
14:32:06  −  AGENT 1 ● Reading the failing assertions before…      ║    write release notes
            └  TOOL ▸  read_file  tests/unit/test_budget.py        ║ ✓  AGENT 3  COMPLETE      $0.0091
                           214 lines · 12 ms · sha 4f2a91c         ║ ✕  AGENT 4  FAILED        $0.0012
            └  TOOL ▸  run  python -m pytest tests/unit -q         ║    flaky probe · ↻ retryable
                           exit 0 · 41 passed · 0 failed · 3.2 s   ║ ⊘  AGENT 5  CANCELLED     $0.0000
14:32:11  +  RECEIPT   ✓ plan@r3 · 2 changesets · $0.0041          ║ ⏎ detail · M mission control
14:32:12  −  LEAD      Fixed 2 assertions; 41 passed, 0 failed.    ║ ── LEDGER ─────────────────
14:32:14  +  ERROR     reservation expired for AGENT 2 — retried   ║ $0.0142 of $5.00     0.3%
14:32:15  +  APPROVAL  command:run-1 awaiting a decision ↓         ║ ▓░░░░░░░░░░░░░░░░░░░░░░░
14:32:16  +  LEAD      Summarizing the diff and the receipts▌      ║ warn ┊ 75%   critical ┊ 90%
──────────────── ↓ 4 new events · End to re-pin ───────────────────║
────────────────────────────────────────────────────────────────────────────────────────────────
┃ APPROVAL REQUIRED [command:run-1]                                  esc keeps pending
┃ EnsureAllow: python -m pytest tests/unit -q
┃ workspace src/skail · reason: shell command outside the allow-list
┃ optional answer or comment ⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯
┃ Approve A     Reject R     Add instruction E
────────────────────────────────────────────────────────────────────────────────────────────────
 QUEUED 2 · ^ take back · newest runs after this one
 ›  Fix the failing budget tests, then summarize.▌
 44 chars · / commands · ? shortcuts                [MODE QUALITY] [SEND ⏎]
────────────────────────────────────────────────────────────────────────────────────────────────
 ^C quit · ^B budget · ^A agents · ^P plan · ^R route · ^T missions · ^O transcript · ⌥T theme ⋯
```

**Narrow (88 cols).** Margin ledger hidden; tabs collapse into a one-row **drawer strip** with
`^A ^P ^R ^B` chips; the clock gutter hides (role tags stay, so status is never colour-only); the
dateline wraps to two rows; approval + composer go full-bleed.

**Widget mapping (ATELIER)**

| Visual block | Textual widget | TCSS notes |
|---|---|---|
| Masthead + dateline | `Header` subclass (`app.py`) | `height: 1`; no border; `text-style: bold` on the wordmark |
| Status dateline | `Static` w/ Rich markup | `height: 1`; `border-bottom: solid $border` |
| Transcript pane (80 cols) | `ChatTranscript` (`widgets/chat.py`) | `width: 80; padding-right: 2` |
| One entry row | `Horizontal` of 4 `Static` | `width: 9 / 2 / 10 / 1fr`; `.c { }` wraps naturally |
| `└` sub-row / detail line | child `Static` in the same row widget | reuse the fold cell for `└` |
| Margin column (39 cols) | `Vertical` + `TabbedContent` | `border-left: solid $border; padding-left: 2` |
| Tab strip | `TabbedContent` restyled | active: `border-bottom: heavy $accent` |
| Agent ledger | `AgentRail` (`widgets/agents.py`, L79) | `ListView`; focused row `background: $selection` |
| LEDGER block | `BudgetMeter` (`widgets/budget.py`) compact variant | permanently mounted at the rail foot |
| Approval band | `InterruptDeck` (`widgets/interrupts.py`) | `background: $approvalSurface`; `border-left: heavy $approval` |
| Answer field | `Input` | `border: none; border-bottom: dashed $borderStrong` |
| Composer band | `PromptComposer` (`widgets/composer.py` L242: `height: auto; min-height: 3; max-height: 8`) | `border-top/bottom: heavy $borderStrong`, no side borders |
| MODE / SEND chips | `Button` | `border: tall $accent`; SEND `background: $accentSoft` |
| Footer | `Footer` | 1 row; overflow `⋯`, full list lives in the `?` overlay |
| Overlays (^O ? ⌥T ⌥P ^T) | `ModalScreen` (`overlays/*.py`) | backdrop `background: $surfaceInset 80%` |

---

## Redesign 2 — MERIDIAN
### Dark-tech glassy HUD · "Meridian" / "Meridian Day"

**Rationale.** MERIDIAN keeps panels but stops drawing them: **three surface depths do the work that
borders did** — `surfaceInset` (overlay backdrop) → `surface` (transcript) → `surfaceRaised` (rail,
composer, chips). Because there are exactly three, a raised panel can never contain a raised panel,
which structurally prevents the cards-in-cards failure. The signature is the **lifeline spine**: a
3-cell gutter inside the transcript whose stripe recolours to `$agentOne/Two/Three` for whichever
agent owns the row, so two parallel children are legible without reading a single word. Budget is
rotated 90° into a **vertical column** pinned to the rail edge with `75┈ / 90┈` ticks at the threshold
cells. Cyan is structural, violet is delegation/quality, amber is the *only* colour that asks for
permission.

**Signature moves**
- **Command bar of segmented pills** (provider · model · mode · spend+mini-meter · agent count · LIVE) —
  the status strip becomes scannable chips instead of a sentence.
- **Lifeline spine** in the transcript gutter: `╷ ● │ ├ ◆ ✕ ▲` nodes on a coloured stripe.
- **Inverted segment tabs** (active = `$accent` on `$background`) instead of underlines — legible in
  16-colour terminals.
- **Vertical budget column** with threshold ticks, always in the peripheral vision.
- **Approval with `border: double $approval`** — Textual supports `double`, and it reads as "modal"
  without an actual modal.
- **Composer with a focus halo** and a left accent stripe; queue strip as an amber chip above the input.

**ASCII wireframe (120 × 40)**
```
✻ SKAIL 0.1.0  [ANTHROPIC] [MODEL auto] [MODE QUALITY] [$0.0142/5.00 ▓░░░ 0.3%] [●1 AGENT]  [● LIVE] 14:32:07
╭─ TRANSCRIPT ────────────── run-1 · 41 events · pinned ─╮ ╭─[AGENTS]─PLAN─ROUTE─BUDGET──────╮ 100
│ ╷ ▸ TASK     ✻ Starting Skail runtime…           32:01 │ │ ● AGENT 1  RUNNING      $0.0142 │ ╎
│ │ ▸ TASK     Ready. Describe the outcome you…    32:02 │ │   survey tui layout + patch     │ ╎
│ ● ▾ YOU      Fix the failing budget tests, then  32:04 │ │   ▰▰▰▰▰▰▰▰▱▱▱▱ 8/12 · 2 kids   │ 90┈
│ │ ▾ LEAD     Reproducing first, then patching…   32:05 │ │ ∙ AGENT 2  WAITING      $0.0000 │ ╎
│ ├ ▸ TOOL ▸   read_file tests/unit/test_budget…   32:06 │ │   write release notes           │ ╎
│ │ ▸ AGENT 1  Reading the failing assertions…     32:06 │ │   ▱▱▱▱▱▱▱▱▱▱▱▱ slot 2 of 3      │ 75┈
│ ├ ▾ TOOL ▸   run python -m pytest tests/unit -q   32:09 │ │ ✓ AGENT 3  COMPLETE     $0.0091 │ ╎
│ │   └ out    exit 0 · 41 passed · 0 failed · 3.2s       │ │   ▰▰▰▰▰▰▱▱▱▱▱▱ 6/6              │ ╎
│ ├ ▸ TOOL ▸   apply_patch runtime/budget.py +18−6  32:10 │ │ ✕ AGENT 4  FAILED       $0.0012 │ ╎
│ ◆ ▸ RECEIPT  ✓ plan@r3 · 2 changesets · $0.0041   32:11 │ │   flaky probe · ↻ retryable     │ ╎
│ │ ▾ LEAD     Fixed 2 assertions; 41 passed…      32:12 │ │ ⊘ AGENT 5  CANCELLED    $0.0000 │ █
│ ✕ ▸ ERROR    reservation expired — retried once   32:14 │ │ ─────────────────────────────── │0.3%
│ ▲ ▸ APPROVAL command:run-1 awaiting a decision ↓  32:15 │ │ [⏎] detail [M] mission control │
│ │ ▸ LEAD     Summarizing the diff and the recei▌  32:16 │ ╰─────────────────────────────────╯
╰────────── ↓ 4 NEW EVENTS · END TO RE-PIN ───────────────╯
╔═ ▲ APPROVAL REQUIRED [command:run-1] ═══════════════ ESC KEEPS PENDING ═╗
║ EnsureAllow: python -m pytest tests/unit -q                              ║
║ workspace src/skail · reason: shell command outside the allow-list        ║
║ ╭ ▸ optional answer or comment… ───────────────────────────────────────╮ ║
║ [⏎ APPROVE A]  [REJECT R]  [ADD INSTRUCTION E]                          ║
╚══════════════════════════════════════════════════════════════════════════╝
┃▌╭─ COMPOSER ────────────────────────────────────────────────────────────╮
║ │ [QUEUED 2] ^ take back · newest runs after this one                    ║
▌ └ Fix the failing budget tests, then summarize.▌                         ║
║   [44 chars] [/ commands] [? shortcuts] [MODE QUALITY]      [ SEND ⏎ ]   ║
╰──────────────────────────────────────────────────────────────────────────╯
[^C]quit [^B]budget [^A]agents [^P]plan [^R]route [^T]missions [⇧^T]chat [^O]transcript [⌥T]theme [⌥P]model [F1]help
```

**Narrow (88 cols).** Rail → drawer; segments collapse to single letters `A P R B`; the vertical budget
column is replaced by the horizontal meter pill in the command bar; the **spine survives** (it is the one
element still carrying agent identity when the rail is gone); composer shrinks to 2 rows + meta chips.

**Widget mapping (MERIDIAN)**

| Visual block | Textual widget | TCSS notes |
|---|---|---|
| Command bar + pills | `Horizontal` of `Static`/`Button` | `height: 1`; pills `border: tall $border; background: $surfaceRaised` |
| Provider pill | conditional `Static` | mounted only when a provider is configured |
| Transcript panel | `ChatTranscript` (`widgets/chat.py`) | `background: $surface; border: round $border; padding: 0 1` |
| Lifeline spine | 1st `Static` child of each row | `width: 3; text-align: center`; `background` stripe via `border-left: heavy $agentN` on a 1-cell spacer |
| Row fold / role / body / tail | `Horizontal` of `Static` | `width: 2 / 9 / 1fr / 8` |
| Rail panel | `Vertical` + `TabbedContent` | `background: $surface; border: round $border` |
| Segment tabs | `TabbedContent` restyled | active: `background: $accent; color: $background; text-style: bold` |
| Agent cards | `AgentRail` (`widgets/agents.py`) | left stripe = `border-left: thick $agentN`; progress = `ProgressBar`-style glyph run |
| Vertical budget column | `BudgetMeter` (`widgets/budget.py`) **vertical variant** | `width: 4; Vertical` of stacked block glyphs, ticks at cells 3 (90%) and 5 (75%) |
| Approval | `InterruptDeck` (`widgets/interrupts.py`) | `border: double $approval; background: $approvalSurface` |
| Action buttons | `Button` ×3 | primary `border: tall $approval`; focused adds `border: heavy $focusRing` |
| Answer field | `Input` | `background: $surfaceInset; border: tall $borderStrong` |
| Composer | `PromptComposer` (`widgets/composer.py` L242: `height: auto; min-height: 3; max-height: 8`) | `background: $surfaceRaised; border: heavy $focusRing` when focused; left stripe = `border-left: thick $accent` |
| Queue strip | `Static` + chip `Button` | `color: $approval` |
| Footer | `Footer` / `Horizontal` of `Static` | `kbd` chips: `border: tall $borderStrong; background: $surfaceRaised` |
| Overlays | `ModalScreen` (`overlays/*.py`) | backdrop `background: $surfaceInset 85%`, panel `border: round $borderStrong` |

> **Not implementable, and deliberately not load-bearing:** the CSS `box-shadow` halo around the
> composer and SEND. In TCSS this degrades to `border: heavy $focusRing` + `background: $accentSoft`.
> No information is carried by the glow.

---

## Redesign 3 — FOUNDRY
### Dense pro-dashboard · "Foundry" / "Foundry Day"

**Rationale.** FOUNDRY is for the operator, not the reader: someone watching three children, a budget
and a plan at once. Three decisions drive it. **(1) The transcript becomes a tabular log grid** with a
sticky header (`# · TIME · SOURCE · SUMMARY · COST · ST`) — every event now has a cost and a state at a
glance, which a budget-aware harness should have been showing all along. **(2) The agent rail is promoted
out of the tab set into a permanent middle pane**, so the `≤2 child attempts / ≤3 concurrent children`
invariants are always on screen (the AGENTS tab remains, as the detail table). **(3) A one-line status
ticker** absorbs model, mode, spend, budget ratio, per-state agent counts, queue depth, routing and
exclusions — the old strip said four things; the ticker says nine in the same row. Colour is rationed:
graphite everywhere, lime only for `YOU`/focus, semantic hues only for state.

**Signature moves**
- **Log grid** with zebra striping, hanging-indent wrap on SUMMARY, right-aligned tabular COST, and a
  3-cell ST column of state glyphs.
- **Permanent agent rail** (26 cols) between log and inspector.
- **Ticker** with `│`-separated `KEY value` fields that drop right-to-left as width shrinks.
- **Approval as a full-bleed inverted banner** (`$approval` fill, dark text — the only place in FOUNDRY
  where colour fills a whole line) + an action dock that spans all three panes, because an approval gates
  the *run*, not the chat column.
- **Inspector tabs** (AGENTS / PLAN / ROUTE / BUDGET) render as `kv` rows, not cards; the plan
  accept/reject/change prompt is a left-barred inline block.
- **Composer meta line** carries char count, row count (`3 of 8`), cost estimate and queue state.

**ASCII wireframe (120 × 40)**
```
✻ SKAIL 0.1.0 │ run-1 │ sess 8f2a │ PROVIDER anthropic                        [● LIVE] 14:32:07
MODEL auto│MODE quality│SPEND $0.0142/$5.00│BUD 0.3% ▓░░░│AG 1R 1W 1C 1F 1X│QUEUE 2│ROUTE auto→lead│EXCL 1
┌─ EVENT LOG ─── 41 rows · ⏎ expand · ^O pager ─┬─ AGENTS ── 2/3 slots ─┬─[AGENTS]─PLAN─ROUTE─BUDGET─┐
│  # TIME     SOURCE SUMMARY              COST  ST│▸1 ● RUNNING    $0.0142│ [r3/4] ✓ ACCEPTED  14:32:05 │
│ 12 14:32:01 TASK   ✻ Starting Skail…      —   · │   survey tui layout   │ ✓ 1 reproduce failure     A3 │
│ 13 14:32:02 TASK   Ready. Describe the…   —   · │   ▓▓▓▓▓▓▓▓░░ 8/12·2k  │ ✓ 2 patch two assertions  A1 │
│ 14 14:32:04 YOU    Fix the failing budg…  —   · │ 2 ∙ WAITING    $0.0000 │ ▌ 3 summarize + receipt     A1 │
│ 15 14:32:05 LEAD   Reproducing first, t… .0021 · │   write release notes │ ⊘ 4 release notes deferred — │
│ 16 14:32:06 A1     ▸ read_file test_bud… .0000 ✓ │   ▓░░░░░░░░░ 0/6 slot2│ ──────────────────────────── │
│ 17 14:32:09 A1     ▸ run pytest -q exit0 .0000 ✓ │ 3 ✓ COMPLETE   $0.0091 │ REVISIONS r2 → r3 item 4 def │
│ 18 14:32:10 A2     ▸ apply_patch +18 −6  .0000 ✓ │   reproduce failure   │ INTEGRATE pytest·rtk·apply…  │
│ 19 14:32:11 RCP    RECEIPT plan@r3 · 2cs .0041 ✓ │   ▓▓▓▓▓▓ 6/6          │ RECEIPTS  ✓ plan@r3 · $0.0041│
│ 20 14:32:12 LEAD   Fixed 2 assertions;…  .0031 ✓ │ 4 ✕ FAILED     $0.0012 │ ──────────────────────────── │
│ 21 14:32:14 A2     ERROR reservation e…  .0012 ✕ │   flaky probe ↻ retry │ BUDGET  $0.0142/$5.00 · 0.3% │
│ 22 14:32:15 APPR   APPROVAL REQUIRED r…    —   ▲ │ 5 ⊘ CANCELLED  $0.0000 │ ▓░░░░░░░░░░░░ warn75┊crit90  │
│ 23 14:32:16 LEAD   Summarizing the dif…  .0008 ▌ │   superseded by A3    │ ──────────────────────────── │
│ ─────── ↓ 4 NEW · END TO PIN · ⇧⏎ COLLAPSE ─── │ [⏎] detail [M] miss.  │ ▌▲ PLAN r4 PROPOSED BY LEAD  │
│                                                 │                       │  add “update release notes”  │
│                                                 │                       │  [ACCEPT A][REJECT R][CHG C] │
└─────────────────────────────────────────────────┴───────────────────────┴──────────────────────────────┘
▲ APPROVAL REQUIRED [command:run-1]              EnsureAllow: python -m pytest tests/unit -q
  WORKSPACE src/skail │ REASON shell command outside the allow-list          ESC KEEPS PENDING
  ANSWER  [optional answer or comment…]
  [⏎ APPROVE A] [REJECT R] [ADD INSTRUCTION E]                 blocks run-1 · 2 children idle
────────────────────────────────────────────────────────────────────────────────────────────────
 QUEUED 2 · ^ take back · newest runs after this one                    est. $0.004 · ~1.2k tok
 ❯ Fix the failing budget tests, then summarize.▌      [MODE QUALITY]
   44 chars │ / commands │ ? shortcuts │ 3 of 8 rows · ⇧⏎ newline        [SEND ⏎]
────────────────────────────────────────────────────────────────────────────────────────────────
[^C]quit [^B]budget [^A]agents [^P]plan [^R]route [^T]missions [⇧^T]chat [^O]log [?]keys [⌥T]theme [⌥P]model [F1]help
```

**Narrow (88 cols).** Three panes → one, with a **pane switcher** (`LOG AGENTS PLAN ROUTE BUDGET`) taking
the rail/inspector's place; the log drops `#`, `COST` and `ST`; the ticker wraps to two rows; the
approval banner stays full-bleed (it is the one thing that must never be collapsed).

**Widget mapping (FOUNDRY)**

| Visual block | Textual widget | TCSS notes |
|---|---|---|
| Title bar | `Header` subclass (`app.py`) | `height: 1; background: $surfaceRaised` |
| Status ticker | `Static` (`projection.py` fields) | `height: 1–2; overflow: hidden`; fields dropped R→L under 100 cols |
| Event log | **`DataTable`** (replaces the row list in `widgets/chat.py`) | columns `#4 · TIME7 · SOURCE7 · SUMMARY 1fr · COST8 · ST3`; `zebra-stripes: true`; `cursor-type: row` |
| Log header | `DataTable` header | `background: $surfaceInset; color: $textFaint` |
| Expanded row detail | `DataTable` row expand / child `Static` | restores the full role word + tool args |
| Agent rail pane (26 cols) | `AgentRail` (`widgets/agents.py`) | `border-left/right: solid $border`; `ChildView` (`projection.py` L135) is the row model |
| Inspector pane (32 cols) | `Vertical` + `TabbedContent` hosting `widgets/plan.py`, `route.py`, `budget.py`, `agents.py` | tabs `box-shadow: inset 0 2 0 $accent` equivalent = `border-top: heavy $accent` |
| kv rows | `Horizontal` of 2 `Static` | `width: 11 / 1fr` |
| Plan accept/reject/change | inline block in `widgets/plan.py` | `border-left: thick $approval; background: $approvalSurface` |
| Approval banner | `InterruptDeck` (`widgets/interrupts.py`) **outside** the 3-pane container | `background: $approval; color: $background` (inverted) |
| Action dock | `Horizontal` of `Button` + `Input` | `border-left: thick $approval; background: $approvalSurface` |
| Composer | `PromptComposer` (`widgets/composer.py` L242: `height: auto; min-height: 3; max-height: 8`) | `border: solid $borderStrong` → `heavy $focusRing` on focus; `height: auto 3..8` |
| Meta line | `Static` | `border-top: solid $border` |
| Footer | `Footer` | all 12 bindings fit at 120 cols in `kbd` chips |
| Mission Control ^T | `ModalScreen` (`overlays/missions.py`) | reuses the `DataTable` shell + a concurrency ticker |
| Log pager ^O | `TranscriptOverlay` (`overlays/transcript.py`) | same column widths as the log grid |

---

## Feature coverage (all 57 inventoried features × all three redesigns)

Legend: **✓** = present and restyled in place · **↑** = promoted (more visible than today) ·
**→** = moved to a different container · **⊕** = merged with another block · **↓** = collapsed/hidden
until invoked (nothing deleted). Every row has an entry in every column — nothing is dropped.

| # | Feature (from the verified inventory) | R1 ATELIER | R2 MERIDIAN | R3 FOUNDRY |
|---|---|---|---|---|
| 1 | Header: brand + version | ✓ masthead, letterspaced `S K A I L  0.1.0` | ✓ `✻ SKAIL 0.1.0` wordmark | ✓ title bar `✻ SKAIL 0.1.0` |
| 2 | Header: clock | ✓ dateline right `FRI 18 SEP · 14:32:07` | ✓ command bar right | ✓ title bar right |
| 3 | Optional provider badge | ✓ chip `ANTHROPIC` in masthead | ✓ first pill in command bar | ✓ `PROVIDER anthropic` in title bar |
| 4 | Status: `Model: <m>` | ✓ dateline `MODEL auto` | ✓ pill `MODEL auto` (hot) | ✓ ticker `MODEL auto` |
| 5 | Status: `Mode: <routing>` | ✓ dateline `MODE quality` in `$modeQuality` | ✓ pill, `$modeQuality` border | ✓ ticker, `$modeQuality` value |
| 6 | Status: `Cost: $X / $Y` | ✓ dateline `SPEND $0.0142 / $5.00` | ✓ pill `$0.0142/5.00` | ✓ ticker `SPEND $0.0142/$5.00` |
| 7 | Status: `Active Agents: N` | ✓ dateline `AGENTS ●1 running` | ✓ pill `●1 AGENT` | ✓ ticker `AG 1R 1W 1C 1F 1X` ↑ (per-state counts) |
| 8 | Status strip is 1 row | ✓ 1 row (2 in narrow) | ✓ 1 command bar | ✓ 1 ticker row (2 in narrow) |
| 9 | 60/40 left-right split | → 80/39 (67/33) — wider measure for prose | → 76/43 (64/36) | → 60/26/32 three panes |
| 10 | Sidebar tabs Agents/Plan/Route/Budget | ✓ underlined small-caps strip | ✓ inverted segment strip | ✓ inspector tab strip (AGENTS also permanent) ↑ |
| 11 | Transcript scrolling | ✓ `ChatTranscript` scroll | ✓ panel scroll | ✓ `DataTable` scroll |
| 12 | Collapsible rows `[▾]` | ✓ `+ / −` in a 2-cell fold gutter | ✓ `▾ / ▸` fold cell | ✓ `⏎` expand + `⇧⏎` collapse all |
| 13 | Role `YOU` | ✓ role cell, `$accent` | ✓ role cell, `$accent` | ✓ SOURCE cell, `$accent` |
| 14 | Role `LEAD` | ✓ role cell, `$text` | ✓ role cell, `$text` | ✓ SOURCE cell |
| 15 | Role `AGENT n` | ✓ `AGENT 1 ●` (9-cell field, slot-coloured) | ✓ `AGENT 1` + spine colour | ✓ `A1/A2/A3` (full word on expand) |
| 16 | Role `TASK` | ✓ | ✓ | ✓ |
| 17 | Role `TOOL ▸ <title>` | ✓ `TOOL ▸` in role cell + title in measure | ✓ `TOOL ▸` role cell | ✓ `▸ <title>` in SUMMARY, `A1` in SOURCE |
| 18 | Role `ERROR` | ✓ row on `$errorSurface` | ✓ row on `$errorSurface` + `✕` spine node | ✓ row on `$errorSurface` + `✕` in ST |
| 19 | Role `APPROVAL REQUIRED` | ✓ row on `$approvalSurface` | ✓ row + `▲` spine node | ✓ `APPR` row + `▲` in ST |
| 20 | Role `RECEIPT` | ✓ `RECEIPT ✓ plan@r3 · $0.0041` | ✓ `RECEIPT` + `◆` spine node | ✓ `RCP` row (full word on expand) |
| 21 | Streaming in-place append | ✓ shimmer row + `$accent` caret, no re-flow | ✓ same | ✓ same row `#23` mutates in place |
| 22 | Scroll-pin + docked hint `↓ N new events (End)` | ✓ centred hairline `↓ 4 new events · End to re-pin` | ✓ glowing rule `↓ 4 NEW EVENTS · END TO RE-PIN` | ✓ `↓ 4 NEW · END TO PIN` |
| 23 | Interrupt/approval container at bottom of left column | → full-bleed band below the split (spans both columns) | → full-width panel below the split | → full-width banner + dock below all three panes |
| 24 | Approval title `[command:<run_id>]` | ✓ `[command:run-1]` next to the small-caps title | ✓ same | ✓ same, in the inverted banner |
| 25 | Approval question text | ✓ `EnsureAllow: …` | ✓ | ✓ |
| 26 | Buttons Approve / Reject / Add instruction | ✓ underlined words + `kbd` glyphs | ✓ 3 chips, primary = Approve w/ focus halo | ✓ 3 buttons, primary = Approve |
| 27 | Approval input `Optional answer or comment…` | ✓ dashed-underline field | ✓ inset `Input` with `▸` | ✓ `ANSWER` kv `Input` |
| 28 | Approval key hint `[A] [R] [E]` | ✓ inline after each action | ✓ inside each chip | ✓ inside each button |
| 29 | `Esc keeps pending` | ✓ top-right of the band | ✓ top-right of the panel | ✓ right of the banner + overlay list |
| 30 | Agents tab row `> ● Agent 1 | task | status | cost` | ✓ margin ledger row (same 4 fields) | ✓ agent card (stripe + LED + task + cost) | ✓ permanent rail row |
| 31 | Statuses running/waiting/complete/failed/cancelled | ✓ `● ∙ ✓ ✕ ⊘` + words | ✓ same glyphs + words | ✓ same + ticker counts `1R 1W 1C 1F 1X` |
| 32 | `Enter` = agent detail | ✓ `⏎ detail` hint in margin | ✓ `[⏎] detail` | ✓ `[⏎] detail` + AGENTS tab detail table |
| 33 | `m` = Mission Control | ✓ hint + `^T` overlay frame | ✓ hint + `^T` | ✓ hint + full `^T` overlay frame |
| 34 | Plan tab: plan items | ✓ PLAN mini-panel (`✓ ✓ ▌ ⊘`) | ✓ PLAN segment mini-panel | ✓ live in the inspector |
| 35 | Plan tab: revisions | ✓ `r2 → r3 · item 4 deferred` | ✓ `REVISIONS` row | ✓ `REVISIONS` kv (2 revisions) |
| 36 | Plan tab: integrations | ✓ `pytest · rtk · apply_patch` | ✓ `INTEGRATE` row | ✓ `INTEGRATE` kv |
| 37 | Plan tab: receipts | ✓ `✓ plan@r3 · 2 changesets · $0.0041` | ✓ `RECEIPTS` row | ✓ `RECEIPTS` kv + `RCP` log rows |
| 38 | Plan accept/reject/change prompt | ✓ `A accept / R reject / C change` + note field | ✓ raised sub-panel with 3 buttons + input | ✓ left-barred prompt with 3 buttons + input |
| 39 | Route tab: routing info | ✓ ROUTE mini-panel (policy/eligible/floors/sticky/fallback) | ✓ ROUTE segment mini-panel | ✓ ROUTE tab mini-panel + ticker `ROUTE auto→lead` ↑ |
| 40 | Route tab: exclusion info | ✓ `EXCLUDED gpt-4o-mini · below floor` | ✓ `✕ gpt-4o-mini · floor` | ✓ `EXCLUDED` kv + ticker `EXCL 1` ↑ |
| 41 | Budget meter (fill) | ✓ LEDGER block + dateline meter | ✓ **vertical** column | ✓ ticker meter + BUDGET tab |
| 42 | Budget warning ≥ 0.75 | ✓ token-state strip `WARNING 78% ▲` | ✓ `90┈/75┈` ticks + state strip | ✓ BUDGET tab shown *at* 77.8% ▲ |
| 43 | Budget critical ≥ 0.90 | ✓ state strip `CRITICAL 94% ▲▲` | ✓ state strip + tick | ✓ state strip + `auto-degrade` note |
| 44 | Composer queue strip `QUEUED N ^ take back` | ✓ small-caps row above the input | ✓ amber `QUEUED 2` chip above the input | ✓ amber row above the input + meta echo |
| 45 | Composer card with round border | → bordered **band** (top/bottom heavy rules, no box) | ✓ rounded raised panel + focus halo | ✓ bordered band with focus inset |
| 46 | Composer 3–8 row multiline input | ✓ 3-row min measure, grows to 8 | ✓ 3-row min | ✓ `3 of 8 rows` shown in the meta line |
| 47 | Palette line `/ opens commands ? shortcuts <n> chars` | ✓ `44 chars · / commands · ? shortcuts` | ✓ 3 pills: `44 chars`, `/ commands`, `? shortcuts` | ✓ `44 chars │ / commands │ ? shortcuts │ 3 of 8 rows` |
| 48 | Mode badge `MODE QUALITY` | ✓ chip with `$modeQuality` border | ✓ hot pill | ✓ chip + composer side stack |
| 49 | Send button | ✓ `SEND ⏎` chip | ✓ glowing `SEND ⏎` | ✓ `SEND ⏎` + cost estimate beside it |
| 50 | Footer: all 12 keybindings | ✓ 1 row + `⋯`, **all 12 listed in the `?` overlay frame** | ✓ 1 row, all 12 as `kbd` chips | ✓ 1 row, all 12 as `kbd` chips |
| 51 | Narrow mode: width < 100 hides sidebar | ✓ 88-col frame: margin → drawer strip | ✓ 88-col frame: rail → drawer, segments → letters | ✓ 88-col frame: 3 panes → 1 + pane switcher |
| 52 | Overlay: transcript pager `^O` | ✓ same shell (documented) | ✓ same shell | ✓ reuses the log grid columns |
| 53 | Overlay: shortcuts `?` | ✓ **rendered frame** (all 12 + row/approval keys) | ✓ same shell | ✓ same shell |
| 54 | Overlay: theme switcher `⌥T` (live preview) | ✓ light token set + in-page toggle proves it | ✓ Meridian Day set + toggle | ✓ Foundry Day set + toggle |
| 55 | Overlay: model picker `⌥P` | ✓ same shell | ✓ **rendered frame** (eligible/excluded + floors) | ✓ same shell |
| 56 | Overlay: Mission Control `^T` | ✓ same shell | ✓ same shell | ✓ **rendered frame** (tree, concurrency 2/3, leases, guards) |
| 57 | Semantic tokens, dark **and** light | ✓ Ink & Bone / Newsprint (36 tokens) | ✓ Meridian / Meridian Day | ✓ Foundry / Foundry Day |

### Accessibility (all three)
| Requirement | ATELIER | MERIDIAN | FOUNDRY |
|---|---|---|---|
| Contrast (text on background) | 12.6:1 (`#EDE4D6` on `#14110E`) | 13.2:1 (`#DCE6F5` on `#07090E`) | 13.9:1 (`#E6E9EA` on `#0D0F10`) |
| `textFaint` usage | metadata only, never state/cost | same | same (stated in notes) |
| Focus ring | 2px inset `$focusRing` bar on the current row + `border` on chips | halo → `border: heavy $focusRing` | inset bar + `$selection` row fill |
| Status not colour-only | glyph **+** word (`● RUNNING`) everywhere; clock gutter keeps meaning when colour is stripped | same; spine is redundant with the role cell | same; ST column is a glyph *and* the SOURCE cell names the agent |
| Reduced motion | shimmer → static caret (row in each state strip) | same | same |
| Light theme | full 36-token set | full 36-token set | full 36-token set |

### Palettes (retuned hex per token)
| Token | ATELIER dark | ATELIER light | MERIDIAN dark | MERIDIAN light | FOUNDRY dark | FOUNDRY light |
|---|---|---|---|---|---|---|
| background | `#14110E` | `#F4F0E7` | `#07090E` | `#EEF2F7` | `#0D0F10` | `#F2F3F1` |
| surface | `#1B1714` | `#FBF8F1` | `#0C1017` | `#FFFFFF` | `#14171A` | `#FBFBFA` |
| surfaceRaised | `#221D19` | `#EDE7DA` | `#121826` | `#E3EAF3` | `#1C2124` | `#E8EAE6` |
| surfaceInset | `#100D0A` | `#E7E0D2` | `#05070B` | `#DCE4EE` | `#090B0C` | `#E2E5E0` |
| border | `#322A24` | `#D6CCBB` | `#1E2A3D` | `#C3CEDC` | `#262C30` | `#CFD3CD` |
| borderStrong | `#4F4238` | `#A99C87` | `#2E4260` | `#8FA0B5` | `#3C464C` | `#98A09A` |
| text | `#EDE4D6` | `#241E17` | `#DCE6F5` | `#0E1723` | `#E6E9EA` | `#161A17` |
| textMuted | `#9A8C7B` | `#6E6154` | `#7E92A9` | `#55677D` | `#8C979C` | `#5C6660` |
| textFaint | `#6E6154` | `#948878` | `#566579` | `#8296AE` | `#5E686D` | `#8A938D` |
| accent | `#D98E4A` | `#9E5518` | `#4FD1FF` | `#0077A8` | `#A8E05F` | `#4E7A16` |
| accentSoft | `#2E2318` | `#F0E0CB` | `#0F2A3A` | `#D6EEFA` | `#1E2A14` | `#E4F0D2` |
| focusRing | `#E8B978` | `#7A3F0E` | `#8CE6FF` | `#005A80` | `#C7F464` | `#3B5E0E` |
| modeQuality | `#B39DDB` | `#5E46A0` | `#A78BFA` | `#6545B8` | `#B79CFF` | `#6545B8` |
| modeEconomy | `#82C9A5` | `#2C7355` | `#58D6A7` | `#087A55` | `#7FD6A8` | `#0B6B4A` |
| modeManual | `#D9A441` | `#8A6200` | `#FFC857` | `#98600B` | `#F2C14E` | `#8A6200` |
| delegation | `#B39DDB` | `#5E46A0` | `#A78BFA` | `#6741C7` | `#B79CFF` | `#6741C7` |
| budgetFill | `#C9A227` | `#8A6A0C` | `#4FD1FF` | `#0077A8` | `#A8E05F` | `#4E7A16` |
| budgetWarning | `#D98E4A` | `#9E5518` | `#FFC857` | `#98600B` | `#F2C14E` | `#8A6200` |
| budgetCritical | `#E0645A` | `#AE3227` | `#FF6B7A` | `#B42335` | `#FF6B6B` | `#B42335` |
| budgetEmpty | `#2C2620` | `#DCD4C5` | `#1A2432` | `#D3DCE7` | `#232A2E` | `#D6DAD4` |
| error | `#E0645A` | `#AE3227` | `#FF6B7A` | `#B42335` | `#FF6B6B` | `#B42335` |
| errorSurface | `#2A1614` | `#F6E2DE` | `#22121A` | `#FBE3E6` | `#241416` | `#FBE3E5` |
| approval | `#D9A441` | `#8A6200` | `#FFC857` | `#8A6200` | `#F2C14E` | `#8A6200` |
| approvalSurface | `#241E14` | `#FAEEC9` | `#1A1608` | `#FFF3D2` | `#241F10` | `#FBF0CE` |
| agentOne | `#7FB3D5` | `#2F6E92` | `#5CC8FF` | `#0077A8` | `#6FC7E8` | `#1E6E8C` |
| agentTwo | `#B39DDB` | `#5E46A0` | `#B69CFF` | `#6545B8` | `#B79CFF` | `#5E46A0` |
| agentThree | `#82C9A5` | `#2C7355` | `#58D6A7` | `#087A55` | `#7FD6A8` | `#0B6B4A` |
| diffAdded / Surface | `#8FBF7A` / `#182114` | `#2C7355` / `#DDF3E6` | `#58D6A7` / `#0C211B` | `#087A49` / `#DDF6E9` | `#7FD6A8` / `#12211A` | `#087A49` / `#DDF6E9` |
| diffRemoved / Surface | `#E0645A` / `#2A1614` | `#AE3227` / `#F6E2DE` | `#FF7D88` / `#251116` | `#B42335` / `#FCE2E5` | `#FF8080` / `#241416` | `#B42335` / `#FBE3E5` |
| dimmed | `#6E6154` | `#948878` | `#4B5A6D` | `#8296AE` | `#4C555A` | `#8A938D` |
| shimmerBase / Peak | `#6E6154` / `#F6E7D0` | `#A99C87` / `#241E17` | `#4B5A6D` / `#D5F3FF` | `#8FA0B5` / `#0E1723` | `#5E686D` / `#EAF7D2` | `#98A09A` / `#161A17` |
| selection | `#3A2F22` | `#E3D3BC` | `#173748` | `#CBEAF8` | `#23301A` | `#DCEBC6` |
| link | `#8FC7E8` | `#2F6E92` | `#79D1FF` | `#0077A8` | `#8FD0E8` | `#1E6E8C` |

The current `DARK_THEME` / `LIGHT_THEME` values remain valid for all three — these are *retunes*, and
each is a drop-in `ThemeTokens(...)` construction. The `agentOne/Two/Three` values are deliberately
kept close to the shipped `#5CC8FF / #B69CFF / #58D6A7` so per-slot identity stays stable across themes.

---

## Cross-design comparison

| Axis | ATELIER | MERIDIAN | FOUNDRY |
|---|---|---|---|
| Metaphor | printed page / typescript | cockpit HUD | trading terminal |
| Hierarchy device | rules, indentation, letterspaced small caps | 3 surface depths + pills | grid columns + ticker fields |
| Boxes on screen | 1 (composer band) | 4 (2 panels, approval, composer) | 3 panes + banner + composer |
| Columns spent on chrome | ~4 | ~10 (panel borders/padding) | ~5 (2 dividers + padding) |
| Transcript width at 120 | 78 | 69 | 58 (but 2 extra data columns) |
| Agent visibility | tab + margin ledger | tab + spine colour | **permanent pane** + tab |
| Budget visibility | dateline + LEDGER block | command pill + **vertical column** | ticker + inspector kv |
| Density | low–medium (airy) | medium | high |
| Best for | long prose answers, calm sessions | parallel children, situational awareness | cost/latency operators, auditing |
| Riskiest bet | users may miss panel boundaries | spine eats 3 columns | 34-char SUMMARY forces truncation |
| Cheapest to ship | ★★★ (mostly TCSS) | ★★ (spine + vertical meter are new widgets) | ★ (DataTable migration of the transcript) |

---

## Features that were hard to represent (honest list)

1. **Streaming shimmer.** `shimmerBase → shimmerPeak` is an animated Rich effect. HTML needs
   `background-clip: text` + a gradient, which has **no TCSS equivalent**. In Textual this must be a
   two-colour toggle driven by a timer (or a static `$textFaint` body with an `$accent` caret under
   `SKAIL_REDUCED_MOTION`). All three mockups show the *end state*, not the animation; treat the gradient
   as illustrative only.
2. **Glow (MERIDIAN only).** `box-shadow` halos are impossible in a terminal. Nothing informational is
   carried by them — focus is also encoded as `border: heavy $focusRing` + `$accentSoft` fill. Flagged in
   the file's implementation notes so nobody tries to ship the glow.
3. **Letterspaced small caps (ATELIER).** TCSS has no `letter-spacing`. Real implementation means baking
   spaces into the string (`A G E N T S`), which changes the character budget and can push a label past
   its `width`. The mockup uses CSS letter-spacing on short labels only; in code, prefer
   `text-style: bold` + `$textMuted` and reserve baked spacing for the 4 tab labels and section headers.
4. **Vertical budget column with exact threshold ticks (MERIDIAN).** 75% and 90% only land on cell
   boundaries for specific cell counts (12 cells → 75% at cell 9, 90% at 10.8). Either fix the meter to
   20 cells (75 → 15, 90 → 18) or accept ±1 cell and label the ticks `75┈ / 90┈` rather than drawing them
   at a computed offset. The mockup uses 12 cells and hand-places the ticks — that is the one place where
   the picture is *not* literally implementable.
5. **Approval container relocation.** The spec puts the interrupt container at the bottom of the **left
   column**. All three designs move it to a **full-width band below the split** (ATELIER/MERIDIAN) or a
   **full-bleed banner spanning all panes** (FOUNDRY). Rationale: an approval gates the whole run, and at
   60% width the command line being approved truncates. This is a deliberate `→` move, not a drop — but it
   changes `app.py`'s layout composition, not just TCSS, so it is the most expensive of the three
   "restyles" to land.
6. **`⌥` / Alt key rendering.** `⌥T` and `⌥P` are macOS-flavoured glyphs; Textual's `Footer` will render
   `alt+t`. The mockups use `⌥` for compactness. Ship `alt+T` (or make the glyph set part of the theme).
7. **12 footer bindings at 120 columns.** They do not fit on one row in any design. ATELIER shows 8 + `⋯`
   and puts all 12 in the `?` overlay (rendered); MERIDIAN and FOUNDRY fit all 12 by shortening labels
   (`transcript` → `log`, `shortcuts` → `keys`). If the owner wants every label verbatim, the footer must
   become 2 rows — that costs one transcript row and I would not recommend it.
8. **FOUNDRY's SUMMARY column is only ~34 characters.** Dense grids trade prose for scannability; long
   assistant messages wrap to 3+ rows and erode the density benefit. Mitigation is truncation with `⏎`
   expand plus the `^O` pager at full width. If the owner's dominant workload is long prose answers,
   FOUNDRY is the wrong pick and ATELIER is the right one.
9. **Zebra striping vs. hairlines.** FOUNDRY uses alternating `$surface` rows. In a 256-colour terminal
   the step between `#0D0F10` and `#14171A` is visible; on an 8-colour fallback it is not, so the grid
   must remain legible from the header + column alignment alone (it does — no information is striped).
10. **Live theme preview (`⌥T`).** The mockups prove the light sets are designed, but real live preview
    means regenerating the `--token` CSS block and re-mounting; `theme.py:to_textual_css()` already
    supports it. Nothing to design, just don't forget the preview must re-run `budget_token_for_ratio()`.

---

## Suggested next step

Pick one direction, then land it in three commits so each is independently revertible:
1. **Tokens** — add the chosen palette as a new `ThemeTokens` set in `theme.py` (no layout change).
2. **Chrome** — status strip → dateline/command bar/ticker, footer chips, composer band. Pure TCSS +
   one `Static` restructure.
3. **Transcript** — the row grid (ATELIER 4-cell rows / MERIDIAN spine cell / FOUNDRY `DataTable`),
   plus the approval relocation from step 5 above.

Do not start with the transcript: it is the only one of the three that touches
`widgets/chat.py` + `projection.py` rendering, and the first two commits already deliver most of the
visual change.
