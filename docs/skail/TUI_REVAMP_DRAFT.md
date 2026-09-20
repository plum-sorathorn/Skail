# Skail TUI Revamp Draft

## 0. Problem framing and architectural recommendation

The current TUI exposes the runtime effectively, but its first-run path, visual language, keyboard accessibility, and rendering strategy make it feel like a diagnostic shell rather than a polished multi-agent cockpit. The revamp should preserve the current event-sourced architecture and every CLI/headless capability while moving runtime construction behind the mounted TUI for interactive sessions, introducing semantic theming, incremental transcript rendering, and keyboard-complete workflows.

### Options considered

1. **Cosmetic-only restyle**
   - Lowest implementation risk.
   - Does not solve credential-gated boot, transcript flicker, single-line composition, or inaccessible controls.

2. **Replace the TUI architecture**
   - Could produce a cleaner implementation.
   - Unnecessarily threatens snapshot/event reconstruction, headless parity, session behavior, and the Textual-free projection invariant.

3. **Recommended: staged shell and widget revamp**
   - Retain `SkailApp`, projection semantics, runtime boundaries, and command behavior.
   - Split interactive boot from headless runtime construction.
   - Replace hardcoded styling with semantic tokens.
   - Incrementally update transcript widgets instead of rebuilding the DOM.
   - Add onboarding, overlays, richer composition, and complete keyboard navigation.

### Non-negotiable architecture boundaries

- The runtime must never import Textual.
- `projection.py` must remain importable and testable without Textual or Rich.
- UI state must remain reconstructible from a snapshot plus ordered events.
- Headless `-p`, `--jsonl`, `-c`, `-r`, and `--no-session` paths retain their current semantics.
- A run may launch at most two child attempts and never exceed three concurrent children.
- `/quit` must cancel an active worker, mark the session idle, and exit with code `0`.
- API keys must never be placed in projection state, snapshots, events, transcripts, logs, or session files.

---

# 1. Design vision and principles

Skail should feel like a compact mission-control instrument: calm at rest, explicit under load, and immediately understandable without reading documentation. The interface should use neutral surfaces, one primary sail-blue accent, and semantic color only where state needs to be distinguished.

## Principles

1. **State is never hidden**
   - Mode, model, budget, active children, queued prompts, pending approvals, and connection/loading state remain visible without opening a panel.

2. **Keyboard first, mouse complete**
   - Every clickable action has a documented key path.
   - Focus styling must be obvious.
   - Mouse interaction remains supported but is never required.

3. **Calm shell, vivid events**
   - The frame uses neutral grays and sail blue.
   - Role, approval, error, diff, and agent colors appear locally rather than tinting whole screens.

4. **Incremental, not theatrical**
   - Existing transcript nodes update in place.
   - Animation communicates active work but never delays interaction.
   - Reduced-motion mode removes shimmer and transitions without losing state.

5. **Receipts over ambiguity**
   - Forks, resumes, configuration changes, trust decisions, cancellations, and queued work produce concise, copyable confirmation lines.

---

# 2. Pixel-sail identity

## 2.1 Cell legend

All logo variants use a strict monospace cell grid.

- `■` — primary filled sail pixel
- `▪` — secondary/accent pixel
- `│` — mast
- `━` — hull or waterline
- space — empty cell

Do not substitute emoji, proportional symbols, or colored image assets. In color-capable output:

- `■` uses `accent`
- `▪` uses `delegation`
- `│` and `━` use `textMuted`

In monochrome output, all occupied cells use the terminal foreground.

## Variant A — “Windward,” 7 columns × 6 rows

```text
   ■
  ■■│
 ■■■│
■■■■│
  ▪ │
━━━━━━━
```

Cell-by-cell:

| Row | Cells 1–7 |
|---|---|
| 1 | ` ` ` ` ` ` `■` ` ` ` ` ` ` |
| 2 | ` ` ` ` `■` `■` `│` ` ` ` ` |
| 3 | ` ` `■` `■` `■` `│` ` ` ` ` |
| 4 | `■` `■` `■` `■` `│` ` ` ` ` |
| 5 | ` ` ` ` `▪` ` ` `│` ` ` ` ` |
| 6 | `━` `━` `━` `━` `━` `━` `━` |

Character positions are authoritative; the table describes the visual cells rather than requiring a separate graphics implementation.

**Character:** recognizable at small size, stable silhouette, reads clearly as a sail rather than a generic triangle.

## Variant B — “Twin Agent,” 9 columns × 7 rows

```text
    ■
   ■■│▪
  ■■■│▪▪
 ■■■■│▪▪▪
■■■■■│
   ━━━━━
  ━━━━━━━
```

Cell-by-cell visual structure:

- Rows 1–5 use column 6 as the mast.
- The primary sail grows left from one to five `■` cells.
- The secondary sail grows right from one to three `▪` cells on rows 2–4.
- Rows 6–7 form a two-step hull.

**Character:** communicates delegation and two cooperating agents, but is visually busier and less effective at header scale.

## Variant C — “Beacon Sail,” 7 columns × 7 rows

```text
   ▪
   ■
  ■■│
 ■■■│
■■■■│
  ━━━
 ━━━━━
```

Cell-by-cell visual structure:

- `▪` at row 1, column 4 is the beacon.
- Primary sail grows from one to four cells over rows 2–5.
- Mast remains at column 5 on rows 3–5.
- Hull uses centered widths of three and five cells.

**Character:** friendlier onboarding mark, but the top beacon can read as a star or notification.

## Selected mark: Design C, “Twin sail”

Reasons:

- Legible in one terminal color.
- Distinct at six rows and stable in monospace output.
- Twin sails express lead/child collaboration without animation.
- The full lockup is used in README, help, and onboarding; the compact `/\| S K A I L`
  form is used in the always-visible masthead.

## Placement rules

| Location | Rendering |
|---|---|
| Welcome cockpit | Full six-row logo, left-aligned, followed by `SKAIL` and the current version |
| Header | Compact text mark `/\| S K A I L` |
| `/help` | Full six-row monochrome mark above command groups |
| README | Full six-row logo in a fenced `text` block; optional SVG may reproduce the same exact grid |
| Errors/loading | Do not repeat the logo; errors should remain terse and functional |
| Narrow header | Keep the compact text mark only when status fields still fit |

Do not animate the logo. The spinner may shimmer; the identity mark must remain stable.

---

# 3. Brand and theme tokens

## 3.1 Color policy

The shell uses sail blue as its primary accent. Violet is reserved for delegation and tool activity. Green, amber, and red are semantic state colors, not decorative accents.

Every widget must consume semantic tokens. No raw hex value may appear in widget CSS, Rich markup, or rendering logic outside `theme.py` and the theme token definitions.

## 3.2 Required token table

