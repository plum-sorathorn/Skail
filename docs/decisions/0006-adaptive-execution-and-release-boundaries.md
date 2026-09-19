# ADR 0006: Adopt adaptive execution plans and evidence-gated release boundaries

Status: Accepted
Date: 2026-09-05
Depends on: [ADR 0001](./0001-skail-native-multi-agent-harness.md), [ADR 0005](./0005-context-engineering-contract.md)
Supersedes: ADR 0001 decision 3 and its rejection of precompiled task DAGs, only as described below

## Context

ADR 0001 established a capable lead, DeepAgents' standard `task` surface, task-bound model
assignments, bounded concurrency, and one escalation. The first runtime implemented those contracts,
but it makes the lead choose each delegated batch. That adds lead calls between known dependent tasks
and cannot safely express discovery checkpoints, revisions, isolated writers, or verified
integration as durable execution state.

Skail also needs two different evidence boundaries. Deterministic offline fixtures can establish
engineering readiness, but they cannot prove that a cheaper model strategy preserves real coding
quality or reduces provider spend. Release mechanics must not turn incomplete economic evidence into
a product claim or treat a tag as permission to rename a repository or remote.

## Decision

1. The first necessary lead response may finish directly or record a typed `ExecutionDecision` for
   direct, discovery, or planned execution. A final answer needs no execution decision. Runtime
   middleware requires a decision before operational tool calls, except for a scoped user question
   needed to obtain intent or authority.
2. Skail interprets a versioned `ExecutionPlan` with a fixed coordinator. Plans contain finite,
   typed nodes, dependencies, acceptance criteria, effect and resource scopes, and explicit decision
   checkpoints. Model-authored code and todo prose are never executable plans.
3. DeepAgents' standard `task` tool remains compatible. A `task` call becomes one validated plan
   task through the same admission, assignment, budget, execution, result, and event services. It is
   not a second scheduler.
4. The runtime persists plan identity, schema version, policy version, revision, node identity, legal
   transitions, and revision evidence before dispatch. Skail owns persistent opaque IDs; model
   output uses plan-local names. Completed node identities remain stable across revisions.
5. Plan, node, revision, route, workspace, change-set, and verification records are Skail domain
   contracts. Their schema versions are owned by the domain modules that serialize them. Journal
   migrations are owned by `sessions/migrations.py`; event envelope and payload evolution are owned
   by `domain/events.py`. Readers reject unsupported future versions. Migrations preserve prior
   records and never reinterpret historical evidence in place.
6. A healthy lead run and child attempt keep their persisted model assignment. Replanning, waiting,
   resume, or workspace integration does not reroute active work. Provider fallback and the single
   task escalation create explicit new assignments under the existing attempt rules.
7. Shared-workspace writers remain serialized. Isolated writer work starts from a reproducible
   `WorkspaceSnapshot`, returns a content-addressed `ChangeSet`, and is integrated by one serialized
   owner after conflict and verification checks. Unsafe or unavailable isolation falls back to the
   shared single-writer path without discarding user changes.
8. Automatic strategy promotion requires an approved paired-evaluation policy and qualifying
   outcome evidence for the relevant workload class. Sparse, stale, or unsupported evidence keeps
   `auto` on the recorded conservative baseline and exposes the reason. Planner confidence and
   descriptive local statistics are not quality evidence.
9. Engineering-ready v0.1.0 requires all numbered offline phases, raw-evidence checks, and exact-
   candidate Windows/Linux verification. Economic qualification is a separate track requiring
   explicit provider-spend authorization and held-out live evidence. Engineering readiness does not
   imply a broad savings claim.
10. Creating or accepting this ADR authorizes the numbered implementation plan and its local phase
    commits. It does not authorize paid evaluation, provider access, publication, pushing, tagging,
    remote or repository renaming, or legacy deletion. A release tag requires separate explicit
    authorization and exact-commit platform evidence. A tag never authorizes a remote rename.

## Alternatives considered

### Keep lead-selected task batches as the only scheduler input

Rejected because known dependencies would repeatedly wake the lead and durable recovery would have
to infer execution intent from conversation history.

### Generate and execute a static graph for every prompt

Rejected because simple work should stay direct and repository evidence can invalidate later work.
Discovery checkpoints and versioned revisions provide bounded adaptation without executing generated
code.

### Promote routes from local descriptive outcomes

Rejected because small, selected samples cannot establish quality parity. Local observations may
inform shadow estimates and drift detection, but promotion requires the approved paired protocol.

### Make isolated workspaces the only writer mode

Rejected because non-Git, dirty, or conflicting workspaces cannot always be isolated safely. The
serialized shared-workspace path remains the correctness fallback.

## Consequences

- Direct work remains cheap, while accepted plans can release ready nodes without a lead call after
  every ordinary completion; interrupt, block, and failure exits are not ordinary completions —
  admitted-but-unlaunched nodes are reconciled to BLOCKED there (emitting `plan.node_blocked`), and
  only persisted READY nodes are re-admitted on resume.
- Plan admission, revisions, dispatch, recovery, routing, projections, and evaluation share durable
  versioned records.
- The compatibility `task` surface and existing two-attempt lifecycle remain valid during migration.
- Isolated writing requires snapshot and integration contracts before concurrent writers can ship.
- Novel economic strategies remain shadow or experimental until real outcome evidence qualifies
  them; offline completion can establish engineering readiness only.
- ADR 0001 remains authoritative for the native harness boundary, capable lead, task-bound model
  stickiness, concurrency maximum, and retry limit. Its single-task-surface implementation and
  blanket rejection of precompiled DAGs are superseded only by this adaptive-plan decision.

## Approval effect

This ADR resolves the architecture permission needed by the numbered adaptive-orchestration plan.
Each phase remains subject to its dependency, verification, and phase-commit contract. External
release and qualification actions retain their separate authorization requirements.
