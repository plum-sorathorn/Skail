# Skail documentation

These documents are the maintained product and engineering contracts for Skail.

Read them in this order:

1. [Product specification](SPEC.md) — user-visible behavior and acceptance criteria.
2. [Technical architecture](ARCHITECTURE.md) — runtime topology, state, routing, and boundaries.
3. [Feature contracts](FEATURES.md) — detailed orchestration, tools, sessions, and TUI behavior.
4. [CLI reference](CLI.md) — commands, output modes, state paths, and exit codes.
5. [Threat model](THREAT_MODEL.md) — trust boundaries and security controls.
6. [Evaluation](EVALUATION.md) and [performance](PERFORMANCE.md) — reproducible evidence rules.
7. [Dependencies](DEPENDENCIES.md) — supported framework and provider integrations.

Accepted decisions are retained under [`docs/decisions`](../decisions/). When documents disagree,
a later accepted ADR takes precedence, followed by `SPEC.md`, `ARCHITECTURE.md`, and `FEATURES.md`.