| Token | Dark | Light | Usage |
|---|---:|---:|---|
| `background` | `#0B0D10` | `#F6F7F9` | App canvas |
| `surface` | `#11151A` | `#FFFFFF` | Composer, sidebar, cards |
| `surfaceRaised` | `#171C22` | `#EEF1F4` | Focused overlays, selected tabs |
| `surfaceInset` | `#0E1216` | `#E8ECF0` | Code blocks, queue rows, meters |
| `border` | `#2A313A` | `#CBD2DA` | Structural separators |
| `borderStrong` | `#3A4552` | `#98A3AF` | Focused interactive boundaries |
| `text` | `#E8EDF2` | `#18202A` | Primary text |
| `textMuted` | `#8E99A6` | `#66717D` | Metadata, inactive hints |
| `textFaint` | `#59636F` | `#9099A3` | Timestamps, disabled content |
| `accent` | `#5CC8FF` | `#006F9F` | Primary focus, selected control, lead identity |
| `accentSoft` | `#173748` | `#D9F1FC` | Selected backgrounds |
| `modeQuality` | `#B69CFF` | `#6545B8` | Quality mode indicator only |
| `modeEconomy` | `#58D6A7` | `#087A55` | Economy mode indicator only |
| `modeManual` | `#F2B866` | `#98600B` | Manual mode indicator only |
| `delegation` | `#A88BFA` | `#6741C7` | Delegation/tool activity |
| `budgetFill` | `#5CC8FF` | `#007AAE` | Used portion under warning threshold |
| `budgetWarning` | `#F2B866` | `#98600B` | Used portion at 75–89% |
| `budgetCritical` | `#FF6B7A` | `#B42335` | Used portion at 90%+ |
| `budgetEmpty` | `#303842` | `#D5DBE1` | Unused budget meter cells |
| `diffAdded` | `#4FCB8D` | `#087A49` | Added lines and accept action |
| `diffAddedSurface` | `#102A20` | `#DDF6E9` | Added-line background |
| `diffRemoved` | `#FF7D88` | `#B42335` | Removed lines and reject action |
| `diffRemovedSurface` | `#32171C` | `#FCE2E5` | Removed-line background |
| `dimmed` | `#66717D` | `#89929C` | Rejected/completed secondary content |
| `error` | `#FF6B7A` | `#B42335` | Errors and failed state |
| `errorSurface` | `#34171D` | `#FCE4E7` | Error card background |
| `approval` | `#F5C451` | `#8A6200` | Pending approval |
| `approvalSurface` | `#302711` | `#FFF2C4` | Approval card background |
| `agentOne` | `#5CC8FF` | `#006F9F` | First child, stable by slot |
| `agentTwo` | `#B69CFF` | `#6545B8` | Second child, stable by slot |
| `agentThree` | `#58D6A7` | `#087A55` | Third child, stable by slot |
| `shimmerBase` | `#56616D` | `#98A3AF` | Spinner inactive cells |
| `shimmerPeak` | `#D5F3FF` | `#006F9F` | Spinner moving highlight |
| `focusRing` | `#86D8FF` | `#005D86` | Keyboard focus boundary |
| `selection` | `#24495D` | `#CBEAF8` | Text/list selection |
| `link` | `#79D1FF` | `#006F9F` | Copyable paths and commands |

### Agent color assignment

Colors are assigned by child slot, not by current list position or route status:

- Child slot 1 → `agentOne`
- Child slot 2 → `agentTwo`
- Child slot 3 → `agentThree`

A child keeps its color for the lifetime of the session. Finishing or failing does not cause remaining children to change colors.

---

# 4. Full visual specification

## 4.1 Wide layout, terminal width ≥100 columns

Target proportions:

- Main transcript: flexible, minimum 60 columns.
- Sidebar: 38 columns preferred, 34 minimum.
- One-column structural gap or border between transcript and sidebar.
- Composer occupies full width.
- Queue sits directly above the composer and below the content area.

```text
┌ S│ SKAIL ─ workspace: skail ─ session: 01J... ─ connected ────────────────┐
│ MODEL sonnet-4  MODE [QUALITY]  COST $1.42/$8  ■■■·····  AGENTS 2/3  ● RUN │
├───────────────────────────────────────────────────────┬────────────────────┤
│ LEAD · 10:42:18                                       │ AGENTS PLAN ROUTE  │
│ │ I’ll inspect the routing policy and delegate its    │ BUDGET             │
│ │ tests separately.                                   ├────────────────────┤
│                                                       │ ● Lead       active│
│ AGENT 1 · ROUTING · 10:42:21                      ▶   │ ● Agent 1    active│
│ ┃ Working in tests/unit/test_routing.py                │ ● Agent 2   waiting│
│                                                       │                    │
│ TOOL · pytest                                      ▼  │ Selected: Agent 1  │
│ ┊ 14 passed in 0.82s                                  │ task: routing tests│
│                                                       │ status: active     │
│ APPROVAL REQUIRED                                     │ tokens: 3.1k       │
│ ╭───────────────────────────────────────────────────╮ │ cost: $0.18        │
│ │ Shell wants to run: git status                    │ │                    │
│ │ [A] Approve   [R] Reject   [E] Add instruction    │ │ Enter: details     │
│ ╰───────────────────────────────────────────────────╯ │                    │
├───────────────────────────────────────────────────────┴────────────────────┤
│ QUEUED 2                                          ↑ take back   Ctrl+S stash│
│ 1  “Then compare the provider adapters.”                                  │
│ 2  “Summarize any security boundary changes.”                             │
├────────────────────────────────────────────────────────────────────────────┤
│ ╭ Message Skail…                                              MODE QUALITY ╮│
│ │ Draft supports multiple lines. Shift+Enter inserts a line.               ││
│ │ / opens commands · ? shortcuts                          127 chars  [Send] ││
│ ╰──────────────────────────────────────────────────────────────────────────╯│
├────────────────────────────────────────────────────────────────────────────┤
│ Esc interrupt · Shift+Tab panels · Alt+P model · Ctrl+O transcript · F1 help │
└────────────────────────────────────────────────────────────────────────────┘
```

The queue block is absent when empty. Its disappearance returns height to the transcript.

## 4.2 Narrow layout, terminal width <100 columns

The sidebar is not merely hidden with inaccessible content. Its tabs become overlays reachable through their existing bindings.

```text
┌ S│ SKAIL ─ sonnet-4 ─ [QUALITY] ─ ● RUN ┐
│ $1.42/$8  ■■■·····   AGENTS 2/3         │
├──────────────────────────────────────────┤
│ LEAD · 10:42                             │
│ │ I’ll inspect the routing policy and    │
│ │ delegate its tests separately.         │
│                                          │
│ AGENT 1 · ROUTING                    ▶   │
│ ┃ Working in test_routing.py             │
│                                          │
│ APPROVAL REQUIRED                        │
│ ╭──────────────────────────────────────╮ │
│ │ Run: git status                      │ │
│ │ A approve · R reject · E instruct    │ │
│ ╰──────────────────────────────────────╯ │
├──────────────────────────────────────────┤
│ QUEUED 2                      ↑ take back│
│ 1  Then compare provider adapters…       │
├──────────────────────────────────────────┤
│ ╭ Message Skail…              [QUALITY] ╮│
│ │ /help                                  ││
│ │                              5  [Send] ││
│ ╰────────────────────────────────────────╯│
├──────────────────────────────────────────┤
│ ^B budget  ^A agents  ^P plan  ^R route  │
└──────────────────────────────────────────┘
```

Narrow behavior:

- `Shift+Tab` cycles Agents → Plan → Route → Budget while the composer retains focus.
- Mouse clicks and keyboard focus cannot activate the passive transcript or side panels.
- Header session/workspace text is removed before model, mode, run state, budget, or agent count.
- At extremely narrow widths, use abbreviated labels but preserve values:
  - `M sonnet-4`
  - `Q` / `E` / `M` for mode
  - `$1.4/8`
  - `A2/3`

## 4.3 Typography and glyph rules

- Use terminal monospace only. Do not request or assume Nerd Fonts.
- Section labels: uppercase, bold, one line.
- Body copy: normal weight.
- Metadata: `textMuted`, never italic as the only distinction.
- Commands, paths, model names, and session IDs: `text` or `link`; copyable as plain text.
- Do not use emoji.
- Allowed primary glyphs:
  - `✻` active work/spinner
  - `●` live or selected
  - `∙` idle/subordinate
  - `▶` collapsed
  - `▼` expanded
  - `│` role edge
  - `┃` child-agent edge
  - `┊` tool edge
  - `■` filled meter
  - `·` empty meter
  - `+`/`-` diff lines when color is unavailable
- Color may never be the only state cue. Pair it with a label, glyph, or border pattern.
- Rounded borders are reserved for interactive cards: composer, approval, picker, dialog, actionable diff/plan cards.
- Transcript entries and passive status areas use left edges or straight separators, not rounded boxes.

---

# 5. Per-component specification

## 5.1 Header and statusline

