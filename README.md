<p align="center"><strong>SKAIL</strong></p>

```text
Twin sail mark (v0.1.0, monochrome, never animated):
      /\|\
     /  | \
    /___|__\
   /____|___\
   \________/
    S K A I L
```


<p align="center">
  A Python multi-agent coding harness built on DeepAgents and LangGraph.
</p>

<p align="center">
  <a href="https://github.com/plum-sorathorn/Skail/actions/workflows/ci.yml"><img src="https://github.com/plum-sorathorn/Skail/actions/workflows/ci.yml/badge.svg?branch=skail" alt="CI"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.12%2B-blue.svg?style=flat-square" alt="Python 3.12+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square" alt="License: MIT"></a>
  <a href="https://github.com/langchain-ai/deepagents"><img src="https://img.shields.io/badge/DeepAgents-multi--agent-blue.svg?style=flat-square" alt="DeepAgents"></a>
  <a href="https://github.com/langchain-ai/langgraph"><img src="https://img.shields.io/badge/LangGraph-orchestration-blue.svg?style=flat-square" alt="LangGraph"></a>
  <a href="https://github.com/langchain-ai/langchain"><img src="https://img.shields.io/badge/LangChain-framework-blue.svg?style=flat-square" alt="LangChain"></a>
  <a href="https://github.com/Textualize/textual"><img src="https://img.shields.io/badge/Textual-TUI-blue.svg?style=flat-square" alt="Textual"></a>
  <a href="https://github.com/pydantic/pydantic"><img src="https://img.shields.io/badge/Pydantic-validation-blue.svg?style=flat-square" alt="Pydantic"></a>
  <a href="https://www.sqlite.org/"><img src="https://img.shields.io/badge/SQLite-storage-blue.svg?style=flat-square" alt="SQLite"></a>
</p>

# Skail

