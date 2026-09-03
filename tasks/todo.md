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

- [x] 3.1 Implement provider adapter/model factory and fake provider.
- [x] 3.2 Implement credential resolution and redaction.
- [x] 3.3 Implement first-class LLM Gateway adapter.
- [x] 3.4 Implement DevPass and generic OpenAI-compatible adapters.
- [x] 3.5 Implement lazy LangChain provider registry.
- [x] 3.6 Implement evidence-bearing model catalog.
- [x] Checkpoint D: usable providers.

## Routing and budgets

- [x] 4.1 Implement capability requirements and floors.
- [x] 4.2 Implement deterministic selector and route explanations.
- [x] 4.3 Implement total-attempt cost estimates.
- [x] 4.4 Implement transactional budget reservations.
- [x] 4.5 Implement assignment service and batch funding.
- [x] 4.6 Implement task-bound model middleware and provider fallback.
- [x] Checkpoint E: economic routing.

## Tools and safety

- [x] 5.1 Assemble and describe the default DeepAgents tool surface.
- [x] 5.2 Enforce virtual workspace filesystem boundaries.
- [x] 5.3 Implement command policy and durable approvals.
- [x] 5.4 Implement `ask_user` interrupts.
- [x] 5.5 Implement trusted profiles, skills, and memory loading.
- [x] 5.6 Implement optional MCP/custom tool boundary.
- [x] Checkpoint F: safe useful tools.

## Orchestration

- [x] 6.1 Implement built-in profile definitions.
- [x] 6.2 Implement task validation, fingerprint, and registry.
- [x] 6.3 Implement dependency scheduler and three-child semaphore.
- [x] 6.4 Implement shared-workspace write leases.
- [x] 6.5 Implement production compiled task graph, context packets, and result evaluation.
- [x] 6.6 Implement deterministic failure monitor.
- [x] 6.7 Implement one escalation then return-to-lead.
- [x] 6.8 Build capable lead graph and delegation controls.
- [x] Checkpoint G: headless Rudder core.

## Sessions and UX

- [x] 7.1 Implement session lifecycle, resume, context-aware compaction, and export.
- [x] 7.2 Implement CLI, print/JSONL modes, and exit codes.
- [x] 7.3 Build conversation-first TUI shell and projections.
- [x] 7.4 Add agent rail, route, and budget views.
- [x] 7.5 Add commands, approvals, questions, cancellation, and supported steering.
- [x] Checkpoint H: complete daily-use harness.

## Validation and release

- [ ] 8.1 Build deterministic evaluation runner including context-policy metrics.
- [ ] 8.2 Curate at least 50 approved oracle-backed fixtures.
- [ ] 8.3 Validate and tune completion, cost, and parallel-time gates.
- [ ] 8.4 Complete security/recovery hardening.
- [ ] 8.5 Complete performance/context hardening and context-policy benchmarking.
- [ ] 8.6 Complete packaging, docs, installation, and release candidate.
- [ ] Final checkpoint: all stable-release criteria pass.

## Post-stable / isolated

- [ ] P.1 Worktree-isolated concurrent writers.
- [ ] P.2 Preview-backed background task executor, if approved.
- [ ] P.3 Editor protocol adapter.