Use two rows when width permits.

### Header row

```text
S│ SKAIL  workspace: skail  session: 01JABC…  connected
```

States:

- `connected`
- `connecting`
- `offline`
- `fake provider`
- `onboarding`
- `resumed`

The session ID is copyable. The full ID appears in a tooltip or focus detail if truncated.

### Status row

```text
MODEL sonnet-4  MODE [QUALITY]  COST $1.42/$8  ■■■·····  AGENTS 2/3  ● RUNNING
```

Required order:

1. Model
2. Mode
3. Cost and ambient budget bar
4. Active agent count
5. Run state

Run states:

- `∙ IDLE`
- `✻ STARTING`
- `● RUNNING`
- `! APPROVAL`
- `∙ QUEUED 2`
- `× FAILED`
- `✓ COMPLETE`

`✓` and `×` may be used as text symbols but not emoji-styled variants.

Budget meter:

- Eight cells.
- Used ratio is rounded up to the next cell.
- `<75%`: `budgetFill`
- `75–89%`: `budgetWarning`
- `≥90%`: `budgetCritical`
- Unlimited or unavailable budget: `COST $1.42/—  ········`
- Never animate the budget bar.

Mode control:

- `/mode <auto|economy|quality|manual>` changes routing mode for future assignments.
- Mode color applies only to the bracketed mode value.
- The composer repeats the active mode in its top-right corner.

Model control:

- `Alt+P` opens the model picker.
- Picker includes configured models only.
- Current model marked with `●`.
- Model changes affect future attempts only; they must not mutate immutable per-attempt assignments.

## 5.2 Transcript items

### Shared anatomy

```text
ROLE [optional child/task] · timestamp · state                      ▶/▼
edge  content
edge  content
```

- Header is focusable.
- `Enter` or `Space` toggles collapse.
- Left/right arrow:
  - `Left` collapses.
  - `Right` expands.
- Mouse click on the header continues to toggle.
- A collapsed item displays the first non-empty line, truncated to one row, plus a count such as `12 lines`.
- Focus does not automatically switch tabs or route context.

### Role styling

| Role | Label | Edge | Color |
|---|---|---|---|
| User | `YOU` | `│` | `accent` |
| Lead | `LEAD` | `│` | `accent` |
| Child | `AGENT 1`, etc. | `┃` | Stable agent slot token |
| Task/system | `TASK` | `│` | `modeManual` |
| Tool | `TOOL · <name>` | `┊` | `delegation` |
| Error | `ERROR` | `!` | `error` |
| Approval | `APPROVAL REQUIRED` | actionable rounded card | `approval` |
| Receipt | `RECEIPT` | `│` | `textMuted`, command in `link` |

### Incremental rendering contract

`ChatTranscript` must maintain:

```python
event_or_item_id -> TranscriptItemWidget
```

On projection update:

1. Compare ordered item IDs.
2. Mount only new IDs.
3. Update changed widgets in place.
4. Remove only IDs absent from the new projection.
5. Reorder only if event ordering actually changed.
6. Preserve:
   - scroll position,
   - focused item,
   - collapse state,
   - text selection where Textual permits,
   - pinned-to-bottom state.

Autoscroll:

- If the user is within two lines of the bottom, new content keeps the view pinned.
- If the user has scrolled upward, do not jump.
- Show `↓ 4 new events` as a focusable bottom affordance.
- `End` returns to live output.
- Streaming text updates only the relevant body widget; it must not remount the item.

## 5.3 Composer card

Replace the single-line `Input` with a multiline text area inside one rounded interactive card.

### Composer anatomy

```text
╭ Message Skail…                                      MODE QUALITY ╮
│ Draft text                                                        │
│                                                                   │
│ / opens commands · ? shortcuts                  127 chars  [Send] │
╰───────────────────────────────────────────────────────────────────╯
```

Behavior:

- `Enter`: send when slash palette is closed and no completion is selected.
- `Shift+Enter`: newline.
- `Ctrl+Enter`: always send.
- `Tab`: accept visible ghost completion.
- `Esc`: close completion first; otherwise invoke state-dependent escape behavior.
- Composer grows from 3 to 8 content rows, then scrolls internally.
- Empty placeholder: exact text `Message Skail…`
- Disabled while onboarding validation is active: `Validating provider…`
- Send button remains mouse-accessible and focusable.

### Ghost-text slash completion

Typing `/` at the beginning of the draft opens a fuzzy palette. The matching suffix appears as ghost text in `textFaint`.

Example:

```text
/them e
```

Rendered conceptually as:

- typed: `/th`
- ghost completion: `eme`
- detail: `Switch or preview the active theme`

Filtering considers:

- command name,
- aliases,
- description,
- relevant keywords.

Palette:

```text
╭ Commands ───────────────────────────────────────────╮
│ ● /theme      Preview or change the active theme   │
│   /trust      Review workspace trust               │
│   /missions   Open child mission control           │
│                                      +9 more        │
╰─────────────────────────────────────────────────────╯
```

Rules:

- Show at most six rows.
- Footer displays `+N more` when matches overflow.
- `Up`/`Down` moves selection.
- `Tab` completes without submitting.
- `Enter` completes a command that still needs arguments; it dispatches only a complete no-argument command.
- `Esc` closes the palette without changing the draft.
- Fuzzy matching must be deterministic and independently unit-testable.

### Queue above input

When a run is active, normal messages use existing follow-up queueing semantics.

Queue row:

```text
QUEUED 2                                      ↑ take back
1  “Then compare provider adapters.”
2  “Summarize the boundary changes.”
```

- `Up` on an empty composer removes the most recently queued prompt and restores it to the composer.
- The restored item is not lost if edited.
- `Ctrl+Enter` while active still queues; it does not bypass the queue.
- Queue order remains FIFO.
- Clicking a queue row focuses it; `Enter` takes that specific row back only if queue semantics safely support removal. Otherwise only last-item take-back is offered.
- Queue must be projection-derived rather than widget-local.

### History and drafts

When no run queue take-back applies:

- `Up` on an empty composer recalls previous submitted prompts newest-first.
- `Down` moves toward newer history and eventually restores the in-progress draft.
- Editing a recalled entry creates a new draft; it never mutates history.
- `Ctrl+S` stashes the current draft.
- Exact receipt: `Draft stashed. Press Up on an empty composer to restore it.`
- Stashes may remain app/session UI state but must not be represented as runtime events unless session restoration requires it.

## 5.4 Interrupt and approval cards

Example:

```text
APPROVAL REQUIRED · SHELL
╭──────────────────────────────────────────────────────╮
│ Command                                              │
│ git status                                           │
│                                                     │
│ Reason: Inspect workspace state                      │
│ Scope: C:\Users\plum\Documents\Works\Skail           │
│                                                     │
│ [A] Approve   [R] Reject   [E] Add instruction       │
╰──────────────────────────────────────────────────────╯
```

Keyboard behavior when an approval is pending:

- `A`: approve.
- `R`: reject.
- `E`: focus optional instruction field.
- `Tab`/`Shift+Tab`: move among controls.
- `Enter`: activate focused control.
- `Esc`: leave the approval pending and return focus to transcript/composer; it must not approve or reject.
- Approval shortcuts apply only when focus is not in free-text editing, unless the card itself has focus.
- Buttons remain available to mouse users.

After decision:

- Accepted card label: `APPROVED`
- Rejected card label: `REJECTED`
- Rejected content becomes `dimmed`; the decision and reason remain readable.
- Buttons disappear after a terminal decision.
- Duplicate submissions must be disabled immediately after activation.

## 5.5 Agents tab

Rows:

```text
● Lead       running       $1.10
● Agent 1    routing       $0.18
∙ Agent 2    waiting       $0.14
```

