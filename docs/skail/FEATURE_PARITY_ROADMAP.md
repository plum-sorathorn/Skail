# Skail core feature acceptance matrix and follow-on roadmap

Status: Active
Date: 2026-09-13
Authority: [ADR 0006](../decisions/0006-adaptive-execution-and-release-boundaries.md),
[feature contracts](FEATURES.md), and the
[adaptive orchestration and release guide](../../tasks/skail-adaptive-orchestration-and-release-plan.md)

This matrix distinguishes demonstrated application behavior from middleware availability and from
future product parity. “Covered” means deterministic repository tests exercise the listed contract;
it does not mean a live provider, arbitrary extension, or external platform has been qualified.

## Core feature acceptance matrix

| Capability | Current evidence | Demonstrated scope and gap |
| --- | --- | --- |
| Streaming | CLI end-to-end JSONL tests and event-envelope contracts | `--jsonl`/`--json` emits versioned events with one terminal event for persisted runs. Live-provider stream reliability is unqualified. |
| Sessions and resume | Recovery, persistence, export, and CLI tests | Local session state, resume, redacted export, and ambiguous-launch fail-closed recovery are covered. Cross-device sync is not a feature. |
| Approvals | Execution-policy, approval, and security tests | Policy records/uses explicit approvals for scoped effects. No claim is made that an approved trusted command is harmless. |
| Steering | Interrupt, TUI-command, and controller tests | Foreground questions/follow-ups/cancellation are recorded. Background steering is experimental and bounded; it is not general background-agent control. |
| Skills and memory | Trust, profile, context, and contract tests | Built-in/user skill and bounded memory contracts are available under trust policy. No silent semantic harvesting or vector-retrieval parity is claimed. |
| Provider compatibility | Fake, LLM Gateway, DevPass, and OpenAI-compatible contract tests | Listed adapters normalize their supported contract surfaces. Credentials, provider availability, and every LangChain integration remain environment-dependent. |
| Inspection | CLI config/models/sessions tests and TUI projection tests | Local configuration, profiles, session summaries, export, route/budget projections, and event views are covered. This is not an external observability service. |
| Context management | Context-assembly, compaction, redaction, and performance tests | Bounded packets, omissions, artifact references, and durable compaction state are covered. Measured local bounds do not guarantee provider-context quality. |

## Evidence boundaries

The synthetic evaluator, fake provider, smoke command, and offline test suite establish engineering
behavior only. They do not demonstrate real-provider quality, cost savings, universal provider
compatibility, zero leakage, zero UI stutter, or a release on an unrun platform. Exact-candidate
Windows and Linux checks remain release evidence; separately authorized Q1 live, held-out paired
evaluation remains the economic qualification path.

## Separate follow-on roadmap

These items are intentionally outside the v0.1.0 engineering scope. Their presence here is not an
implementation promise or release dependency.

| Follow-on area | Next actionable discovery slice | Boundary |
| --- | --- | --- |
| Editor integration | Define an editor protocol and offline fixture contract before any adapter | No editor process, credential, or filesystem authority is added by default. |
| External tool and extension interoperability | Specify trusted extension manifests and compatibility fixtures | Existing project trust does not establish compatibility with arbitrary external extensions. |
| Background-agent interaction | Evaluate a bounded async interaction protocol with cancellation/recovery fixtures | Experimental steering must retain current permission, budget, depth, and write-scope limits. |
| Multimodal workflows | Define artifact/content contracts and deterministic non-network fixtures | No image, audio, or remote multimodal provider workflow is implied by current text support. |

## Documentation maintenance rule

Active capability claims must link to a tested contract or named evidence. Historical plans and
reports retain their dates and limitations. A later release candidate must regenerate candidate-
specific measurements, packaging checks, dependency resolution, and platform evidence rather than
reusing this document as proof.
