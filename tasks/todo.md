# Rudder Delivery Checklist

Status: Active; implementation is in progress on the `rudder` branch.

## Approval and boundary

- [x] 0.1 Resolve open specification decisions and accept ADR 0001.
- [x] 0.2 Create the approved branch/reference and relocate AutoConduck to `legacy/autoconduck/`.
- [x] 0.3 Create installable Rudder package and fake-provider smoke.
- [x] 0.4 Establish offline Windows/Linux test and CI skeleton.
- [x] Checkpoint A: clean product boundary.

## Framework feasibility

- [x] 1.1 Prove lead DeepAgent, streaming, tools, and checkpoints.
- [x] 1.2 Prove compiled subagent and pre-call task-bound model assignment.
- [x] 1.3 Prove nested streaming, three-child concurrency, and cancellation.
- [x] 1.4 Decide and isolate/defer preview background agents.
- [x] Checkpoint B: framework feasibility.

## Durable core

- [x] 2.1 Implement domain IDs, task/attempt/result, routing, and usage types.
- [x] 2.2 Implement versioned event union and event bus.
- [x] 2.3 Implement typed layered configuration with provenance.
- [x] 2.4 Implement project trust records and gates.
- [x] 2.5 Implement Rudder SQLite journal and migrations.
- [x] 2.6 Implement LangGraph checkpoint wrapper and reconciliation.
- [x] Checkpoint C: durable core contracts.

## Providers and models

- [ ] 3.1 Implement provider adapter/model factory and fake provider.
- [ ] 3.2 Implement credential resolution and redaction.
- [ ] 3.3 Implement first-class LLM Gateway adapter.
- [ ] 3.4 Implement DevPass and generic OpenAI-compatible adapters.
- [ ] 3.5 Implement lazy LangChain provider registry.
- [ ] 3.6 Implement evidence-bearing model catalog.
- [ ] Checkpoint D: usable providers.

## Routing and budgets

- [ ] 4.1 Implement capability requirements and floors.
- [ ] 4.2 Implement deterministic selector and route explanations.
- [ ] 4.3 Implement total-attempt cost estimates.
- [ ] 4.4 Implement transactional budget reservations.
- [ ] 4.5 Implement assignment service and batch funding.
- [ ] 4.6 Implement task-bound model middleware and provider fallback.
- [ ] Checkpoint E: economic routing.

## Tools and safety

- [ ] 5.1 Assemble and describe the default DeepAgents tool surface.
- [ ] 5.2 Enforce virtual workspace filesystem boundaries.
- [ ] 5.3 Implement command policy and durable approvals.
- [ ] 5.4 Implement `ask_user` interrupts.
- [ ] 5.5 Implement trusted profiles, skills, and memory loading.
- [ ] 5.6 Implement optional MCP/custom tool boundary.
- [ ] Checkpoint F: safe useful tools.

## Orchestration

- [ ] 6.1 Implement built-in profile definitions.
- [ ] 6.2 Implement task validation, fingerprint, and registry.
- [ ] 6.3 Implement dependency scheduler and three-child semaphore.
- [ ] 6.4 Implement shared-workspace write leases.
- [ ] 6.5 Implement production compiled task graph and result evaluation.
- [ ] 6.6 Implement deterministic failure monitor.
- [ ] 6.7 Implement one escalation then return-to-lead.
- [ ] 6.8 Build capable lead graph and delegation controls.
- [ ] Checkpoint G: headless Rudder core.

## Sessions and UX

- [ ] 7.1 Implement session lifecycle, resume, compaction, and export.
- [ ] 7.2 Implement CLI, print/JSONL modes, and exit codes.
- [ ] 7.3 Build conversation-first TUI shell and projections.
- [ ] 7.4 Add agent rail, route, and budget views.
- [ ] 7.5 Add commands, approvals, questions, cancellation, and supported steering.
- [ ] Checkpoint H: complete daily-use harness.

## Validation and release

- [ ] 8.1 Build deterministic evaluation runner.
- [ ] 8.2 Curate at least 50 approved oracle-backed fixtures.
- [ ] 8.3 Validate and tune completion, cost, and parallel-time gates.
- [ ] 8.4 Complete security/recovery hardening.
- [ ] 8.5 Complete performance/context hardening.
- [ ] 8.6 Complete packaging, docs, installation, and release candidate.
- [ ] Final checkpoint: all stable-release criteria pass.

## Post-stable / isolated

- [ ] P.1 Worktree-isolated concurrent writers.
- [ ] P.2 Preview-backed background task executor, if approved.
- [ ] P.3 Editor protocol adapter.