- Stable agent color appears in the glyph, left edge, and detail heading only.
- Selecting an agent updates the detail region within Agents.
- Selecting or clicking an agent must **not** force-switch to Route.
- `Enter` opens agent detail.
- `M` opens Mission Control focused on that child.
- Completed and failed agents remain visible until session replacement.
- Explicit labels: `running`, `waiting`, `complete`, `failed`, `cancelled`.

## 5.6 Plan tab

Plan steps use straight structural rows unless actionable.

```text
PLAN · 3/5
✓ 1  Locate routing policy
✓ 2  Add regression coverage
● 3  Update route selection
∙ 4  Run affected tests
∙ 5  Summarize changes
```

Actionable proposed plan:

```text
╭ PROPOSED PLAN ───────────────────────────────────────╮
│ 1. Update routing policy                            │
│ 2. Add deterministic tests                          │
│                                                     │
│ [A] Accept   [R] Reject   [E] Request changes        │
╰─────────────────────────────────────────────────────╯
```

Rejected plans remain visible but dimmed, labeled `REJECTED`, and collapsed by default.

## 5.7 Route tab

Route detail must emphasize why a route was selected:

```text
ROUTE
Selected      Agent 1 → quality
Reason        cross-module change
Model         sonnet-4
Assignment    immutable for attempt 2
Fallback      economy
```

- Route changes apply only through existing runtime/command semantics.
- Current immutable assignment is labeled explicitly.
- Keyboard selection must not silently mutate routing.
- Any mutation requires an action and receipt.

## 5.8 Budget tab

```text
BUDGET
Session     $1.42 / $8.00
Used        ■■■·····  18%
Lead        $1.10
Agent 1     $0.18
Agent 2     $0.14
Remaining   $6.58
```

States:

- `<75%`: normal
- `75–89%`: `NEAR LIMIT`
- `≥90%`: `CRITICAL`
- Exceeded: `LIMIT REACHED`

Do not render an ornamental chart when values are unavailable. Use exact text:

`Budget details are unavailable for this provider.`

## 5.9 Full-screen transcript overlay — `Ctrl+O`

The overlay:

- Occupies the full app content area.
- Hides sidebar and composer but leaves a one-line overlay command bar.
- Preserves role colors, collapsed state, and selection.
- Starts at the same scroll position as the embedded transcript.
- `/` searches transcript text.
- `N`/`Shift+N` moves between search matches.
- `Home`/`End`, `PageUp`/`PageDown` scroll normally.
- `Ctrl+O` or `Esc` closes the overlay.
- Closing returns focus and scroll position to the originating transcript.

Command bar:

```text
TRANSCRIPT  / search  N next  Ctrl+Shift+O native scrollback  Ctrl+O close
```

### Native scrollback escape

`Ctrl+Shift+O` should temporarily leave the alternate screen and render a plain-text transcript through Rich without ANSI interaction controls.

Required behavior:

1. Snapshot the current projected transcript.
2. Suspend the Textual alternate-screen presentation using the supported driver/app mechanism.
3. Print a plain transcript suitable for terminal-native selection and scrollback.
4. Print:
   `Press Enter to return to Skail.`
5. Restore the app and prior focus after Enter.

If the active terminal/driver cannot safely suspend:

- Open the platform pager with the plain transcript.
- Display:
  `Native scrollback is unavailable in this terminal; opened the system pager instead.`

Do not implement this with direct private driver manipulation. If the installed Textual version lacks a supported suspension API, isolate the fallback behind one small adapter.

## 5.10 Shortcut pane — `?`

`?` opens a searchable overlay when the composer is empty and no text control is consuming the key.

Groups:

- Run
- Composer
- Navigation
- Agents
- Approvals
- Session
- Display

Example:

```text
╭ SHORTCUTS ─────────────────────────────────────────────────────╮
│ Run                                                           │
│ Esc                 Interrupt active run                      │
│ Shift+Tab           Cycle Agents/Plan/Route/Budget            │
│ Alt+P               Choose model                              │
│                                                               │
│ Display                                                       │
│ Ctrl+O              Full transcript                           │
│ Ctrl+T              Mission Control                           │
│ /mode               Change routing mode                       │
│                                                               │
│ Type to filter                                      Esc close │
╰────────────────────────────────────────────────────────────────╯
```

`F1` retains its existing behavior of injecting help into the transcript. `?` is an overlay and does not add a transcript event.

## 5.11 Theme picker — `/theme`

```text
╭ THEME ──────────────────────────────────────────────╮
│ ● Dark                                             │
│   Light                                            │
│   System                                           │
│                                                    │
│ Preview                                            │
│ surface  text  accent  approval  error  agents     │
│                                                    │
│ Enter apply   Esc restore previous                 │
╰────────────────────────────────────────────────────╯
```

Requirements:

- Moving selection applies a live preview.
- `Enter` commits.
- `Esc` restores the previously committed theme.
- `System` follows detectable terminal/OS preference when available; otherwise resolves to Dark and says so in detail text.
- Theme selection must not affect runtime state.
- Persist through the existing application configuration mechanism if one exists; otherwise add a small TUI preference file that contains only non-secret UI settings.
- Do not store theme preference in session event history.

## 5.12 Mission Control — `Ctrl+T` and `/missions`

```text
╭ MISSION CONTROL ─ children 2/3 ───────────────────────────────╮
│ ● Agent 1  routing tests       RUNNING   $0.18   00:21       │
│ ● Agent 2  provider review     WAITING   $0.14   00:09       │
│                                                              │
│ Agent 1                                                      │
│ Assignment   Add deterministic routing tests                 │
│ Model        sonnet-4 · immutable for this attempt           │
│ Workspace    shared writer lock held                         │
│ Last event   pytest started                                  │
│                                                              │
│ Enter details   C cancel child   Esc close                    │
╰──────────────────────────────────────────────────────────────╯
```

- This view is observational by default.
- A cancel action requires confirmation.
- It must not expose any path to exceed three concurrent children.
- It must not permit overlapping shared-workspace writers.
- Agent selection retains stable colors.
- `Ctrl+T` toggles the overlay.
- `/missions` opens the same overlay.
- Existing `Ctrl+T` behavior must be reconciled if currently occupied; the context lists `ctrl+t` without a named panel, so retain any existing target through an alternate documented command if required by the actual binding map.

---

# 6. Spinner, shimmer, and motion

## 6.1 Spinner

Use a five-cell shimmer rather than a rotating emoji:

```text
✻ ∙ ∙ ∙ ∙
∙ ✻ ∙ ∙ ∙
∙ ∙ ✻ ∙ ∙
∙ ∙ ∙ ✻ ∙
∙ ∙ ∙ ∙ ✻
∙ ∙ ∙ ✻ ∙
∙ ∙ ✻ ∙ ∙
∙ ✻ ∙ ∙ ∙
```

- Active `✻`: `shimmerPeak`
- Inactive `∙`: `shimmerBase`
- Frame interval: 90 ms.
- The status label remains explicit:
  - `✻ CONNECTING`
  - `✻ THINKING`
  - `✻ DELEGATING`
  - `✻ COMPACTING`
- Never animate more than:
  - one global status spinner, and
  - one selected active child detail.
- Off-screen transcript items do not animate.

## 6.2 Reduced motion

Support an app preference and respect terminal/environment capability where detectable.

Reduced-motion behavior:

- Replace moving shimmer with steady `✻`.
- Disable background fades and selection transitions.
- Keep streaming text updates.
- Keep focus-ring changes immediate.
- Do not blink any status.
- State labels and colors remain unchanged.

No animation may exceed 150 ms except the continuous active-work shimmer.

---

# 7. Empty, loading, and error states

## 7.1 Ready/empty transcript

Exact copy:

```text
Ready.

Describe the outcome you want, paste an error, or type /help.
Shift+Tab cycles panels while the composer stays focused. /mode changes routing mode. ? shows shortcuts.
```

## 7.2 Runtime starting

```text
✻ Starting Skail runtime…
Loading configured providers and session state.
```

Avoid generic `Loading…`.

