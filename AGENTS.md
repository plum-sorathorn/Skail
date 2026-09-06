# Rudder — AGENTS.md

Rudder Harness is a native, budget-aware multi-agent coding harness for Python 3.12+. The console command
is `rudder`; the distribution name is `rudder-harness`.

## Commands

- Install: `python -m pip install -e ".[dev]"`
- Test: `rtk pytest`
- Focused tests: `rtk pytest tests\unit -q`
- Lint: `python -m ruff check src tests scripts`
- Type check: `python -m mypy src\rudder`
- Smoke: `python scripts\smoke.py --fake-provider`
- Build: `python -m build`
- Graph update: `graphify update .`

## Product invariants

- Rudder launches the harness directly; no proxy, daemon, plugin plane, hooks, shims, OMA, or SLM.
- The lead is capable of direct work and delegates only for leverage.
- Delegation uses DeepAgents' standard `task` surface and Rudder-owned compiled lifecycle graphs.
- Every lead run and child attempt has a persisted model assignment before its first call.
- A healthy attempt keeps one model. A delegated task has at most two attempts.
- Child concurrency is configurable from one to three, with three as the hard maximum.
- Shell access is write-capable. Shared-workspace writers, including the lead, never overlap.
- Budgets distinguish authoritative actual, estimated actual, reserved, and available amounts.
- Filesystem, shell, tool, trust, and approval boundaries are enforced in code, never only prompts.
- LangGraph checkpoints and Rudder's journal are separate and reconciled explicitly.
- `legacy/autoconduck/` is inert. Runtime code under `src/rudder/` must never import or address it.
- Unknown models are manually selectable but excluded from automatic routing without evidence.

## Workflow

Read the applicable accepted ADR, `docs/rudder/SPEC.md`, and relevant architecture/feature sections
before implementation. Query Graphify before unfamiliar exploration. Work through `tasks/plan.md`
in dependency order, use tests before behavior changes, run focused and affected suites, then run
`graphify update .` and review the complete diff before each phase commit.

Use `apply_patch` for source edits. Preserve user changes and keep changes phase-scoped. Prefix Git,
build, test, and high-output inspection commands with `rtk`, falling back to the raw command only if
RTK cannot spawn it. Use PowerShell syntax on Windows.

The default suite must remain offline and credential-free. Never place secrets in prompts, events,
logs, exceptions, fixtures, exports, or checkpoints. Live-provider validation is opt-in and must not
be represented as completed without real credentials and results.
