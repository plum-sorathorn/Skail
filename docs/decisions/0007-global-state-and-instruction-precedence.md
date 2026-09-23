# ADR 0007: Keep runtime state global and assemble trusted root instructions

Status: Accepted
Date: 2026-09-21
Depends on: [ADR 0001](./0001-skail-native-multi-agent-harness.md), [ADR 0004](./0004-provider-compatibility-contract.md), [ADR 0005](./0005-context-engineering-contract.md), [ADR 0006](./0006-adaptive-execution-and-release-boundaries.md)

## Context

Skail is launched from repositories and isolated worktrees, but approvals, questions, artifacts,
locks, session metadata, configuration, onboarding choices, and credentials are user-owned Skail
state. Creating a second `.skail` directory inside each repository makes state collision-prone and
leaks runtime files into workspaces. Root instructions also need a deterministic, inspectable
precedence rule without allowing prompt text to weaken code-owned safety policy.

## Decision

1. Skail creates exactly one physical `.skail` directory per user: `~/.skail`. Workspace-scoped
   state is below `~/.skail/workspaces/<canonical-workspace-identity>/`; the identity is derived
   from Skail's canonical workspace identity and is never a raw basename or unsanitized path.
   Every resolved state path is validated to remain below the global root.
2. Runtime state includes approvals, questions, project configuration, artifacts, locks, session
   records, onboarding receipts, and migration receipts. Model filesystem tools remain rooted at
   the real workspace and cannot reach the global state directory merely because Skail stores
   artifacts there.
3. Recognized legacy repository-local state may be imported non-destructively and idempotently.
   The source remains unchanged; a migration receipt records source, outcome, and safe digests.
   Conflicting global and legacy data fails visibly rather than overwriting either copy. Rollback is
   recovery by retaining the legacy source and removing only the imported namespaced copy after
   explicit user action.
4. Device-global onboarding stores only versioned non-secret choices: provider, enabled/selected
   models, theme, and schema receipt. Project trust remains a separate workspace decision.
   Credential resolution is explicit environment variable, OS credential store, then interactive
   entry. Interactive credentials may be written only through the OS credential store; if secure
   storage is unavailable, Skail requires an environment credential and never writes plaintext.
5. Context assembly is built-in rules, global `~/.skail/AGENTS.md`, then trusted workspace-root
   `<workspace>/AGENTS.md`. Global and workspace components are source-labelled, size-bounded,
   secret-redacted, content-hashed, and revision-pinned for each in-flight attempt. An
   untrusted workspace file is reported as found-but-ignored. Workspace prompt text cannot widen
   tools, permissions, write scope, budgets, delegation depth, or filesystem boundaries.
6. Actual usage and reservation remain distinct. Provider-authoritative cost wins; otherwise
   measured tokens plus prices frozen on the assignment produce a token-derived estimate. The
   conservative attempt estimate is used only when usage cannot be measured and is labelled as
   such. Missing cost is never encoded as reported zero.

Decision 6's cost precedence was superseded by
[ADR 0008](./0008-in-house-token-cost-ledger.md). The other decisions remain in force.

## Consequences

- Normal operation leaves repositories and temporary worktrees free of Skail-created `.skail`
  directories.
- Users can move within one canonical workspace without creating another state namespace, while
  distinct workspaces remain isolated.
- Existing local state is recoverable and auditable, but migration never silently deletes or
  overwrites user files.
- Root instruction changes are visible in context evidence and cannot become a safety authority.
- Cost projections can show reservation, authoritative actual, token-derived estimate,
  conservative estimate, and unknown as separate values.

## Approval effect

This ADR authorizes the global-state, instruction-precedence, onboarding, and usage-accounting
changes in the usability remediation plan. It does not authorize paid provider validation, release,
publication, repository changes, or deletion of legacy state.
