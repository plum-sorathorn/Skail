# Pre-Mortem Analysis: Skail

Status: Proposed risk analysis
Date: 2026-09-02
Scenario: Skail launches in 14 days, on 2026-09-16, and fails. This is a stress-test date, not an implementation schedule.

## Failure narrative

Skail launched with an appealing “just prompt, we'll orchestrate” story, but early users found that multi-agent runs cost more than a strong single model, parallel writers interfered, and model selection was hard to trust. Provider-specific tool calling broke despite simple chat tests. Users could not distinguish running, queued, approval-blocked, and retrying work. A few interrupted sessions resumed with stale reservations or repeated work. The team spent launch week repairing framework and provider behavior instead of proving that Skail improved completed-work economics.

## Tigers — real risks

### T1. Task-bound model assignment fails under real DeepAgents composition

**Urgency:** Launch-blocking
**Why real:** Skail depends on assigning a model before a child starts and keeping it stable. Child state propagation, middleware order, nested streaming, and cancellation are framework contracts; async subagents are preview.

**Mitigation:** Complete framework contract Tasks 1.1–1.3 first. Pin versions; test first-call assignment, immutability, nested namespaces, checkpoints, three-child concurrency, and cancellation with deterministic fakes. Isolate or defer async support.

**Closure evidence:** Every fake model call carries the expected assignment ID and mutation fails safely.

### T2. The economic promise is unproven

**Urgency:** Launch-blocking
**Why real:** Lead planning, repeated exploration, child output, escalation, and synthesis can make several cheap agents cost more than one strong agent. Per-call price is not cost per completed task.

**Mitigation:** Compare `auto` with fixed economy, fixed quality, serial, and no-delegation baselines on oracle-backed fixtures. Gate claims on completion, cost per completion, and wall time. If gates fail, remove savings claims or ship fixed/manual routing while tuning.

**Closure evidence:** Two reproducible runs over at least 50 approved fixtures meet accepted thresholds.

### T3. Parallel agents corrupt shared work

**Urgency:** Launch-blocking
**Why real:** Shell access makes an agent write-capable even without edit tools. Concurrent edits, formatters, generated files, and user changes can collide, especially across Windows path/Git behavior.

**Mitigation:** Treat execute and unknown extension tools as write-capable. Enforce one shared-workspace writer across lead and children. Prove lease recovery under crash/cancel. Defer worktrees until isolation and integration are tested.

**Closure evidence:** Race tests show no overlapping writers and preserve user changes after failure/cancellation.

### T4. Hard budgets are only cosmetic

**Urgency:** Launch-blocking
**Why real:** Parallel selection can overcommit, usage may be absent, output is uncertain, callbacks can duplicate, and child fan-out can strand the lead without synthesis budget.

**Mitigation:** Use transactional reservations, conservative attempt estimates, idempotent settlement, a retained lead allowance, and visible bounded overshoot. Test concurrent reservation races and duplicate callbacks.

**Closure evidence:** Tests cannot over-reserve or double-charge, and every batch retains lead continuation capacity.

### T5. Provider breadth becomes a false compatibility claim

**Urgency:** Launch-blocking for advertised providers; track for others
**Why real:** Construction, streaming tool calls, structured output, usage, and error formats vary. OpenAI-compatible APIs frequently diverge on agent behavior. LLM Gateway cannot be proven by text chat alone.

**Mitigation:** Publish constructible, contract-tested, auto-eligible, and CI-maintained levels separately. Require full contracts for first-class providers; keep unknown integrations manual/unverified.

**Closure evidence:** LLM Gateway and DevPass pass their declared contracts, and UI/docs show exact support level.

### T6. Shell and extension safety relies on prompts

**Urgency:** Launch-blocking
**Why real:** DeepAgents filesystem permissions do not automatically secure execute, custom, or MCP tools. Autonomous behavior raises the impact of a command mistake, untrusted project instruction, or path escape.

**Mitigation:** Enforce canonical workspace paths, separate execution policy, project trust, side-effect metadata, durable approvals, and secret redaction. Run traversal, junction, injection, extension, and exfiltration suites on Windows/Linux.

**Closure evidence:** No critical/high finding remains and enforcement is demonstrably outside prompts.

### T7. Resume duplicates paid work or lies about state

**Urgency:** Launch-blocking
**Why real:** LangGraph checkpoints and Skail's journal cannot share one transaction. A crash between provider execution, settlement, terminal state, and checkpointing can create conflicting truths.

**Mitigation:** Use idempotency keys and explicit reconciliation. Mark uncertain calls interrupted, not succeeded. Never replay them automatically without evidence. Test every crash boundary.

**Closure evidence:** Recovery tests show no terminal task reruns, duplicate usage, or auto-approved pending action.

### T8. The rewrite recreates Skail complexity under new names

**Urgency:** Launch-blocking at architecture review; track thereafter
**Why real:** Provider breadth, routing, budgets, profiles, persistence, TUI, extensions, background agents, and worktrees can recreate multiple planes before a useful core exists.

**Mitigation:** Hold stable scope to synchronous foreground subagents and shared single-writer execution. Deliver the headless core before UI polish. Isolate background agents, worktrees, editor protocols, and optional integrations. Prohibit legacy imports.

**Closure evidence:** Checkpoint G passes without optional planes or legacy runtime dependencies.

### T9. Autonomous state is not understandable

**Urgency:** Fast-follow; launch-blocking if approval/task state is ambiguous
**Why real:** Running, queued, waiting, escalated, and returned states are easy to hide in chat prose, making cost and safety impossible to judge.

**Mitigation:** Present versioned event projections, distinguish todos from tasks, and show status/model/cost/write posture/blocker. Test comprehension before visual polish.

**Closure evidence:** A tester identifies each agent's state, model, spend, and blocker without reading its transcript.

