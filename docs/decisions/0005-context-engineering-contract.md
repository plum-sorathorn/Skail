# ADR 0005: Assemble context deliberately, progressively, and visibly

Status: Accepted
Date: 2026-09-03
Depends on: [ADR 0001](./0001-skail-native-multi-agent-harness.md), [ADR 0002](./0002-framework-version-contract.md)

## Context

Skail is a long-running coding harness with tool loops, durable sessions, model routing, and
delegated tasks. Its useful information can exceed any model's effective attention budget even
when it fits in a nominal context window. Unbounded transcripts, duplicate rules, eager repository
loads, and raw tool output increase cost and can distract or confuse the lead and child agents.

The design already commits to task isolation, bounded tool output, trusted skills/memory, and
session compaction. Those commitments need one explicit contract so that future task graphs,
session recovery, TUI projections, and evaluations make consistent decisions.

Relevant source material:

- Anthropic, [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents): treat context as finite; use minimal high-signal context, just-in-time retrieval, compaction, structured notes, and isolated agents.
- Anthropic, [The new rules of context engineering for Claude 5 generation models](https://claude.com/blog/the-new-rules-of-context-engineering-for-claude-5-generation-models): prefer simple, non-duplicative guidance, expressive interfaces, and progressive disclosure over large upfront prompts.
- LangChain, [Context engineering for agents](https://www.langchain.com/blog/context-engineering-for-agents): organize the lifecycle as write, select, compress, and isolate, then evaluate the effect of policy changes.

These sources guide context quality. They do not grant safety authority to prompts, authorize
automatic memory harvesting, or replace Skail's persisted journal, task assignment, or trust
boundaries.

## Decision

1. Skail will assemble a versioned, inspectable context packet before every lead or child model
   attempt. It records components, source labels/revisions, approximate token cost, selection
   rationale, and any omission, truncation, or compression reason. It records references and
   metadata, never registered secrets or unrestricted raw tool output.
2. The base packet is intentionally small: product/safety guidance, current user intent and explicit
   constraints, selected profile, task success criteria, and required persisted state. Safety is
   enforced by runtime policy; it is not repeated as competing natural-language rules.
3. Workspace code, documentation, skills, memory, previous artifacts, and detailed history load
   progressively through trusted tools. A task receives explicit references and can retrieve
   additional permitted material just in time; Skail never eagerly injects an entire repository or
   lead transcript.
4. Context selection is deterministic at the runtime boundary. Relevance may use task-declared
   paths, current write scope, active failure handoff, and explicit user references. Model-authored
   text cannot expand trust, permissions, budget, or selected context beyond those boundaries.
5. Context writes are deliberate and labelled. Session notes, task handoffs, and compaction summaries
   have an owner, scope, source revision, and retention rule. Skail v1 does not infer or silently
   persist cross-session user memory from conversation content.
6. Under context pressure, Skail preserves current objective, user constraints, task/attempt state,
   assignments, budgets, approvals/questions, changed paths and verification, unresolved errors, and
   references to full artifacts/events. It replaces low-value history and verbose tool output with
   bounded summaries and references; original journal records remain available for recovery/export.
7. Child contexts stay isolated. They receive only their task packet and an evidence-bearing, bounded
   failure handoff. Child completion returns a compact structured result; the lead retrieves full
   artifacts only when needed.
8. Context policy is evaluated as product behavior. Offline evaluation and benchmarks report context
   pressure, selected/compressed/dropped token estimates, artifact retrievals, handoff size,
   completion, cost, and latency. Tuning cannot bypass journal, assignment, safety, or trust.

## Consequences

### Positive

- Context cost and quality become observable rather than hidden inside prompts.
- Long sessions and parallel tasks retain decisive state without accumulating full transcripts.
- Users can inspect why particular instructions or references reached an agent.
- The policy works across providers because it is Skail-owned rather than model-prompt-specific.

### Trade-offs

- Context assembly, packet persistence, and compaction require explicit implementation in Phases 6–8.
- Just-in-time retrieval can add tool turns and latency; task packets may include a small set of
  deterministic high-confidence references when that avoids obvious exploration.
- No semantic/vector retrieval is introduced in v1. If future evaluations show it is necessary, it
  requires a separate proposal addressing trust, privacy, freshness, and index quality.

## Alternatives considered

### Put all rules, history, and repository facts in every prompt

Rejected. It creates duplicated/conflicting instructions, raises cost, and degrades focus while
making stale information hard to identify.

### Let models autonomously write durable user memory

Rejected for v1. It conflicts with Skail's deliberate, inspectable memory definition and expands
the privacy/trust surface without evidence of value.

### Add a RAG/vector database now

Rejected. Existing file navigation, Graphify references, artifacts, task scopes, and evaluation are
the simpler first mechanisms. Indexing is not assumed reliable enough to become an implicit authority.

## Approval effect

This ADR authorizes the context-packet, progressive-disclosure, compaction, and evaluation work
added to Phases 6–8. It does not authorize hosted services, telemetry, automatic semantic memory,
or a change to Skail's safety/trust boundaries.