## 7.3 Session resume

```text
✻ Resuming session 01JABC…
Replaying snapshot and events.
```

Then receipt:

```text
Session resumed.
Resume later with:
skail -r 01JABC
```

## 7.4 Empty sidebar states

- Agents: `No child agents have been launched.`
- Plan: `No plan has been proposed.`
- Route: `No route decision is available yet.`
- Budget: `No usage has been reported yet.`

## 7.5 Provider error

Do not display raw `str(exc)` as the entire UI.

```text
PROVIDER SETUP FAILED

Skail could not connect to OpenAI.

Check the key, network access, and provider configuration.
Technical detail: authentication rejected

[R] Retry   [B] Back to provider setup   [C] Copy detail
```

Error mapping should provide:

- short title,
- user-actionable explanation,
- sanitized technical detail,
- retryability,
- optional documentation/config hint.

Never display credential contents or headers.

## 7.6 Runtime start failure

```text
RUNTIME COULD NOT START

Your session is safe. No agent run was started.
Review provider settings or retry initialization.

[R] Retry   [S] Setup   [Q] Quit
```

## 7.7 Interrupted run

```text
Run interrupted.
Queued follow-ups were preserved.
```

If no queue exists, omit the second sentence.

---

# 8. New interactive boot and onboarding cockpit

## 8.1 Boot decision

`main()` must classify invocation before building runtime models.

### Interactive TTY with no headless prompt/output mode

1. Parse arguments.
2. Resolve session and configuration metadata that do not require provider creation.
3. Mount `SkailApp` immediately.
4. App starts in one of:
   - ready,
   - initializing,
   - onboarding,
   - recoverable setup error.
5. Build runtime providers/models asynchronously only after the shell is visible.

### Headless invocation

For `-p`, `--jsonl`, or other explicitly non-interactive execution:

- Preserve current eager validation and exit semantics.
- Never launch Textual.
- Provider configuration failures remain stderr plus non-zero exit.
- `--fake-provider` remains supported.

This split fixes first-run TUI boot without weakening automation behavior.

## 8.2 Welcome-as-cockpit layout

This is the real app shell, not a temporary splash. Header, status, transcript area, and setup diagnostics are mounted from the beginning.

```text
┌ S│ SKAIL ─ setup ───────────────────────────────────────────────────────────┐
│ PROVIDER not configured   MODE [QUALITY]   COST —   AGENTS 0/3   ∙ ONBOARD │
├──────────────────────────────────────────────┬──────────────────────────────┤
│    ■                                         │ SETUP                        │
│   ■■│                                        │ ● 1 Welcome                  │
│  ■■■│                                        │ ∙ 2 Provider                 │
│ ■■■■│                                        │ ∙ 3 Trust                    │
│   ▪ │                                        │ ∙ 4 Theme                    │
│ ━━━━━━━                                      │ ∙ 5 Ready                    │
│                                              │                              │
│ SKAIL                                        │ Environment                  │
│ Budget-aware multi-agent coding harness.     │ folder  …\Works\Skail        │
│                                              │ keys    none detected        │
│ Set up this cockpit without leaving the TUI. │ session new                  │
│                                              │                              │
│                              [Enter] Continue│                              │
├──────────────────────────────────────────────┴──────────────────────────────┤
│ Enter continue · Esc back · Ctrl+C quit                                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 8.3 Step ladder

### Step 1 — Welcome

Exact copy:

```text
Welcome to Skail.

Skail coordinates a lead agent and up to three concurrent child agents while
keeping model assignments, workspace writes, approvals, and budget visible.

No provider key was found in the environment.
```

Actions:

- `Enter`: continue.
- `F`: choose fake provider.
- `Ctrl+C`: quit.
- If credentials already exist, onboarding may skip directly to asynchronous validation while still mounting the app first.

### Step 2 — Provider

```text
CHOOSE A PROVIDER

● LLM Gateway
  OpenAI
  Anthropic
  Fake provider

Use ↑/↓ to choose, then Enter.
For local evaluation without credentials, choose Fake provider
or restart with: skail --fake-provider
```

After selecting a live provider:

```text
LLM Gateway API key

╭ Key ───────────────────────────────────────────────────────╮
│ ••••••••••••••••••••••••••••••••••••••••••••••••••••• │
╰────────────────────────────────────────────────────────────╯

The key is held in memory for this process and is never written to the
session, transcript, event stream, or logs.

[V] Validate   [B] Back
```

Validation:

- Runs in a worker; UI remains responsive.
- Button changes to `Validating…`.
- Status shows `✻ CONNECTING`.
- Prevent duplicate validation requests.
- Sanitize all failures.
- Success copy:
  `Provider validated. LLM Gateway is ready.`
- Failure copy:
  `Validation failed. Check the key and network access, then retry.`

Credential precedence:

1. Explicit CLI/provider options, if already supported.
2. Environment variables.
3. In-memory onboarding entry.
4. Fake provider when explicitly selected.

Do not silently fall back from a failed live key to fake provider.

### Step 3 — Trust this folder

```text
TRUST THIS FOLDER?

C:\Users\plum\Documents\Works\Skail

Trusted folders may allow approved shell and filesystem operations within
the configured workspace boundary. Trust does not bypass tool approvals,
secret redaction, or workspace writer locks.

[T] Trust this folder
[R] Restricted mode
[B] Back
```

- Use existing trust semantics and storage.
- Never imply that trust removes approval boundaries.
- Show the resolved path before accepting.
- Receipt:
  - `Workspace trusted: C:\...\Skail`
  - or `Workspace opened in restricted mode.`

### Step 4 — Theme

Use the same live-preview picker as `/theme`.

Default:

- Resolve saved UI preference.
- Otherwise use `System`.
- If system preference cannot be detected, resolve to Dark.

### Step 5 — Ready receipt

```text
READY

Provider     LLM Gateway
Workspace    trusted
Theme        Dark
Mode         Quality
Session      01JABC

Resume this session later with:
skail -r 01JABC

