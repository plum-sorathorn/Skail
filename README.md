<div align="center">

# AutoConduck 0.5.0

**Local, zero-overhead SLM model router + optional deterministic plugin orchestrator for coding assistants.**

[![Python](https://img.shields.io/badge/python-3.11+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://python.org)
[![Fast Path Latency](https://img.shields.io/badge/turn--guard-%3C2ms-brightgreen.svg?style=flat)](https://github.com)
[![SLM Engine](https://img.shields.io/badge/SLM-Qwen%202.5%20Coder%200.5B%20(ONNX%2FGGUF)-purple.svg?style=flat)](https://github.com)
[![LiteLLM](https://img.shields.io/badge/proxy-LiteLLM-orange.svg?style=flat)](https://github.com/BerriAI/litellm)
[![FastAPI](https://img.shields.io/badge/server-FastAPI-009688.svg?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/license-MIT-blue.svg?style=flat)](LICENSE)

[Why AutoConduck?](#why-autoconduck) · [Architecture](#architecture) · [Quick Start](#quick-start) · [Supported Agents](#supported-agents) · [How It Works](#how-it-works-internally) · [TUI Dashboard](#interactive-tui-dashboard) · [CLI Reference](#cli-command-reference) · [Configuration](#configuration-reference) · [Development](#development)

</div>

---

## Why AutoConduck?

Coding agents (**Claude Code**, **OpenCode**, **Pi**, and **Oh My Pi**) frequently send every prompt, from a single-line typo fix, git status check, or docstring lookup to a 20-file architecture migration, to a single expensive frontier model. This incurs massive token spend on routine turns while bottlenecking large multi-step changes without structured selection.

**AutoConduck 0.5.0** is a local, zero-overhead **model router** with an optional deterministic plugin plane:

- **Turn Guard (regex, <2ms, synchronous):** Classifies every turn without I/O or LLM calls. Healthy tool loops stay on `DIRECT_ACTIVE_TIER`; only genuine stagnation (3+ identical consecutive calls or 2+ consecutive errors) triggers a re-classify via the SLM classifier. No replanning.
- **Embedded SLM Classifier (Qwen 2.5 Coder / LFM 2.5 ONNX / GGUF):** Local small model emits a lightweight `TaskClassification` (`task_type` / `confidence` / `complexity_score`) with a 2000 ms circuit-breaker and deterministic fallback. Optional, non-binding signal — never an authority.
- **"Fit-Gate Then Cheapest" 4D Capability Selection:** Filters models against a 4-dimensional capability vector (`reasoning`, `tool_reliability`, `code_quality`, `latency_class`) weighted per task type, then picks the absolute cheapest qualifying model — on **every** classified turn.
- **Per-Turn Confidence Floor + Optional Session Escalation Bias:** Low SLM confidence raises the capability floor (`min(base + 0.15 * (1 - conf), 0.60)`) on every classified turn; an additive session bias (cap 0.75, TTL in turns) can raise it further when deterministic stagnation/escalation fires.
- **Session Guard (`server/session_guard.py`):** Preserves immutable prompt-caching prefixes (turns 0 & 1) across 40+ turns and compacts at the 80% context window ceiling.
- **Plugin Plane (opt-in, deterministic-first):** Daemon-side Python runtime — ledger (SQLite WAL, batched, durable-only events), bias store, salvaged executor proof path, and templated synthesis. Thin per-harness shims observe via `autoconduck hook` and spool file; escalation bias feeds back into the next-turn selection. LLM judgment, when needed, is routed through the router.
- **LanceDB Knowledge & RAG Subsystem:** Embedded vector store with zero-cost 16-dimensional term-hash embeddings retrieves relevant codebase snippets without external API dependencies.
- **Real-Time Reasoning SSE Streamer:** Streams live cognitive deliberations directly to client coding agents using OpenAI `reasoning_content` and Anthropic `thinking_delta` protocols.

---

## Architecture

```text
                    Two-Plane Architecture (Proxy = authority, Plugin = optional)

  Client (Claude Code / OpenCode / Pi / OMP)
                          │
                          ▼
            FastAPI Proxy — Pure Router (always on)
     ┌──────────────────────────────────────────────┐
     │  Turn Guard (regex <2ms, I/O-free)          │
     │    DIRECT_ACTIVE_TIER ──► keep active tier  │
     │    CLEAN turn ─────────► SLM classify        │
     │    STAGNATION (3×identical / 2×errors) ──► re-classify │
     │                     │                        │
     │                     ▼                        │
     │  SLM Classifier (task_type/confidence/       │
     │    complexity_score, 2000ms CB, fallback)    │
     │                     │                        │
     │                     ▼                        │
     │  Fit-Gate-Then-Cheapest Selection            │
     │    filters: enabled → tools → reasoning →    │
     │    context → capability floor → cost         │
     │    floor = base + 0.15*(1-conf) cap 0.60     │
     │           + session_bias (additive, cap 0.75)│
     │    sort by absolute cost ascending → cheapest│
     │    upstream via LiteLLM                      │
     └──────────────────────────────────────────────┘
                          │
                          ▼
                    Upstream Provider

  Plugin Plane (daemon-side, Python — enabled only when plugins.enabled=true)
     ┌──────────────────────────────────────────────┐
     │  Shims (thin, non-blocking, <10ms)          │
     │    Claude Code hooks → autoconduck hook      │
     │    claude <Event> (observe-only, exit 0)     │
     │    Pi / OpenCode: gated stub (inert)         │
     │                     │                        │
     │                     ▼                        │
     │  Spool file → tailer (autoconduck/plugin/    │
     │    spool.py) → POST /plugin/events           │
     │                     │                        │
     │                     ▼                        │
     │  Daemon Runtime (autoconduck/plugin/)        │
     │    ledger (SQLite WAL, batched, durable-only)│
     │    bias (SessionBiasStore, TTL turns)        │
     │    runtime (salvaged executor_loop+tools,    │
     │      deterministic stagnation → bias)         │
     │    synthesis (templated; LLM stub off)       │
     │                     │                        │
     │            escalation ─┘                     │
     │                     ▼                        │
     │  Selection bias (next-turn floor bump,       │
     │    additive, cap 0.75) ──► Proxy selection   │
     └──────────────────────────────────────────────┘
     Control endpoints: /plugin/events, /plugin/contract,
       /plugin/escalate, /plugin/execute — never 5xx;
       no-op when plugins.enabled=false.
```

### Core Architecture Pillars

1. **Turn Guard (`server/turn_guard.py`):** Pure synchronous regex classifier executing in <2ms, I/O-free. Distinguishes clean user turns (→ classify), active healthy tool loops (`DIRECT_ACTIVE_TIER` — client drives its own loop), and genuine stagnation (3+ identical consecutive calls or 2+ consecutive errors → re-classify). No replanning or task graph.
2. **SLM Classifier (`routing/slm_planner.py`):** Local ONNX/GGUF model emitting a lightweight `TaskClassification` (`task_type`, `confidence`, `complexity_score`) with configurable circuit breaker (default 2000 ms) and deterministic fallback. Optional non-binding signal per the Brain Ladder.
3. **Capability Vector Model Selection (`routing/model_pool.py` + `routing/dispatcher.py`):** Multi-dimensional capability scoring (`reasoning`, `tool_reliability`, `code_quality`, `latency_class`) weighted across task types via `TASK_TYPE_WEIGHTS`. Fit-gate then cheapest; per-turn confidence floor `min(base + 0.15*(1-conf), 0.60)` on every classified turn plus optional additive session escalation bias (cap 0.75, TTL in turns).
4. **Plugin Runtime (`autoconduck/plugin/` — Brain Ladder, deterministic-first):** Ledger (SQLite WAL, async bounded queue, batched, durable-only events), bias store (`SessionBiasStore`), salvaged executor proof path (deterministic stagnation 3-identical/2-errors → bias), and templated synthesis (LLM stub off). SLM is never authority for escalation / stagnation / completion / safety; LLM judgment, when needed, is routed through the router (deferred wiring).
5. **Session Guard (`server/session_guard.py`):** Enforces byte-identical prompt prefix immutability across turns for upstream provider cache hits, and compacts non-structural message history at 80% context capacity. Relocated from `orchestrator/` to `server/` in the two-plane transformation.
6. **Knowledge Vector Store (`knowledge/vector_store.py`):** Embedded LanceDB vector index using deterministic 16-dimensional term-hash embeddings for zero-overhead local code symbol retrieval.

---

## Quick Start

### Installation

Install globally via **npm** or directly with **pip**:

```bash
# Global installation via npm
npm install -g autoconduck

# Or Python installation via pip
pip install -r requirements.txt
pip install -e .
```

### Launching

```bash
# 1. Interactive onboarding & TUI dashboard
autoconduck

# 2. Start headless daemon in background
autoconduck start --headless --daemon

# 3. Stop background daemon
autoconduck stop

# 4. Direct agent launch shortcuts
autoconduck start --claude
autoconduck start --opencode
autoconduck start --pi
```

The server listens on `http://127.0.0.1:11434/v1` by default.

---

## Supported Agents

AutoConduck provides automated configuration, shims, and lifecycle hooks for **Claude Code**, **OpenCode**, **Pi**, and **Oh My Pi (OMP)**:

```bash
# Automatically configure and install launcher shims for all agents:
autoconduck install all

# Or install specific agents:
autoconduck install claude opencode pi omp
```

Agent configuration edits are bounded between `# BEGIN AUTOCONDUCK` and `# END AUTOCONDUCK` markers, with automated backups saved to `~/.autoconduck/backups/<agent>/<timestamp>.bak` (retaining the last 5 backups). Running `autoconduck reset` or `autoconduck uninstall` cleanly restores all original configuration files.

### Claude Code

AutoConduck provides an Anthropic-compatible `/v1/messages` translation shim and configures `settings.json`. When `plugins.enabled=true` **and** `plugins.claude_enabled=true`, Claude Code hooks (`PreToolUse` / `PostToolUse` / `Stop`) are installed via marker-bounded edits to `settings.json` and fire `autoconduck hook claude <Event>` (observe-only, exit-0-always, spool file). Disable either flag to remove hooks with no behavioral delta.

```bash
# Launch directly through AutoConduck
autoconduck start --claude

# Or manually configure Claude Code environment:
export ANTHROPIC_BASE_URL="http://127.0.0.1:11434"
export ANTHROPIC_AUTH_TOKEN="autoconduck-local"
export ANTHROPIC_MODEL="autoconduck"
claude
```

### OpenCode

AutoConduck configures `opencode.json` with structured OpenAI-compatible provider endpoints. The OpenCode plugin shim is currently **doc-only stub** — install machinery is present but hooks are inert behind `plugins.opencode_enabled=false` (full implementation deferred).

```json
{
  "provider": {
    "autoconduck": {
      "type": "openai",
      "baseURL": "http://127.0.0.1:11434/v1"
    }
  },
  "model": "autoconduck/autoconduck"
}
```

```bash
# Launch directly through AutoConduck
autoconduck start --opencode
```

### Pi Coding Agent

Pi integration installs a TypeScript extension `<pi_dir>/extensions/autoconduck.ts` using `pi.registerProvider()` and sets `defaultProvider: "autoconduck"` in `settings.json`. The Pi extension is a **gated constant (inert)** behind `plugins.pi_enabled=false`; full shim implementation is deferred.

```bash
# Launch directly through AutoConduck
autoconduck start --pi
```

### Oh My Pi (OMP)

AutoConduck supports Oh My Pi through dedicated link commands and config patching (`~/.omp/agent/models.yml` and `config.yml`). OMP plugin work is deferred.

```bash
# Link Oh My Pi to AutoConduck
autoconduck omp link

# Unlink Oh My Pi
autoconduck omp unlink
```

---

## The Three Pseudo-Models

AutoConduck presents three virtual models to coding agents:

| Pseudo-Model | Selection Behavior | Best For |
| :--- | :--- | :--- |
| **`autoconduck`** | Standard SLA capability fit-gate, selects the **cheapest** qualifying model | Everyday software engineering & mixed workflows |
| **`autoconduck-budget`** | Standard SLA capability fit-gate, selects the **cheapest** qualifying model | Repetitive tasks, small edits, and high-frequency runs |
| **`autoconduck-expensive`** | Standard SLA capability fit-gate, selects the **most expensive / capable** qualifying model | Complex architectural refactoring, deep reasoning, greenfield design |

---

## How It Works Internally

### 1. Turn Guard (`server/turn_guard.py`)

Turn Guard evaluates incoming messages synchronously in <2ms (regex-only, I/O-free):
- **Clean user turn** → SLM classify, then fit-gate selection with per-turn confidence floor.
- **`DIRECT_ACTIVE_TIER`**: Healthy active tool loop → bypasses SLM and routes directly to the active model tier. Healthy loops touching multiple files or turns are never interrupted.
- **Stagnation** (3+ identical consecutive tool calls or 2+ consecutive tool execution errors) → deterministic trigger to **re-classify** via the SLM classifier (no task graph, no replanning, no plan mutation). The SLM signal is non-binding; stagnation judgment itself is deterministic.

### 2. SLM Classification (`routing/slm_planner.py`)

The local Small Language Model (defaulting to Qwen 2.5 Coder 0.5B ONNX) emits a lightweight `TaskClassification`:
- **`task_type`**: One of `chat`, `explain`, `reconnaissance`, `single_edit`, `multi_edit`, `debug`, `refactor`, `full_workflow`, `git_ops`, `routine`, `read_answer`, `knowledge_query`, `research`.
- **`confidence`**: Classification confidence score between `0.0` and `1.0`.
- **`complexity_score`**: Scalar complexity hint in `[0, 1]`.
- The classifier is circuit-breaker guarded (default 2000 ms) with a deterministic fallback that still yields a valid selection. There are no sub-tasks, phases, or task graph topologies.

### 3. "Fit-Gate Then Cheapest" Model Selection (`routing/model_pool.py` + `routing/dispatcher.py`)

AutoConduck matches candidate models using a multi-dimensional capability vector:

$$\text{Dimensions} = (\text{reasoning},\; \text{tool\_reliability},\; \text{code\_quality},\; \text{latency\_class})$$

1. **Task-Specific Weighting:** Dimension weights are assigned based on `task_type` (`TASK_TYPE_WEIGHTS`).
2. **Capability Fit Scoring:** Computes `capability_fit(vector, weights)` as:

$$\text{fit} = \min_{d \in \text{dominant}} (\text{vector}[d]) + 0.1 \times \sum_{d} (w_d \times \text{vector}[d])$$

3. **Confidence Floor Tightening (every classified turn):** Lower classification confidence raises the capability floor:

$$\text{floor} = \min(\text{base} + 0.15 \times (1 - \text{confidence}),\; 0.60)$$

4. **Session Escalation Bias (optional, additive, cap 0.75):** When the plugin runtime fires a deterministic escalation trigger (e.g., consecutive errors), `SessionBiasStore` applies an additive bump to the floor for subsequent turns in that session (TTL in turns, precedence and reset rules as implemented).
5. **Hard Filters:** Filters candidates by active status, tool support, reasoning support, minimum context window, and capability floor.
6. **Opt-In Price Cap:** `CapabilitySLA.max_price_usd_per_mtok` (configured via `selection.path_price_cap_usd_per_mtok`, disabled by default `{}`) sets an optional price ceiling in USD per 1M tokens. If the price cap empties the pool, AutoConduck falls back to the cheapest qualifying model with `fallback_reason = "price_cap_emptied_pool"`.
7. **Cheapest Selection:** Qualifying models are sorted by absolute cost (`P = cost_input + 0.5 * cost_output`) ascending, picking the cheapest model (or most expensive if `autoconduck-expensive`).

### 4. Plugin Plane — Deterministic-First (Brain Ladder)

The plugin plane is **opt-in** (`plugins.enabled=false` by default) and **never on the routing hot path**. Ledger I/O and bias lookups are off the hot path; routing stays sub-ms.

**Brain Ladder (binding):** Every plugin duty has a deterministic baseline; the local SLM is an optional non-binding refinement; the routed LLM handles judgment when needed — via the router.

| Duty | Deterministic baseline (primary) | SLM role | Routed LLM role |
|---|---|---|---|
| Turn classification | Event type, tool/error counts, explicit intent | Optional label refinement (non-binding) | Never required |
| Task contract | Fixed schema from request + harness metadata | Suggest missing fields only | Generate/revise when ambiguous |
| Stagnation judgment | 3-identical / 2-errors thresholds | None by default | Optional diagnosis after trigger |
| Quality / progress | Completion criteria, exit codes, diffs | Summarize evidence only | Semantic evaluation when requested |
| Final-output synthesis | Template from ledger facts | Optional concise wording | Best-effort synthesis (stub off) |
| Escalation decisions | Explicit trigger matrix | Tie-breaker only after ambiguity | Select higher-capability model via router |

**Never SLM-only:** escalation, stagnation detection, success/completion claims, tool safety, contract constraints, factual assertions in final output.

**Data path:** Thin shims → `autoconduck hook claude <Event>` (observe-only, exit-0-always, bounded spool file `~/.autoconduck/run/plugin_spool.jsonl`) → `autoconduck/plugin/spool.py` tailer → `POST /plugin/events` → ledger (SQLite WAL, async bounded queue, batched, durable-only events: task start, escalation, terminal result, errors) / bias / runtime (salvaged `executor_loop` + `tools` proof path, deterministic stagnation → bias) / synthesis (templated, LLM stub off).

**Control surface:**

- `POST /plugin/events` — ingest shim events (never 5xx; `ignored` when disabled or unknown kind)
- `GET /plugin/contract?session=` — JSON task contract (`schema_version`, `execution-authority: plugin-deterministic`)
- `POST /plugin/escalate` — deterministic trigger matrix → session bias update (`floor_bump`, `ttl_turns`; cap 0.75)
- `POST /plugin/execute` — internal executor proof path (gated by `plugins.execute_enabled`)

All plugin endpoints are fail-soft: they never return 5xx and are no-ops when `plugins.enabled=false`.

---

## Interactive TUI Dashboard

AutoConduck includes an interactive terminal UI built with Textual:

```bash
autoconduck
```

### Main Navigation Hub

From the main menu, navigate directly to all major views:

- **Live Routing Stats (`d`):** Real-time routing decisions, latency histograms, token volume, and decision drill-down.
- **Model Catalog (`m`):** Browse curated model presets and token pricing.
- **Configure Integrations (`c`):** Set up providers, API keys, and custom endpoints.
- **Edit Models (`e`):** Customize active models and capability overrides.
- **Check for Updates (`u`):** Check latest version and upgrade in-place.
- **Settings (`s`):** Interactive editor for thresholds, ports, and execution parameters.
- **Launch Agent (`a`):** Pick and launch a configured coding agent.

### Keymap Reference

| Key | Action |
| :---: | :--- |
| `Up` / `Down` | Move selection cursor |
| `Enter` / `Space` | Open / toggle selection |
| `Left` / `Esc` / `b` | Back / step float down |
| `Right` / `+` | Advance / step float up |
| `d` | Open detailed routing & latency drill-down |
| `m` | Open model catalog |
| `c` | Configure integrations & API keys |
| `e` | Edit models |
| `u` | Check for updates & upgrade |
| `s` | Open settings screen |
| `a` | Open launch agent picker |
| `p` | Pause / resume proxy routing |
| `?` | Toggle keymap help |
| `/` | Filter list items |
| `Ctrl+C` | Quit current screen / exit AutoConduck (`Ctrl+Q` disabled) |

---

## CLI Command Reference

| Command | Description | Options & Flags |
| :--- | :--- | :--- |
| `autoconduck` | Launches interactive TUI dashboard | `--version` |
| `autoconduck start` | Starts the AutoConduck proxy server | `--headless`, `--daemon`, `--port <int>`, `--host <str>`, `--claude`, `--opencode`, `--pi`, `--new-terminal` |
| `autoconduck stop` | Stops the running proxy server & supervisor | `--port <int>` |
| `autoconduck install [agents...]` | Configures agents & installs launcher shims | Positional: `claude`, `opencode`, `pi`, `omp`, `all` |
| `autoconduck hook claude <Event>` | Plugin shim hook — observe-only, appends to spool file, **exit-0-always** (never blocks the harness) | Event: `PreToolUse`, `PostToolUse`, `Stop`, etc. |
| `autoconduck omp link` | Links Oh My Pi configuration to AutoConduck | |
| `autoconduck omp unlink` | Reverts Oh My Pi configuration | |
| `autoconduck edit` | Opens TUI directly on model/provider editor | |
| `autoconduck stats` | Displays routing audit telemetry & cost stats | `--json`, `--days <int>`, `--reset`, `--force` |
| `autoconduck update` | Upgrades AutoConduck to the latest release | `--dry-run` |
| `autoconduck reset` | Reverts all agent configurations & cleans shims | `--force` |
| `autoconduck uninstall` | Reverts configs, removes shims, & uninstalls | `--force` |

---

## Configuration Reference

Configuration is stored in `~/.autoconduck/config.yaml` (or `$AUTOCONDUCK_HOME/config.yaml`), and credentials are kept in `~/.autoconduck/auth.yaml` (`0o600` permissions).

```yaml
host: "127.0.0.1"
port: 11434
log_level: "INFO"

selection:
  # SLM Engine Settings
  slm_model_path: "models/qwen2.5-coder-0.5b-instruct-q4.onnx"
  slm_circuit_breaker_timeout_ms: 2000

  # Session Guard & RAG
  session_guard_compaction_ratio: 0.80
  rag_max_tokens: 250
  rag_db_path: "~/.autoconduck/rag_db"

  # Selection & Capability Floor Tunables
  confidence_floor_k: 0.15
  confidence_floor_max: 0.60

  # Price Caps & Spend Guard (USD per 1M tokens)
  path_price_cap_usd_per_mtok: {}
  spend_guard_enabled: true
  spend_guard_max_usd_per_min: 0.20
  spend_guard_window_s: 300

  # Workspace Tools
  executor_enable_tools: true
  executor_max_tool_rounds: 10
  executor_enable_bash: false

plugins:
  enabled: false
  claude_enabled: false
  pi_enabled: false
  opencode_enabled: false
  ledger_retention_days: 30
  escalation_ttl_turns: 10
  escalation_floor_bump: 0.15
  llm_synthesis_enabled: false
  execute_enabled: false
```

> **Removed keys:** 6 dead config keys deleted in the two-plane transformation (tolerated with a startup warning, never a crash). If present in `config.yaml` they emit a warning and are ignored. See `docs/phase-reports/PHASE1A.md` for the exact key names.

### Custom Provider Registration

```yaml
custom_models:
  - provider: openrouter
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY
    enabled: true

model_list:
  - model_name: openrouter/anthropic/claude-3.5-sonnet
    provider: openrouter
  - model_name: openrouter/deepseek/deepseek-chat
    provider: openrouter
```

---

## Audit & Observability

AutoConduck exposes standard operational and proxy endpoints:

- `GET /healthz`: Health check endpoint (`{"status": "ok"}`).
- `GET /v1/models`: OpenAI-compatible active models list.
- `POST /v1/chat/completions`: OpenAI-compatible chat completion proxy (supports SSE `delta.reasoning_content`).
- `POST /v1/messages`: Anthropic-compatible messages proxy (supports SSE `thinking_delta`).
- `POST /v1/messages/count_tokens`: Anthropic token counting endpoint.
- `GET /stats`: Returns live audit telemetry, decision breakdowns, token volume, latency histograms, and explainability metrics (`candidates_considered`, `binding_constraint`, `spend_cap_engaged`, `fallback_reason`).
- `POST /plugin/events`: Plugin event ingestion (shim → spool → daemon). Never 5xx; returns `ignored` when `plugins.enabled=false` or on unknown kind.
- `GET /plugin/contract?session=`: Returns the JSON task contract for a session (`schema_version`, `execution-authority: plugin-deterministic`).
- `POST /plugin/escalate`: Deterministic trigger matrix → session bias update (`floor_bump`, `ttl_turns`). Never 5xx; `rejected` on unknown trigger, `ignored` when disabled.
- `POST /plugin/execute`: Internal executor proof path (gated by `plugins.execute_enabled`). Never 5xx.

> Plugin endpoints are fail-soft by design: they **never return 5xx** and are **no-ops when `plugins.enabled=false`**.

```bash
# View live telemetry in terminal
autoconduck stats

# Export JSON audit telemetry
autoconduck stats --json
```

---

## Development

```bash
# Clone repository and set up environment
git clone https://github.com/plum-sorathorn/AutoConduck.git
cd AutoConduck
pip install -r requirements.txt
pip install -e .

# Run test suite
python -m pytest

# Run smoke tests
python scripts/end_to_end_smoke.py              # mode A: router-only liveness
python scripts/end_to_end_smoke.py --plugin     # mode B: router + plugin plane

# Version bump (syncs pyproject.toml, __init__.py, package.json, docs)
python scripts/bump_version.py --patch

# Update graphify knowledge graph
graphify update .
```

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