### T10. Model evidence and prices become stale

**Urgency:** Fast-follow
**Why real:** Models, price, limits, and tool behavior change. Stale price breaks budgets; stale capability produces poor routes.

**Mitigation:** Store field provenance/as-of times and catalog revisions. Reject unusable price data for hard budgets, schedule contract refresh, and never infer capability from names.

**Closure evidence:** Staleness is visible and refresh cannot silently auto-enable an unmeasured model.

## Paper Tigers — concerns that should not drive the architecture

### P1. Skail must use as few tools as Pi

Pi's restraint is useful, but an exact tool count is not the goal. Skail needs files, execution, tasks, todos, skills, memory, and questions. Duplicate tools, unclear side effects, and excessive outputs are the actual risks.

### P2. Removing OMA and the SLM removes all intelligence

A capable lead can delegate through DeepAgents, while Skail enforces lifecycle, budgets, routing, concurrency, and failure policy. Rebuilding OMA would add a second planner without proven value.

### P3. Three agents is too restrictive

Three intentionally bounds cost, state, and contention for budget-conscious local coding. Evidence can justify a later change; unbounded fan-out is not needed for the initial product.

### P4. No Skail migration helper loses every existing user

Skail is intentionally a new product with incompatible concepts. Leaving old data untouched and documenting fresh setup is sufficient; a compatibility layer would preserve removed architecture.

### P5. Every LangChain provider must be first-class at launch

Manual construction can be broad, but advertised maintenance and automatic routing should remain evidence-gated.

### P6. A native harness must expose a local HTTP API

CLI, TUI, and JSONL can use `RunController` directly. A server would add lifecycle and security surfaces without serving the initial terminal use case.

## Elephants — under-discussed assumptions

### E1. Will the lead know when delegation is worth it?

“Just prompt” relies on the lead's decision quality. Evaluations must score direct-versus-delegate choices with forced-direct and forced-delegate counterfactuals, not only model routing.

### E2. Which objective wins when speed, accuracy, and budget conflict?

The spec treats cost per completed task as the economic target with completion and time guardrails. This priority needs explicit confirmation so tuning does not optimize different objectives.

### E3. Will users trust autonomous shell access?

Frequent approvals destroy autonomy; permissive defaults destroy trust. Test approval frequency and action-preview comprehension before tuning safe-command defaults.

### E4. Is “Skail” available and distinguishable?

Package registries, repository names, trademarks, and searchability were checked. Resolved: the product full name is Skail Harness, the Python distribution name is `skail-harness`, and the console command is `skail`.

### E5. Who maintains providers and the model catalog?

Broad inheritance decays without ownership, refresh cadence, and CI access. Define maintained-provider criteria and deprecation policy before claims.

### E6. Does orchestration actually save context?

Task descriptions, artifacts, results, and failure handoffs can still bloat the lead. Measure context/cache behavior and enforce bounded summaries plus artifact references.

### E7. Are seven built-in profiles too many?

Some roles may overlap in actual prompts. Instrument profile use and consolidate only from evidence, not intuition.

### E8. What if explicit user instructions request unsafe orchestration?

“Explicit intent wins” must consistently mean orchestration preferences, never safety, workspace, hard-budget, or platform boundaries.

### E9. Can retrying from partial work make attempt two worse?

The stronger model may inherit broken changes. Handoffs need changed-path/diff evidence, and attempt two may alter only task-owned changes. Worktrees may later make this cleaner.

## Action plans for launch-blocking Tigers

Dates are for the 14-day scenario, not public commitments.

| Risk | Action | Best owner | Due | Gate |
|---|---|---|---|---|
| T1 Framework binding | Finish Tasks 1.1–1.3 and accept framework version ADR. | Runtime engineering | 2026-09-04 | Assignment/stickiness/stream/cancel contracts pass. |
| T2 Economics | Approve fixtures and run all policy counterfactuals twice. | Product + evaluation | 2026-09-13 | Gates pass or savings claims are removed. |
| T3 Workspace corruption | Enforce global write lease and crash/cancel race suite. | Runtime + safety | 2026-09-09 | No writer overlap; user changes preserved. |
| T4 Budgets | Ship transactional reservation/settlement and duplicate-callback tests. | Routing + storage | 2026-09-08 | No over-reservation; lead allowance remains. |
| T5 Providers | Pass LLM Gateway/DevPass advertised contracts and publish levels. | Provider engineering | 2026-09-10 | First-class providers pass declared checks. |
| T6 Safety | Complete threat model and adversarial path/command/trust/secret tests. | Security + runtime | 2026-09-12 | No critical/high issue. |
| T7 Resume | Test checkpoint/journal crash boundaries and reconciliation. | Persistence engineering | 2026-09-10 | No duplicate work/usage; uncertainty is explicit. |
| T8 Scope | Keep stable core synchronous/shared; enforce legacy boundary. | Technical lead | 2026-09-03 and each checkpoint | Headless core precedes optional/TUI work. |
| T9 Visibility | Run task/approval/budget comprehension script. | Product design + TUI | 2026-09-13 | State/model/cost/blocker understood without transcript. |

## Pre-launch review

Re-run this exercise two to three weeks before a real launch. Verify framework assumptions, fixture representativeness, exact-release LLM Gateway behavior, tool-policy bypasses, crash reconciliation, evidence behind savings/provider claims, optional feature labels, and whether users understand todo/task/attempt/escalation/fallback distinctions.

## Bottom line

Skail is implementable, but it is not merely “DeepAgents plus a router.” The launch-critical proof is a headless fake-provider synchronous core with assignment stickiness, budget reservations, one-writer scheduling, one escalation, and crash-safe state. Provider breadth, the full TUI, background agents, and worktrees must not get ahead of that proof.
