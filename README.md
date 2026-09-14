# Skail

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

**Skail Harness** (distribution: `skail-harness`) is a local, budget-aware multi-agent coding
harness. It runs as `skail` without a proxy server, daemon, plugin plane, or hook shim.

## What is implemented

Skail has deterministic, offline coverage for direct and planned execution, typed plan state,
bounded child scheduling, workspace leases and worktree fallback, approvals and project trust,
sessions/recovery, routing and budget records, CLI JSONL, and local inspection. It deliberately
keeps a healthy model assignment fixed for an attempt, permits at most two attempts per delegated
task, and permits at most three concurrent children.

The [feature matrix](docs/skail/FEATURE_PARITY_ROADMAP.md#core-feature-acceptance-matrix) names
the evidence and demonstrated gaps for each user-facing capability. The separate
[follow-on roadmap](docs/skail/FEATURE_PARITY_ROADMAP.md#separate-follow-on-roadmap) identifies
editor, interoperability, richer background, and multimodal work that is not part of this release.

## Quick start

```powershell
git clone https://github.com/plum-sorathorn/Rudder.git -b skail
cd Skail
python -m pip install -e ".[dev]"

# Interactive TUI
skail

# Deterministic offline non-interactive run
skail --print --fake-provider --model fake:fast-model "Summarize this workspace"

# Versioned JSONL event output (`--json` is an alias)
skail --jsonl --fake-provider --model fake:fast-model "Inspect this workspace"
```

External provider use is opt-in and requires configured credentials. The deterministic offline
suite is engineering evidence; it is not a live-provider quality or savings claim.

## How Skail works

Skail is designed for coding work that sometimes benefits from a small, controlled team but should
not pay that overhead for every prompt.

1. A lead either answers directly or records an execution decision for discovery or a typed plan.
2. An admitted plan records nodes, dependencies, acceptance criteria, effect scope, and a durable
   revision before anything runs. Model-authored todo text is never executable state.
3. Ready work receives a concrete model assignment and budget reservation. Independent nodes can
   run concurrently, subject to the hard three-child limit and workspace ownership rules.
4. A successful child result releases dependent work. Failed attempts retain their evidence and
   partial work; Skail can escalate a task only once before returning it to the lead.
5. Sessions preserve task, route, usage, approval, and verification state for inspection or
   recovery. Ambiguous in-flight work fails closed instead of being silently replayed.

This is a local application guarantee, not control over an operating system or an external provider.
The [architecture](docs/skail/ARCHITECTURE.md) explains the durable contracts behind the flow.

## Typical workflows

### Ask directly

Use a direct prompt for inspection, a narrow edit, or a task where coordinating children would add
more cost than value.

```powershell
skail "Explain the failing tests in this repository"
skail --print --fake-provider --model fake:fast-model "Summarize the project layout"
```

### Bound a run

Use routing, budget, delegation, and workspace controls when the work needs explicit limits. CLI
values override the corresponding resolved configuration values for that run.

```powershell
skail --budget 2.50 --mode economy --max-agents 2 --workspace worktree `
  "Implement and verify the requested change"
```

`worktree` is an isolation preference, not a promise: unsafe or unavailable Git isolation falls
back to the serialized shared-workspace path. A request to use a worktree never discards existing
user changes.

### Inspect or resume a session

```powershell
skail sessions list
skail sessions show <session-id>
skail sessions export <session-id> --output session.json
skail --resume <session-id>
```

Exports are redacted records intended for local inspection. They are not a guarantee that every
secret present in an independently executed trusted program was observable or removable.

### Integrate with scripts

Use print mode when a caller needs only the final text, or JSONL when it needs versioned lifecycle
events. JSONL includes one terminal event for persisted runs; failures before a run is persisted do
not fabricate one.

```powershell
skail --print --fake-provider --model fake:fast-model "Report the next step"
skail --jsonl --fake-provider --model fake:fast-model "Inspect the current task"
```

## Execution and safety boundaries

- **Direct versus adaptive execution:** simple work can finish directly. A recorded execution
  decision can instead admit a typed plan whose ready nodes dispatch without another lead turn.
- **Workspace modes:** shared writers are serialized. Git worktree isolation is used only when a
  reproducible snapshot is safe; otherwise Skail falls back to the shared single-writer path
  without discarding user changes.
- **Approvals and steering:** destructive, external, privileged, and unknown effects follow the
  execution approval policy. Foreground input is classified as an answer, queued follow-up, or
  cancellation; experimental background steering cannot enlarge permission, budget, depth, or
  write scope.
- **Economics:** route estimates, reservations, actual/estimated usage, and exclusions are durable.
  Automatic strategy promotion remains shadow/experimental until separately authorized live,
  held-out qualification.

See the [architecture](docs/skail/ARCHITECTURE.md), [feature contracts](docs/skail/FEATURES.md),
[CLI contract](docs/skail/CLI.md), and [threat model](docs/skail/THREAT_MODEL.md) for the
normative contracts and their stated limitations.

## Models, providers, and configuration

The built-in fake provider is deterministic and credential-free, making it the default for tests,
examples, and local smoke verification. Skail also has adapter contracts for LLM Gateway, DevPass,
and OpenAI-compatible providers; optional LangChain integrations depend on the corresponding extra
and a provider configuration. `skail auth status` and `skail auth check` report environment
configuration without exposing credential values or contacting a provider.

Skail records a route choice, estimated cost, reservation, and normalized provider usage when that
usage is available. An estimate is not an invoice, and unobserved or synthetic usage is labelled as
such. Automatic routing remains conservative until evidence qualifies a strategy for a workload
class; see [evaluation](docs/skail/EVALUATION.md).

Configuration is layered from user and trusted-project TOML files. Use these commands to discover
the actual paths and effective values on a workstation:

```powershell
skail config path
skail config show
skail models list
skail models show implementer
```

Project-defined configuration and extensions require an explicit trust decision. Trust does not
override filesystem, approval, budget, or global safety boundaries.

## Safety model

Skail treats model output as untrusted input at its filesystem, command, trust, and secret
boundaries. Workspace paths are normalized against the selected root; sensitive paths and
outside-workspace access receive stronger handling. Command policy distinguishes ordinary local
build/test activity from mutations, external effects, privilege requests, destructive effects, and
unknown effects. The latter categories can require approval or be rejected.

These controls reduce risk inside Skail's application paths. They cannot make a trusted repository
or privileged host process safe. Read the [threat model](docs/skail/THREAT_MODEL.md) before using
Skail on sensitive workspaces or with external credentials.

## CLI and inspection

Run `skail --help` for the active parser contract. The supported root flags include `--print`,
`--jsonl`/`--json`, `--continue`, `--resume`, `--no-session`, `--mode`, `--model`,
`--lead-model`, `--agent-model`, `--budget`, `--max-agents`, `--delegation`, `--workspace`,
`--approve-project`, `--deny-project`, and `--fake-provider`.

The supported subcommands are `config`, `sessions`, `auth`, `models`, and `smoke`. `auth check`
reports whether known environment credential variables are present; it does not perform a provider
network request. `skail smoke --fake-provider` is the offline smoke path.

The documented process exit codes are `0` (completed), `1` (failure), `2` (usage), `3` (blocked),
and `4` (cancelled). Full syntax, output framing, subcommand behavior, and removed legacy aliases
are in the [CLI contract](docs/skail/CLI.md).

## Verification and release evidence

```powershell
rtk pytest -q
python -m ruff check src tests scripts evals benchmarks
python -m mypy src\skail
python scripts\smoke.py --fake-provider
python scripts\package_check.py
python scripts\release_check.py
```

The [evaluation record](docs/skail/EVALUATION.md),
[performance record](docs/skail/PERFORMANCE.md), and
[dependency audit](docs/skail/DEPENDENCIES.md) distinguish synthetic/local evidence from release
and live-economics evidence. Engineering release readiness still requires exact-candidate Windows
and Linux evidence. A release tag, publication, provider spend, and remote change each require
separate authorization.

## Repository guide

| Path | Purpose |
| --- | --- |
| `src/skail/` | Runtime, agents, routing, providers, sessions, safety tools, CLI, and TUI. |
| `tests/` | Deterministic unit, contract, integration, end-to-end, and security coverage. |
| `evals/` | Offline evaluation schemas, fixtures, and raw-evidence tooling. |
| `docs/skail/` | Product contracts, architecture, threat model, evaluation, performance, and roadmap. |
| `tasks/skail-adaptive-orchestration-and-release-plan.md` | Active dependency-ordered implementation and release guide. |

For development conventions, see [AGENTS.md](AGENTS.md). Historical plans and legacy source remain
historical/reference material; they are not compatibility surfaces or current release evidence.

## Current limitations

- Live-provider quality, spend reduction, and universal provider behavior have not been qualified.
- Exact-candidate cross-platform release evidence must be generated for the final candidate; a
  passing report from an earlier commit is not transferable.
- Editor integrations, arbitrary third-party extension interoperability, richer background-agent
  interaction, and multimodal workflows are separate future work, not implied by the runtime.
- The application does not run an HTTP proxy, daemon, or generic plugin server.

## License

MIT License. See [LICENSE](LICENSE).
