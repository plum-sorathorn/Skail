# Rudder

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

**Rudder Harness** (distribution: `rudder-harness`) is a native, budget-aware multi-agent coding harness for Python 3.12+. It launches directly from the console as `rudder` without proxy servers, daemons, plugin planes, or hook shims.

> **Just prompt; Rudder will orchestrate.**

A capable lead agent completes simple coding tasks directly or delegates bounded work to as many as three concurrent subagents. Every lead run and subagent attempt receives an immutable model assignment before its first provider call. Rudder routes models deterministically according to hard capability floors, task roles, provider health, and budget limits.

---

## 1. Key Invariants

1. **Direct Launch**: No daemon, proxy, OMA, or SLM required. Rudder launches directly as `rudder`.
2. **One Capable Lead**: The lead agent is fully capable of direct exploration, editing, execution, and synthesis; delegation is used for leverage, not ceremony.
3. **Immutable Model Assignments**: A model is selected and bound to an attempt before its first call. Healthy attempts never switch models mid-flight.
4. **Escalate Once**: An attempt that fails due to under-tiering may escalate once to a higher-capability model (+0.15 floor boost). A second failure returns to the lead.
5. **Bounded Concurrency**: Up to three child subagents run concurrently (`max_children=1..3`).
6. **Shared-Workspace Write Leases**: Writers never overlap in a shared workspace.
7. **Budget Accounting**: Distinguishes authoritative actual, estimated actual, reserved, and available balance with hard launch gates.
8. **Enforced Security Boundaries**: Filesystem boundaries, path traversal guards, command execution policies, and secret redaction are enforced in code, never via prompts alone.
9. **Offline by Default**: The entire test and evaluation suite runs 100% offline and credential-free.

---

## 2. Quick Start

### Installation

```bash
# Clone and install in editable mode with development dependencies
git clone https://github.com/plum-sorathorn/Rudder.git -b rudder
cd Rudder
python -m pip install -e ".[dev]"
```

### Basic Usage

```bash
# 1. Interactive Terminal UI (TUI)
rudder

# 2. Interactive with initial prompt
rudder "Refactor utils.py to use pathlib"

# 3. Non-interactive print mode (clean stdout, diagnostics on stderr)
rudder "Run unit tests and fix failures" --print

# 4. Machine-readable JSONL streaming (versioned events + terminal event)
rudder "Analyze repository dependencies" --jsonl

# 5. Enforce budget limit and routing mode
rudder "Write integration tests" --budget 2.50 --mode economy
```

---

## 3. CLI Subcommands

| Command | Description |
|---|---|
| `rudder config` | View layered configuration, precedence, and provenance |
| `rudder sessions list` | List local sessions, status, run counts, and timestamps |
| `rudder sessions export <id>` | Export session transcript, routes, and usage to JSON/Markdown |
| `rudder auth status` | Check configured provider credentials and health |
| `rudder auth login <provider>` | Interactive provider credential configuration |
| `rudder models list` | List available models, capability vectors, and pricing |
| `rudder smoke` | Run local harness verification with fake deterministic models |

---

## 4. Routing Modes & Economics

Rudder provides four deterministic routing policies:

- **`auto` (default)**: Evaluates role floor (`explorer=0.35`, `tester=0.40`, `implementer=0.50`, `reviewer=0.55`, `lead=0.60`) and task risk (`trivial=0.25` up to `high-risk=0.70`), then selects the lowest-cost candidate that meets the floor. Reduces median task costs by **78.7%** compared to fixed quality.
- **`economy`**: Applies a `-0.10` capability floor discount to explore economical smaller models, automatically recovering via one-time escalation if under-tiering is detected.
- **`quality`**: Applies a `+0.15` capability floor boost and ranks candidates by capability fit and tool reliability before cost.
- **`manual`**: Pins execution to an exact provider and model (e.g. `--model openai:gpt-4o`).

---

## 5. Interactive TUI & Slash Commands

When launched in an interactive terminal, Rudder renders a responsive conversation-first TUI:
- **Main Chat Transcript**: Collapsible tool calls, markdown streaming, and persistent interrupt alerts.
- **Agent Rail**: Live status badges (`queued`, `running`, `escalated`, `returned`, `blocked`), elapsed time, and per-agent cost breakdown.
- **Routing & Budget View**: Inspect recorded routing decisions, hard limits, reserved funds, and available balance.
- **Inline Interrupts**: Answer clarifying questions or review command approvals directly in the terminal.

### Supported Slash Commands
- `/help` — Display command help
- `/agents` — List active and completed child tasks
- `/agent <id>` — Focus transcript on specific child task
- `/tasks` — Show current task hierarchy
- `/route [id]` — Inspect model selection rationale and constraints
- `/budget` — Show authoritative actual, estimated, and reserved spend
- `/mode <auto|economy|quality>` — Switch active routing mode
- `/cancel [id]` — Cancel active task or entire instruction run
- `/compact` — Trigger context compaction preserving ADR 0005 invariants
- `/quit` — Exit Rudder

---

## 6. Provider Support Matrix

| Provider | Support Level | Authentication | Streaming Tools |
|---|---|---|---|
| **LLM Gateway** | Native (First-class) | `LLM_GATEWAY_API_KEY` | Supported |
| **DevPass** | Native (First-class) | `DEVPASS_TOKEN` | Supported |
| **OpenAI-Compatible** | Native | `OPENAI_API_KEY` / Base URL | Supported |
| **Anthropic** | LangChain integration | `ANTHROPIC_API_KEY` | Supported |
| **Fake Provider** | Built-in (Deterministic) | None (Offline) | Simulated |

---

## 7. Security & Threat Model

Rudder enforces strict execution boundaries:
- **Virtual Filesystem Boundary**: All file operations are jailed within `workspace.resolve()`. Directory traversals (`../../`), Windows drive escapes, and symlink/junction hops outside the workspace are strictly blocked.
- **Sensitive Paths**: Files matching `.env*`, `id_rsa*`, `*.pem`, `*.key`, and `.git` are prohibited from entering model context.
- **Command Policy**: Destructive commands (`rm`, `del`, `format`, `sudo`, `git clean -fdx`, `git reset --hard`) are hard-rejected. Shell interpreters and external network commands require interactive human approval.
- **Secret Redaction**: Environment credentials and tokens are scrubbed from logs, context packets, and session exports via `SecretRedactor`.

---

## 8. Verification & Release Testing

```powershell
# Run full offline test suite (430+ tests)
rtk pytest -q

# Run static analysis and linting
python -m ruff check src tests scripts evals
python -m mypy src\rudder

# Run deterministic routing & orchestration evaluation suite (52 fixtures)
python scripts\eval_routing.py --fixtures evals\manifest.toml

# Run release packaging check
python scripts\release_check.py
```

---

## 9. License

MIT License. See [LICENSE](LICENSE) for details.