Skail is an agentic AI and multi-agent coding harness built on
[DeepAgents](https://github.com/langchain-ai/deepagents). It uses
**[LangGraph](https://github.com/langchain-ai/langgraph)** for durable,
stateful orchestration—including direct execution, dependency-aware task graphs, checkpointing,
human-in-the-loop interrupts, and resumable sessions—and
**[LangChain](https://github.com/langchain-ai/langchain)** abstractions for LLM
provider integration, model invocation, structured output, and tool calling.

Its systems stack combines **[Pydantic](https://github.com/pydantic/pydantic)** contracts,
**[SQLite](https://www.sqlite.org/)** persistence, asynchronous Python
concurrency, Git worktree isolation, budget-aware model routing, provider usage accounting,
context engineering, and a **[Textual](https://github.com/Textualize/textual)** terminal UI. Skail coordinates specialized subagents while
enforcing task dependencies, bounded retries, verification evidence, permissions, and Skail-owned
budget gates in deterministic runtime code. Skail's budget is an application-level control;
provider-side usage and account controls determine billed spend.

Skail runs locally without a proxy server or daemon and exposes an interactive TUI, a conventional
CLI, and versioned JSONL event streaming for automation. The Python distribution is
`skail-harness`; the console command is `skail`.

## Why Skail?

Building a coding agent is straightforward. Making it dependable across planning, parallel work,
cost control, recovery, and verification is the harder part. Skail provides those runtime
guarantees out of the box:

- **Adaptive execution** — simple requests stay direct; complex work can use discovery checkpoints
  or a typed, dependency-aware plan.
- **Task-bound model routing** — each lead run and child attempt receives a durable provider/model
  assignment based on capability, role, evidence, health, and budget.
- **Budget control** — reservations gate work against Skail's estimates, usage is tracked once, and
  uncertain accounting blocks unsafe replay. Provider-side usage remains the billing authority.
- **Safe parallel work** — up to three children can run concurrently; writers use reproducible Git
  worktrees when available and serialized integration when changes return.
- **Human checkpoints** — project trust, tool approvals, questions, steering, and cancellation are
  enforced by runtime policy rather than prompt compliance.
- **Durable sessions** — SQLite-backed plans, assignments, events, approvals, usage, checkpoints,
  compaction, recovery, and exports survive interruption.
- **Context engineering** — bounded task packets, skills, memory, artifact references, output
  offloading, and compaction keep model context focused.
- **Terminal-native interfaces** — work interactively in the TUI, capture only the final answer, or
  consume a stable JSONL event stream from scripts.

The control plane runs locally with SQLite state and direct provider adapters; no service
infrastructure is required.

## Release status

Skail is version 0.1.0 and is classified as Alpha. Release evidence is tracked in the
[evaluation](docs/skail/EVALUATION.md) and [performance](docs/skail/PERFORMANCE.md) documents.
Exact-final-commit Windows/Linux verification is pending. Offline tests do not establish live-provider
quality or savings, and provider-side usage is required to establish billed spend.

## Getting started

### Quickstart from source

```powershell
git clone https://github.com/plum-sorathorn/Skail -b skail
cd Skail
python -m pip install -e ".[dev]"

# Verify the installation without credentials
python scripts\smoke.py
```

`skail auth check` checks credential availability without contacting a provider. `skail models list`
shows configured models and the last validated local catalog snapshot. Launching `skail` performs
startup setup and opens the TUI:

```powershell
skail auth check
skail models list
skail
```

Useful bounded invocations:

```powershell
# Cap spend and parallelism while preferring isolated writers
skail --budget 2.50 --mode economy --max-agents 2 --workspace worktree `
  "Implement and verify this change"

# Emit versioned events for automation
skail --jsonl --budget 1.00 "Inspect the repository and report findings"

# Resume durable work
skail sessions list
skail --resume <session-id>
```

See the [CLI contract](docs/skail/CLI.md) for every flag, subcommand, output mode, and exit code.

### Clean uninstall

The uninstall script removes Skail's OS-keyring credential entries, the complete `~/.skail` state
root, and the installed `skail-harness` package. Pass explicit old workspace roots only when you also
want their legacy local `.skail` directories removed:

```powershell
.\scripts\uninstall_skail.ps1 -Yes
.\scripts\uninstall_skail.ps1 -Yes -LegacyWorkspaceRoots C:\path\to\old-workspace
```

The operation is destructive. It does not scan arbitrary drives for unknown historical folders.

### Interactive TUI

Launch `skail` in a TTY to mount the cockpit immediately; provider and model
setup runs in a background worker after the shell is visible. First run walks
a mount-first 5-step onboarding ladder:

1. Welcome (Twin sail mark + overview)
2. Provider (LLM Gateway / OpenAI / Anthropic)
3. Trust (trust this exact folder, or restricted mode)
4. Theme (Dark / Light / System / Pistachio Night / Pistachio Paper / Mint Porcelain with live preview)
5. Ready (receipt with the exact `skail -r <session-id>` resume command)

```powershell
# Normal interactive start after provider setup
skail auth check
skail models list
skail
```

Keybindings: `Shift+Tab` cycles the Agents, Plan, Route, and Budget panels while
keeping the composer focused, `Alt+P` opens the model picker (future attempts
only), and `/mode` changes routing mode. The transcript and side panels are
display-only; the removed Ctrl+A/B/P/R bindings cannot steal focus. `Esc` goes
back one step and never approves (pending approvals stay pending), `Ctrl+O`
opens the transcript overlay, `Ctrl+T` opens Mission Control (child agents),
`Ctrl+Shift+T` focuses chat/composer, and `?` opens the shortcuts pane
(type-to-filter). While a run is active, `Ctrl+Enter` queues a follow-up; take
back the newest queued prompt from the queue view. `skail -r <session-id>`
resumes any durable session.
Headless use is unchanged: `skail -p "<prompt>"` prints the final answer,
`skail --jsonl` streams versioned events, `-c` continues, `-r` resumes, and
`--no-session` runs without persistence.

## Architecture

```mermaid
flowchart LR
    User[Developer] --> Surface[TUI · Print · JSONL]
    Surface --> Controller[RunController]
    Controller --> Lead[Capable lead]
    Lead --> Direct[Direct execution]
    Lead --> Plan[Typed adaptive plan]
    Plan --> Scheduler[Bounded scheduler]
    Scheduler --> Workers[Up to 3 children]
    Direct --> Tools[Policy-enforced tools]
    Workers --> Tools
    Workers --> Workspaces[Shared or isolated workspaces]
    Controller --> Budget[Budget and assignment ledger]
    Controller --> Journal[(SQLite journal)]
    Journal --> Resume[Resume · replay · export]
```

| Execution path | Best for | Coordination | Workspace behavior |
| --- | --- | --- | --- |
| Direct | Small edits, inspection, and focused commands | The lead works in its normal tool loop | Shared workspace with policy-enforced writes |
| Discovery | Work whose shape depends on repository evidence | Read-only frontier, checkpoint, then evidence-backed revision | Read-only discovery before later admitted work |
| Planned | Multi-step or parallel work with known dependencies | Durable nodes release when verified prerequisites complete | Isolated worktrees when safe; serialized fallback and integration |

> **Skail is a local application boundary.** It runs with the invoking user's operating-system
> permissions. Workspace confinement, trust, approvals, redaction, and budgets govern actions that
> pass through Skail; trusted programs and privileged host processes remain the user's
> responsibility.

## Documentation

| Section | What you'll find |
| --- | --- |
| [Product specification](docs/skail/SPEC.md) | Product behavior, users, commands, configuration, and acceptance criteria |
| [Architecture](docs/skail/ARCHITECTURE.md) | Runtime topology, graph composition, persistence, routing, budgets, and safety boundaries |
| [Feature contracts](docs/skail/FEATURES.md) | Exact behavior for agents, tools, sessions, approvals, context, and terminal interfaces |
| [CLI reference](docs/skail/CLI.md) | Invocation syntax, subcommands, JSONL framing, and process exit codes |
| [Threat model](docs/skail/THREAT_MODEL.md) | Trust boundaries, mitigations, and residual host-level risks |
| [Evaluation](docs/skail/EVALUATION.md) | Independent fixtures, raw evidence, routing gates, and qualification rules |
| [Performance](docs/skail/PERFORMANCE.md) | Reproducible runtime, rendering, persistence, and context measurements |
| [Changelog](CHANGELOG.md) | Notable v0.1.0 fixes, performance evidence, and release status |
| [Dependencies](docs/skail/DEPENDENCIES.md) | Pinned runtime dependencies, provider extras, and transitive tooling |

## Benchmarks

Skail includes reproducible local benchmarks ([bench_runner](benchmarks/bench_runner.py)) and an independently scored offline evaluation suite.
Run them against the same source and environment you want to measure:

```powershell
python benchmarks\bench_runner.py --json --repetitions 5
python scripts\eval_routing.py --paired-runtime --output $env:TEMP\skail-eval.json
python scripts\release_check.py
```

The suite measures orchestration, persistence, context, rendering, workspace, and paired execution
behavior from raw records. Deterministic scripted evidence verifies the engineering contract;
it is not a live-provider quality or savings claim.

## Contributing

Issues, pull requests, tests, and documentation improvements are welcome. Read
[AGENTS.md](AGENTS.md) for the repository conventions and keep changes focused, typed, offline by
default, and backed by the appropriate tests.

```powershell
rtk pytest -q
python -m ruff check src tests scripts evals benchmarks
python -m mypy src\skail
python scripts\smoke.py
python scripts\package_check.py
```

Report bugs or propose changes through [GitHub Issues](https://github.com/plum-sorathorn/Skail/issues).
For the project's security boundaries, start with the [threat model](docs/skail/THREAT_MODEL.md).

## Project links

- [GitHub repository](https://github.com/plum-sorathorn/Skail)
- [Issue tracker](https://github.com/plum-sorathorn/Skail/issues)
- [Documentation index](docs/skail/README.md)

## License

Skail is released under the [MIT License](LICENSE).