[Enter] Open cockpit
```

The command must be plain selectable text and also emitted as a transcript receipt after entering the cockpit.

If fake provider was selected:

```text
Provider     Fake provider
```

No fake key should be invented or stored.

## 8.4 Cold-start behavior with existing credentials

Even Freestanding startup should mount before slow provider/model initialization:

```text
✻ Starting Skail runtime…
Loading LLM Gateway models.
```

On success, replace the loading state with the normal ready transcript. On recoverable failure, enter provider setup instead of terminating the app.

## 8.5 Non-TTY, no-argument behavior

The current `ready` output is misleading and must be removed.

When stdin or stdout is non-TTY and no explicit headless operation was requested:

- Do not attempt to mount Textual.
- Do not print `ready`.
- Print to stderr:

```text
skail: interactive mode requires a TTY.
Use `skail -p "<prompt>"` for headless execution, `skail --jsonl` for
machine-readable output, or run `skail` in an interactive terminal.
```

- Exit with `EXIT_FAILURE` or the project’s established CLI usage-error code.
- This behavior must be deterministic and tested.

---

# 9. Keyboard handling map

Bindings must be represented in one centralized action registry used by the Footer, `?` overlay, and command help so documentation cannot drift.

| Key | Context | Action |
|---|---|---|
| `Ctrl+C` | Global | Existing quit flow: cancel worker, mark session idle, exit `0` |
| `Esc` | Active run | Interrupt current run |
| `Esc` | Palette/overlay | Close topmost transient first |
| `Esc`, `Esc` within 400 ms | Idle, draft non-empty | Clear draft after placing it in recoverable draft stash |
| `Esc`, `Esc` within 400 ms | Idle, draft empty | Open rewind chooser at prior user turn |
| `Shift+Tab` | Global except modal text navigation | Cycle Agents → Plan → Route → Budget; composer remains focused |
| `Alt+P` | Global | Open model picker |
| `Ctrl+S` | Composer | Stash draft and clear composer |
| `Enter` | Composer | Send; during active run, queue |
| `Shift+Enter` | Composer | Insert newline |
| `Ctrl+Enter` | Composer | Send/queue regardless of multiline state |
| `Up` | Empty composer, queue non-empty | Take back newest queued follow-up |
| `Up` | Empty composer, no queue item | Previous prompt/draft history |
| `Down` | History navigation | Newer prompt and then active draft |
| `Tab` | Completion open | Accept ghost completion |
| `?` | Composer empty/global | Open shortcuts pane |
| `/` | Composer at column 0 | Open slash command palette |
| `Ctrl+O` | Global | Toggle full-screen transcript |
| `Ctrl+Shift+O` | Transcript overlay | Native scrollback/plain transcript escape |
| `Ctrl+T` | Global | Toggle Mission Control |
| `/agents`, `/plan`, `/route`, `/budget` | Composer | Switch the passive view from the single interaction point |
| `F1` | Global | Preserve existing help transcript injection |
| `A` | Pending approval card focused | Approve |
| `R` | Pending approval card focused | Reject |
| `E` | Pending approval card focused | Edit/add instruction |
| `Enter`/`Space` | Transcript header focused | Toggle collapse |
| `Left` | Transcript item focused | Collapse |
| `Right` | Transcript item focused | Expand |
| `End` | Transcript | Return to live output |
| `PageUp`/`PageDown` | Transcript | Scroll |
| `Ctrl+F` or `/` | Transcript overlay | Search transcript |
| `N`/`Shift+N` | Search active | Next/previous result |
| `M` | Agent focused | Open Mission Control for child |
| `C` | Child detail | Request child cancellation, then confirm |
| `Enter` | Onboarding | Continue/activate selected action |
| `Esc` | Onboarding | Back one step |
| `F` | Welcome/provider setup | Select fake provider when advertised |

### Escape timing rule

Do not delay interruption merely to detect a double press:

- If a run is active, first `Esc` interrupts immediately.
- A second `Esc` within 400 ms opens rewind only after the interrupt request has been acknowledged or enters the relevant post-interrupt view.
- If idle, the app may wait up to 250 ms before interpreting the first bare `Esc` when no transient is open.
- Closing a palette or overlay consumes the first `Esc` and does not count toward a destructive double-Escape action.

---

# 10. Slash commands and receipts

## 10.1 Existing commands retained

- `/help`
- `/agents`
- `/budget`
- `/plan`
- `/route`
- `/config`
- `/trust`
- `/resume`
- `/compact`
- `/cancel`
- `/quit`

## 10.2 New commands

### `/theme [dark|light|system]`

- Without argument: open theme picker.
- With valid argument: apply and emit:
  `Theme changed to Dark.`
- Invalid argument:
  `Usage: /theme [dark|light|system]`

### `/model [name]`

- Without argument: open model picker.
- With name: select for future attempts only.
- Receipt:
  `Model set to sonnet-4 for future attempts. Active attempts are unchanged.`

### `/missions`

- Opens Mission Control.
- Alias may be `/children`, but only `/missions` needs primary documentation.

## 10.3 Resume receipts

After any successful resume:

```text
Session resumed: 01JABC
Resume later with:
skail -r 01JABC
```

Active assignments remain immutable; future session branching requires a separate persisted-session contract.

## 10.4 Quit receipt and semantics

`/quit` retains existing behavior:

1. Cancel active worker.
2. Mark session idle.
3. Flush permitted session state.
4. Exit code `0`.

Do not reinterpret `/quit` as an immediate unclean app exit.

---

# 11. Implementation plan for the medium implementer

## Phase 1 — Semantic shell and boot separation

### `src/skail/tui/theme.py` — new

Define:

- `ThemeName`: dark, light, system.
- Immutable `ThemeTokens`.
- Dark and light token instances containing every required token.
- Token lookup and validation.
- System theme resolution.
- Reduced-motion preference.
- Conversion helpers for Textual CSS variables and Rich `Style` instances.

Requirements:

- One source of truth.
- No widget-local hex values.
- Unit test that dark/light token key sets are identical.
- Unit test that every required token exists and is a valid six-digit hex color.
- If dynamic Textual variables are version-limited, generate scoped CSS from tokens in this module rather than spreading compatibility logic among widgets.

### `src/skail/tui/app.py`

Refactor app lifecycle:

- Accept a bootstrap/runtime factory rather than requiring fully built runtime models for interactive startup.
- Mount the complete shell immediately.
- Add app states:
  - onboarding,
  - initializing,
  - ready,
  - recoverable error,
  - quitting.
- Start provider/model initialization in a Textual worker.
- Add centralized action/binding registry.
- Add responsive wide/narrow classes.
- Implement overlay stack:
  - transcript,
  - shortcuts,
  - theme,
  - model,
  - Mission Control.
- Preserve existing `App[int]` exit code behavior.
- Preserve existing control bindings while adding new bindings.
- Implement focus restoration after overlay close.
- Apply theme tokens and reduced-motion class.
- Keep runtime imports behind existing adapters; do not leak Textual into runtime modules.

### New onboarding module

Prefer a focused module such as:

`src/skail/tui/onboarding.py`

Define Textual screens/widgets for:

- welcome,
- provider selection,
- masked key entry,
- asynchronous validation,
- trust,
- theme,
- ready receipt.

Do not place secrets in reactive state that is serialized, logged, or included in debug representations. Keep key material in the narrowest possible in-memory bootstrap object and clear references after runtime construction where feasible.

### `src/skail/cli/main.py`

Reorder boot:

1. Parse invocation.
2. Determine interactive versus headless.
3. Preserve current runtime-first path for explicit headless execution.
4. For interactive TTY:
   - construct non-provider bootstrap metadata,
   - pass a runtime factory/configuration callback into `SkailApp`,
   - mount app before provider validation/model discovery.
5. With no credentials, enter onboarding rather than raising out of the TUI.
6. With credentials but a recoverable startup failure, show setup/error screen.
7. With `--fake-provider`, initialize through the same visible path but skip credential setup.
8. For non-TTY no-argument invocation, emit the exact actionable usage error rather than `ready`.

Do not weaken error handling for headless automation.

## Phase 2 — Incremental transcript and composer

### `src/skail/tui/chat.py`

Replace full `remove_children()` plus remount with keyed reconciliation.

Add:

- Item widget cache keyed by stable projection item ID.
- `update_from_view_model()` methods.
- Focusable transcript headers.
- Keyboard collapse actions.
- Role-edge semantic styles.
- Scroll pin/new-events behavior.
- Incremental streaming body updates.
- Plain-text transcript export for native scrollback/pager.
- Search hooks for transcript overlay.

If current projection items lack stable IDs, add stable pure-data IDs to projection output rather than synthesizing from display strings.

### `src/skail/tui/composer.py`

Replace the single-line input with:

- Multiline composer widget.
- Dynamic height 3–8 rows.
- Queue-above view.
- History controller.
- Recoverable draft stash.
- Slash fuzzy palette.
- Ghost completion.
- Character count.
- Contextual mode indicator.
- Keyboard behavior from the table.
- Mouse-accessible Send button.

Keep parsing/dispatch in `commands.py`; composer should generate intent, not execute runtime commands directly.

Implement fuzzy ranking as a small pure function:

1. exact command-prefix matches,
2. subsequence matches,
3. description/keyword matches,
4. stable alphabetical or registry-order tiebreak.

### `src/skail/tui/interrupts.py`

- Replace raw colors with tokens.
- Make each action focusable and keyboard-addressable.
- Implement `A`, `R`, `E` action handling with text-entry safeguards.
- Disable actions immediately after submission.
- Add terminal accepted/rejected visual state.
- Preserve optional instruction input.
- Ensure pending approval remains visible until projection confirms resolution.

## Phase 3 — Sidebar and overlays

### `src/skail/tui/agents.py`

- Stable slot colors.
- Separate selection from route-tab navigation.
- Keyboard detail navigation.
- Mission Control entry action.
- Explicit status labels.
- No implicit route mutation.

### `src/skail/tui/plan.py`

- Restyle steps.
- Add actionable plan card presentation where projection exposes pending decisions.
- Keyboard accept/reject/request-changes.
- Dim rejected plans without removing them.

### `src/skail/tui/route.py`

- Display route reason, model, fallback, attempt, and immutable-assignment label.
- Preserve existing route behavior.
- Ensure selecting an agent does not force-switch to this tab.

### `src/skail/tui/budget.py`

- Add eight-cell ambient meter.
- Add normal/warning/critical labels.
- Graceful unavailable-provider state.
- Use semantic tokens only.

### Optional new overlay modules

To avoid overloading `app.py`, use focused modules:

- `overlays/transcript.py`
- `overlays/shortcuts.py`
- `overlays/theme_picker.py`
- `overlays/model_picker.py`
- `overlays/missions.py`

Do not create a generic overlay framework unless at least three overlays genuinely share behavior beyond ordinary Textual `Screen` behavior.

## Phase 4 — Projection and command contracts

### `src/skail/tui/projection.py`

This file must remain Textual-free.

Permitted additions:

- Stable transcript item IDs.
- Queue view-model data.
- Child slot/color index as semantic integer `1..3`, not UI hex values.
- Pending approval decision state.
- Plan decision state.
- Initialization/resume status if these are represented by domain events.
- Receipt records where receipts need snapshot/event reconstruction.
- Mission-control pure-data fields.
- Model assignment immutability metadata.
- Derived unread/new-event counts if suitable.

Do not add:

- Textual widgets, messages, screens, CSS, colors, or `reactive`.
- Rich `Text`, `Style`, `Panel`, or markup.
- API keys or provider secrets.
- Widget-local collapse/focus state unless it is explicitly session-domain state.
- Animation frames.

Projection tests must continue to run in an environment where Textual is unavailable.

### `src/skail/tui/commands.py`

Retain existing command parsing and follow-up queue behavior.

Add registry metadata:

- command,
- aliases,
- synopsis,
- description,
- keywords,
- whether arguments are required,
- dispatch category.

Add:

- `/theme`
- `/model`
- `/missions`

Use the same registry for:

- parser validation,
- slash palette,
- `/help`,
- shortcut/command documentation.

Do not let widget code maintain a second hardcoded command list.

Receipts for resume and fork must include exact `skail -r <SESSION>` commands.

## Phase 5 — CSS and documentation

### TUI CSS

Whether inline or in `.tcss`:

- Reference generated semantic variables/classes.
- Remove all hardcoded role hex colors.
- Wide breakpoint: sidebar visible at `>=100`.
- Narrow breakpoint: sidebar becomes overlay access.
- Rounded borders only for interactive cards.
- Define explicit focus styles with `focusRing`.
- Ensure light mode is genuinely light rather than an inverted dark palette.

### README/help

- Add selected Twin sail logo.
- Update interactive startup and onboarding explanation.
- Document:
  - `Shift+Tab`,
  - `Alt+P`,
  - `Esc`,
  - `Ctrl+O`,
  - `Ctrl+T`,
  - `?`,
  - queue take-back,
  - fake-provider onboarding.
- Preserve headless examples.

---

# 12. What must not be changed

1. **Projection boundary**
   - `projection.py` remains Textual-free and Rich-free.

2. **Runtime dependency direction**
   - Runtime code does not import `skail.tui` or Textual.

3. **Headless parity**
   - `-p`, `--jsonl`, `-c`, `-r`, and `--no-session` remain operational and non-interactive.

4. **Direct launch**
   - Existing direct launch semantics remain intact.

5. **Attempt model assignment**
   - Changing the UI-selected model must not alter active attempt assignments.

6. **Agent limits**
   - No more than two child attempts per run where currently enforced.
   - No more than three concurrent children globally.

7. **Workspace safety**
   - Shared workspace writers must not overlap.
   - Trust does not bypass filesystem, shell, approval, or secret-redaction boundaries.

8. **Quit semantics**
   - `/quit` and `Ctrl+C` follow the established cancellation/session-idle cleanup and exit `0`.

9. **Event reconstruction**
   - Restoring snapshot plus subsequent events reconstructs the same domain-facing TUI state.

10. **Queue semantics**
    - Follow-ups submitted during an active run remain queued according to current ordering guarantees.

11. **Legacy code**
    - Do not import, edit, or address `legacy/skail/`.

---

# 13. Verification and test plan

## 13.1 Baseline before changes

Run and record:

```powershell
rtk pytest -q
python -m ruff check src tests scripts evals
python -m mypy src\skail
python scripts\smoke.py --fake-provider
```

## 13.2 New unit tests

### Theme tests

- Dark and light themes expose identical token names.
- Every required token exists.
- Every color is valid.
- Widgets contain no prohibited raw hardcoded legacy role hex values.
- Agent slots map stably to slots 1–3.
- Budget threshold styling changes at exactly 75% and 90%.

### Projection tests

- Imports successfully without Textual and Rich.
- Snapshot plus event replay reconstructs:
  - queue,
  - child slots,
  - pending approval,
  - plan decision state,
  - transcript stable IDs.
- Duplicate/replayed events do not create duplicate transcript items.
- API keys never appear in serialized state.

### Composer tests

- `Enter` sends.
- `Shift+Enter` inserts newline.
- Active run sends to queue.
- Empty-composer `Up` first takes back the newest queued prompt.
- With no queued prompt, `Up` navigates history.
- `Ctrl+S` stashes and clears.
- Ghost completion ranking is deterministic.
- Overflow count is correct.
- `Tab` completes without accidental dispatch.
- Draft survives palette open/close.

### Transcript tests

- Existing item widgets are not remounted when only streaming content changes.
- New events mount one new widget.
- Removed items remove only their own widget.
- Collapse state survives projection updates.
- Keyboard expand/collapse works.
- Scrolled-up transcript does not jump to bottom.
- Pinned transcript follows new content.
- Plain transcript export contains no Textual/Rich control markup.

### Approval tests

- `A`, `R`, and `E` work when the card has focus.
- Typing `a`, `r`, or `e` in an instruction field does not trigger decisions.
- Duplicate activation is prevented.
- Rejected state is retained and dimmed.
- Escape does not make an approval decision.

### Command tests

- Existing commands retain parsing and dispatch.
- New commands parse.
- Invalid arguments return exact usage strings.
- Command registry drives palette and help.
- `/resume` receipts contain:
  `skail -r <SESSION>`

## 13.3 TUI pilot tests

Using Textual’s app pilot:

1. Interactive no-credential boot mounts app rather than throwing `ProviderConfigurationError`.
2. Welcome step is visible.
3. Fake-provider path reaches ready cockpit.
4. Provider validation shows loading state.
5. Validation failure remains in app and allows retry.
6. Key field is masked.
7. Trust and theme steps are keyboard-operable.
8. Theme preview is restored on Escape.
9. Wide viewport shows sidebar.
10. Width 99 hides sidebar and panel bindings remain usable.
11. `Ctrl+O`, `?`, and `Ctrl+T` open and close correctly.
12. Overlay close restores focus.
13. `Shift+Tab` cycles all four passive panels while focus remains in the composer.
14. `Alt+P` changes future model selection without mutating active attempt display.
15. Clicking an agent does not switch to Route.
16. `F1` still injects help into transcript.
17. `/quit` cancels, marks idle, and exits `0`.

## 13.4 CLI tests

Use isolated environment mappings.

| Case | Expected |
|---|---|
| TTY, no args, no keys | TUI mounts onboarding |
| TTY, no args, valid key | TUI mounts, then async initialization |
| TTY, no args, invalid key | TUI mounts recoverable setup error |
| TTY, `--fake-provider` | TUI mounts ready flow without key |
| Non-TTY, no args | Actionable TTY/headless usage error; never `ready` |
| Non-TTY, `-p`, missing key | Existing provider configuration failure |
| `-p` with fake provider | Existing headless prompt behavior |
| `--jsonl` | Machine-readable output remains unpolluted by TUI text |
| `-r <id>` | Session resume works and receipt uses same ID |
| `-c` | Existing continuation semantics retained |
| `--no-session` | No unexpected session persistence |
| `/quit` or `Ctrl+C` | Idle cleanup and code `0` |

## 13.5 Security tests

- Entered keys do not appear in:
  - transcript,
  - projection snapshots,
  - event logs,
  - session files,
  - exception text,
  - debug logs,
  - widget repr snapshots.
- Provider errors redact authorization headers and key-like strings.
- Trust choice does not bypass approvals.
- Mission Control cannot launch a fourth child.
- Child cancellation cannot leave shared-writer locks orphaned.
- Plain transcript export cannot contain secrets excluded from the visible projection.

## 13.6 Performance regression tests

Use a synthetic transcript with:

- 1,000 completed items,
- one actively streaming item,
- multiple collapsed tool items.

Verify:

- A stream update changes one item body instead of rebuilding all children.
- Keyboard input remains responsive.
- Existing scroll position remains stable.
- Theme switching does not reconstruct domain projection.
- Spinner timers stop when screens/widgets unmount.

Precise timing thresholds should be selected from baseline CI performance rather than guessed, but DOM mount counts should be asserted directly.

## 13.7 Final repository checks

```powershell
rtk pytest tests\unit -q
rtk pytest -q
python -m ruff check src tests scripts evals
python -m mypy src\skail
python scripts\smoke.py --fake-provider
python -m build
graphify update .
rtk diff
```

---

# 14. Acceptance checklist

## 14.1 Visual sleekness

- [ ] Dark shell uses `#0B0D10`; light shell uses `#F6F7F9`.
- [ ] Sail blue is the only general-purpose accent.
- [ ] Violet, green, amber, and red appear only for semantic state.
- [ ] No widget contains legacy hardcoded role colors.
- [ ] Rounded borders appear only around interactive controls/cards.
- [ ] Passive transcript entries use edges and separators rather than nested boxes.
- [ ] Mode, model, budget, agents, and run state remain visible.
- [ ] Budget bar uses exactly eight `■`/`·` cells.
- [ ] Agent colors remain stable by slot.
- [ ] No emoji are used.
- [ ] Spinner is a subtle `✻` shimmer and respects reduced motion.
- [ ] Light theme has sufficient contrast and is not a naive inversion.
- [ ] At width 99, all sidebar content remains keyboard-accessible.
- [ ] At width 100, the wide layout activates without clipping.
- [ ] Focus is visible on every interactive element.

