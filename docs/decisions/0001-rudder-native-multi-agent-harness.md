# ADR 0001: Build Rudder as a Native Multi-Agent Harness

Status: Accepted
Date: 2026-09-02

> ADR 0006 supersedes decision 3 and the blanket rejection of precompiled task DAGs with a typed,
> adaptive execution-plan contract. The native harness boundary, capable lead, standard `task`
> compatibility, task-bound model stickiness, concurrency maximum, and retry limit remain active.

## Context

AutoConduck is a local model-routing proxy with optional plugin and OMA orchestration features. That position limits its control over the main agent loop, tool execution, subagent lifecycle, model ownership, safety, and user experience. The desired product is instead a coding harness launched directly as `rudder`, aimed at users who want orchestrated speed and accuracy within a budget.

DeepAgents provides a harness framework on LangGraph with a capable agent loop, filesystem and execution facilities, skills/memory, subagents, middleware, human interrupts, streaming, and persistence integration. It allows Rudder to own product policy without implementing a complete agent runtime from scratch.

## Decision

1. Rudder will be a native terminal coding harness, not a proxy, plugin, daemon, or compatibility layer for another harness.
2. The lead will be a capable DeepAgent that can work directly and selectively delegate. It will not be a coordinator that can only create tasks.
3. Superseded in part by ADR 0006. Rudder retains DeepAgents' standard `task` surface, but routes it
   through the same Rudder-owned adaptive plan admission and lifecycle services as typed plans.
4. Models will be assigned at the lead-run or task-attempt boundary. Middleware installs the recorded model; it does not reroute each model call.
5. Synchronous foreground subagents are the stable initial path. Preview asynchronous subagents will be optional and isolated behind a Rudder `TaskExecutor` adapter.
6. Concurrency will be configurable from one to three child agents. Delegation depth defaults to one. Shared-workspace writers are serialized until worktree isolation is implemented.
7. A failed task gets at most one automatic stronger-model attempt. A second failure returns structured evidence to the lead.
8. OMA, the SLM, proxy/plugin planes, hook shims, and old compatibility commands will not be part of the Rudder runtime.
9. The current AutoConduck source will move to `legacy/autoconduck/` on a new branch as an inert reference. Rudder will not provide configuration or runtime migration helpers.
10. Provider breadth will use LangChain integrations behind Rudder adapters, with first-class LLM Gateway and DevPass support. Automatic routing requires trusted capability and price evidence.

## Rationale

- A capable lead preserves the low-friction behavior of lightweight harnesses for small tasks.
- The task tool gives natural model-driven delegation and context isolation without forcing users to author graphs.
- A compiled lifecycle wrapper gives Rudder deterministic ownership of the policies that matter economically and operationally.
- Task-bound routing is understandable, replayable, and consistent with model specialization; per-call switching would make one task behaviorally unstable.
- A maximum of three agents captures useful parallelism while bounding cost, output contention, and cognitive load.
- One escalation is enough to recover from under-tiering without creating an expensive recursive retry ladder.
- Framework adapters prevent a preview feature or dependency upgrade from defining Rudder's public contracts.

## Alternatives considered

### Rebrand the existing proxy/plugin system

Rejected because Rudder would still lack authoritative control of the lead loop, tools, child scheduling, and task state. It would retain the integration complexity the new product is meant to remove.

### Build a harness from scratch

Rejected because the agent loop, graph state, checkpointing, tool middleware, subagents, and interrupts are already available in DeepAgents/LangGraph. Rudder's differentiator is orchestration and economics, not reimplementing those foundations.

### Fork or clone dcode

Rejected as the architectural foundation. Rudder should emulate the proven behavior of a capable lead with selective delegation, but use a maintained framework boundary and its own policies rather than depend on another product's internal implementation.

### Precompile every user request into a static task DAG (superseded in part by ADR 0006)

The rejection of a mandatory static DAG remains. ADR 0006 permits an optional typed, revision-aware
plan interpreted by a fixed coordinator, while simple work remains direct and todo prose remains
non-executable.

### Route every model call dynamically

Rejected because it breaks task ownership, complicates context/cache behavior, makes outcomes difficult to explain, and can silently change competence during a tool loop.

### Use only one agent

Rejected because independent parallel work, specialist context isolation, and independent verification are central to the product intent. The lead still remains capable of direct execution.

### Make preview async subagents the only execution path

Rejected because individual steering/cancellation is attractive but the API is preview. The first stable core should rest on the mature synchronous path.

## Consequences

### Positive

- Rudder has one coherent runtime and user experience.
- Delegated work has explicit identities, assignments, budgets, results, and recovery.
- Most ordinary prompts require no orchestration syntax.
- Provider/model choices are visible and measurable per task.
- AutoConduck complexity can be removed rather than kept as compatibility debt.

### Negative

- The repository undergoes a deliberate rewrite rather than an incremental product upgrade.
- DeepAgents/LangGraph upgrades require contract testing and adapter maintenance.
- Shared-workspace write serialization limits early parallel implementation speed.
- Automatic routing cannot honestly support every newly discovered model without evidence.
- Background steering may remain experimental after the initial stable release.

### Risks requiring validation

- Nested streaming, state propagation, and cancellation behavior of compiled subagents.
- Reliable assignment injection before the first model call.
- Budget reservation behavior under concurrent `task` calls.
- Windows behavior of the execution backend and cancellation.
- LLM Gateway streaming tool calls and usage normalization.

These are first-phase contract spikes and are launch-blocking if no safe adapter design is found.

## Approval effect

Changing this ADR to `Accepted` authorizes planning against these boundaries; it does not by itself authorize code migration or dependency changes. Implementation begins only after the specification set and active plan are approved.
