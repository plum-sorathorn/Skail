# Skail design set

Status: v0.1.0 candidate documentation; exact-final-commit Windows/Linux verification remains pending
Date: 2026-09-16

Skail is the native, budget-aware multi-agent coding harness built on DeepAgents. It
supersedes an archived predecessor implementation that used proxy, plugin, and sidecar surfaces.
These documents contain normative product and engineering contracts; they are not, by themselves,
proof that a capability has been qualified. The active implementation and release authority is
[ADR 0006](../decisions/0006-adaptive-execution-and-release-boundaries.md) and the
[adaptive orchestration guide](../../tasks/skail-adaptive-orchestration-and-release-plan.md).

## Release status

The Phase 22 candidate-bound Windows verification passed for the source candidate recorded in the
active guide, including offline tests, packaging, smoke, benchmarks, and paired evaluation. This is
not release sign-off: exact-final-commit Windows/Linux verification remains pending and must be
regenerated or obtained for the frozen documentation commit in Phase 24. Live-provider quality,
economic qualification, and production route promotion remain separate Q1 work.

Windows verification is green on `421e8e4` (Windows, Python 3.14.6), covering the journal
connection-pool fix (`6809874`) and the eval-journal-close fix (`421e8e4`): 1377.8 appends/sec
against the unchanged 100 appends/sec gate, with synchronous=FULL and per-op commit/rollback
preserved. Measurements from the earlier documentation commit do not carry over as evidence for
this commit. Linux CI raw evidence is still required; Linux green is not claimed.

Read in this order:

1. [Product specification](SPEC.md) — users, promises, requirements, commands, configuration, and acceptance criteria.
2. [Technical architecture](ARCHITECTURE.md) — runtime topology, state, module boundaries, data contracts, routing, persistence, providers, and security.
3. [Feature contracts](FEATURES.md) — exact behavior and edge cases for orchestration, subagents, model assignment, budgets, failure handling, tools, sessions, and the terminal UI.
4. [Legacy isolation](MIGRATION.md) — how the Skail implementation becomes an inert reference under `legacy/skail/`.
5. [Pre-mortem risk analysis](PreMortem-Skail-2026-09-02.md) — Tigers, Paper Tigers, Elephants, and launch-blocking mitigations.
6. [Architecture decision](../decisions/0001-skail-native-multi-agent-harness.md) — the major decisions and rejected alternatives.
7. [Active implementation guide](../../tasks/skail-adaptive-orchestration-and-release-plan.md) — dependency-ordered delivery slices and verification gates.
8. [Feature acceptance matrix and follow-on roadmap](FEATURE_PARITY_ROADMAP.md) — tested core scope, demonstrated gaps, and separately scoped future work.
9. [Phase 21 final integrated review](PHASE_21_REVIEW.md) — cross-phase findings, representative traces, remediation ownership, and remaining release boundaries.
10. [Phase 22 candidate and release evidence](../../tasks/skail-adaptive-orchestration-and-release-plan.md#phase-22-handoff) — candidate results and the final release sequence.

## Source baseline

The design was checked against the following current upstream behavior:

- DeepAgents builds an agent harness on LangChain and LangGraph, with planning, filesystems, context management, subagents, memory, backends, permissions, and human-in-the-loop support: <https://docs.langchain.com/oss/python/deepagents/overview>
- Synchronous subagents are invoked through the `task` tool and may be declarative agents or caller-supplied compiled LangGraph runnables: <https://docs.langchain.com/oss/python/deepagents/subagents>
- Async subagents provide background execution, updates, and cancellation, but remain a preview API: <https://docs.langchain.com/oss/python/deepagents/async-subagents>
- Model middleware can replace the concrete model before a provider call: <https://docs.langchain.com/oss/python/langchain/middleware/custom#dynamic-model-selection>
- Filesystem permissions do not protect custom tools or shell execution, so Skail must enforce command policy separately: <https://docs.langchain.com/oss/python/deepagents/permissions>
- LLM Gateway exposes an OpenAI-compatible endpoint at `https://api.llmgateway.io/v1`: <https://docs.llmgateway.io/developers>
- The current DeepAgents repository separates the deployment-oriented `deepagents-cli` from the interactive `deepagents-code`/`dcode` product: <https://github.com/langchain-ai/deepagents/blob/main/AGENTS.md>
- Pi's coding-agent prompt uses a deliberately small direct-work tool set, while its repository requires broad provider behavior tests: <https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/src/core/system-prompt.ts> and <https://github.com/badlogic/pi-mono/blob/main/AGENTS.md>

The implementation baseline used during research was `deepagents==0.7.13`. The implementation must repeat the compatibility spike and pin the exact supported version before writing the runtime adapter.

Phase 1 confirmed that baseline and records the exact supported dependency tuple and adapter-owned limitations in [ADR 0002](../decisions/0002-framework-version-contract.md). Background execution remains experimental under [ADR 0003](../decisions/0003-background-execution.md).

## Document authority

When documents disagree, use this order:

1. A later accepted ADR.
2. `SPEC.md` for product behavior.
3. `ARCHITECTURE.md` for contracts and boundaries.
4. `FEATURES.md` for detailed flows and defaults.
5. The active adaptive-orchestration guide for implementation order only.

`tasks/plan.md`, `tasks/todo.md`, the v0.1.0 remediation plan, and archived planning material are
historical records. Preserve their dates and evidence limits; do not use their checkboxes or claims
as current implementation or release evidence.

Implementation discoveries change the specification or an ADR first. They are not silently encoded only in code.