## 14.2 Feature-retention map

| Existing feature/invariant | New location |
|---|---|
| Header | Restyled top header row |
| Model display | Statusline and model picker |
| Mode display | Statusline and composer |
| Cost/limit | Statusline ambient meter and Budget tab |
| Active agents | Statusline, Agents tab, Mission Control |
| 60/40 transcript/sidebar | Wide responsive layout |
| Sidebar hidden under 100 columns | Narrow overlay panels |
| Chat transcript | Incrementally reconciled `ChatTranscript` |
| Click collapse | Retained on transcript header |
| Keyboard collapse | Added Enter/Space/Left/Right |
| Interrupt widget | Restyled approval/interrupt card |
| Approve/reject | Buttons retained; A/R/E added |
| Agents tab | Restyled Agents panel |
| Plan tab | Restyled Plan panel and actionable cards |
| Route tab | Restyled Route panel |
| Budget tab | Restyled Budget panel |
| Composer Send button | Retained in multiline composer |
| Follow-up queueing | Visible queue above composer |
| `/help` | Retained; driven by command registry |
| `/agents` | Retained; opens Agents |
| `/budget` | Retained; opens Budget |
| `/plan` | Retained; opens Plan |
| `/route` | Retained; opens Route |
| `/config` | Retained |
| `/trust` | Retained and reused by onboarding |
| `/resume` | Retained with exact resume receipt |
| `/compact` | Retained |
| `/cancel` | Retained |
| `/quit` | Retained with cancellation, idle cleanup, exit `0` |
| `Ctrl+C` | Retained quit behavior |
| `Ctrl+T` | Mission Control; direct Ctrl+A/B/P/R panel bindings are removed |
| `F1` help injection | Retained exactly |
| Headless `-p` | Unchanged runtime-first path |
| `--jsonl` | Unchanged, no TUI contamination |
| `-c` | Unchanged |
| `-r` | Unchanged plus receipt |
| `--no-session` | Unchanged |
| `--fake-provider` | Retained and advertised during onboarding |
| Projection snapshot/event reconstruction | Preserved and expanded with pure-data fields only |
| Runtime never imports Textual | Preserved |
| At most three concurrent children | Preserved and displayed as `n/3` |
| Immutable per-attempt model | Explicitly labeled in Route/Mission Control |
| Shared-writer exclusion | Preserved and visible in Mission Control |
| No-credential interactive boot | Changed from hard exit to onboarding cockpit |
| Non-TTY no-arg `ready` | Replaced by actionable usage error |
| Raw startup exception | Replaced by sanitized recoverable error screen |
| Synchronous cold start | Replaced by mounted shell plus worker initialization |
| Full-DOM transcript rebuild | Replaced by stable-ID incremental reconciliation |
| Agent click switches Route tab | Removed; selection stays in Agents |
| Dark-only hardcoded colors | Replaced by semantic dark/light themes |

## 14.3 Onboarding acceptance

- [ ] `skail` in an interactive TTY with no credentials mounts the TUI.
- [ ] Twin sail logo appears in the welcome cockpit.
- [ ] Step ladder shows Welcome, Provider, Trust, Theme, Ready.
- [ ] Provider key input is masked and asynchronously validated.
- [ ] Fake provider is offered with the exact hint `skail --fake-provider`.
- [ ] Key material remains process-memory-only and is not serialized.
- [ ] Trust copy names the exact resolved workspace.
- [ ] Theme picker previews live and restores on Escape.
- [ ] Ready step prints `skail -r <SESSION>`.
- [ ] Existing credentials still mount the shell before slow initialization.
- [ ] Recoverable provider errors never eject users to raw stderr.
- [ ] Explicit headless invocations retain existing failure semantics.

## 14.4 Keyboard-completeness acceptance

- [ ] Every mouse action has a keyboard equivalent.
- [ ] Approval works through A/R/E.
- [ ] Transcript collapse works without a mouse.
- [ ] Shift+Tab cycles Agents, Plan, Route, and Budget while focus remains in the composer.
- [ ] Alt+P opens model selection.
- [ ] Ctrl+S stashes a draft.
- [ ] Up takes back a queued prompt before navigating history.
- [ ] Ctrl+O opens full transcript.
- [ ] Ctrl+Shift+O provides native/plain scrollback access.
- [ ] `?` opens shortcut help.
- [ ] Ctrl+T opens Mission Control.
- [ ] Esc interrupts immediately during an active run.
- [ ] Double-Escape clearing/rewind behavior is recoverable and does not conflict with modal dismissal.
- [ ] Overlay close restores prior focus.

## Recommended delivery sequence

1. Boot split and onboarding shell.
2. Theme tokens and semantic CSS.
3. Incremental transcript reconciliation.
4. Multiline composer, history, queue, and command completion.
5. Keyboard-complete approvals.
6. Sidebar restyling and responsive overlays.
7. Transcript, shortcut, theme, model, and Mission Control overlays.
8. Receipts and new commands.
9. Security, performance, headless parity, and full regression verification.

This sequence fixes the highest-impact architectural and usability defects first while keeping each stage independently testable and preserving Skail’s runtime boundaries.
