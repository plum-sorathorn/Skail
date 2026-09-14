<div align="center">

# Skail

**Local, zero-overhead SLM model router + optional deterministic plugin orchestrator for coding agents.**

[![Version](https://img.shields.io/badge/version-0.5.2-blue.svg?style=flat)](pyproject.toml)
[![Python](https://img.shields.io/badge/python-3.11+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://python.org)
[![Fast Path Latency](https://img.shields.io/badge/turn--guard-%3C2ms-brightgreen.svg?style=flat)](skail/server/turn_guard.py)
[![SLM Engine](https://img.shields.io/badge/SLM-Qwen%202.5%20Coder%200.5B%20(ONNX%2FGGUF)-purple.svg?style=flat)](https://github.com/plum-sorathorn/Skail)
[![LiteLLM](https://img.shields.io/badge/proxy-LiteLLM-orange.svg?style=flat)](https://github.com/BerriAI/litellm)
[![FastAPI](https://img.shields.io/badge/server-FastAPI-009688.svg?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/license-MIT-blue.svg?style=flat)](LICENSE)

[Why Skail?](#why-skail) • [Architecture](#architecture) • [Quick Start](#quick-start) • [Supported Agents](#supported-agents) • [The Three Pseudo-Models](#the-three-pseudo-models) • [How It Works Internally](#how-it-works-internally) • [Open-Multi-Agent (OMA) Sidecar](#open-multi-agent-oma-sidecar) • [Interactive TUI Dashboard](#interactive-tui-dashboard) • [CLI Command Reference](#cli-command-reference) • [Configuration Reference](#configuration-reference) • [Audit & Observability](#audit--observability) • [Development](#development) • [License](#license)

</div>

---

## Why Skail?

Coding agents (**Claude Code**, **OpenCode**, **Pi**, and **Oh My Pi**) frequently send every prompt—from a single-line typo fix, git status check, or docstring lookup to a 20-file architecture migration—to a single expensive frontier model. This incurs massive token spend on routine turns while bottlenecking large multi-step changes without structured selection.

**Skail 0.5.2** is a local, zero-overhead **model router** with an optional deterministic plugin plane:

- **Turn Guard (Regex, <2ms, Synchronous):** Evaluates every turn without I/O or LLM calls. Healthy tool loops stay on `DIRECT_ACTIVE_TIER` (inheriting session capability floor); only genuine stagnation (3+ identical consecutive calls or 2+ consecutive errors) triggers an immediate floor bias escalation and SLM re-classification. No replanning, no task graphs.
- **Embedded SLM Classifier (Qwen 2.5 Coder / LFM 2.5 ONNX / GGUF):** Local small model emits a lightweight `TaskClassification` (`task_type`, `confidence`, `complexity_score`) with a 2000 ms circuit-breaker and deterministic fallback. Optional, non-binding signal—never an authority.
- **Proxy Complexity Gating & OMA Sidecar Intercept:** High-complexity tasks (`complexity >= 0.75` or `full_workflow`/`refactor`) at top-level depth (`request_depth == 0` and `x-oma-sidecar != 1`) are automatically intercepted by `server_router.py` and delegated to the OMA Node.js sidecar runner (`skail/plugin/oma_sidecar/runner.js`) when `plugins.enabled` and `plugins.oma_enabled`. Features `x-oma-sidecar: 1` recursion protection and fail-soft degrade to direct fast-path LLM dispatch.
- **Capability Floor Routing (4D Capability Vectors):** Filters models against a 4-dimensional capability vector (`reasoning`, `tool_reliability`, `code_quality`, `latency_class`) weighted per task type, with capability tiebreaker sorting on equal/zero-cost candidates, picking the absolute cheapest qualifying model on **every** classified turn.
- **Dynamic Task Base Floors + Tool Loop Floor Inheritance:** Base floors scale dynamically by task type and complexity (`debug: 0.35`, `refactor: 0.40`, `full_workflow: 0.45`), tightened by low confidence ($\min(\text{base} + 0.15 \times (1 - \text{conf}), 0.60)$) and inherited across tool loops. Additive session bias (+0.15, cap 0.75, TTL 10 turns) elevates selection upon stagnation.
- **Automated Multi-Provider Preset Catalog (1,000+ Models):** `python scripts/sync_all_presets.py` synchronizes 1,024+ models across 11 providers (`openai`, `anthropic`, `google`, `mistral`, `deepseek`, `groq`, `openrouter`, `together`, `xai`, `devpass`, `llmgateway`) from live upstream endpoints directly into code and docs.
- **Session Guard (`server/session_guard.py`):** Preserves immutable prompt-caching prefixes (turns 0 & 1) across 40+ turns and compacts at the 80% context window ceiling.
- **Plugin Plane (Opt-in, Deterministic-First):** Daemon-side Python runtime—ledger (SQLite WAL, batched, durable-only events), bias store, salvaged executor proof path, and templated synthesis. Thin per-harness shims observe via `skail hook` and a bounded spool file.
- **LanceDB Knowledge & RAG Subsystem:** Embedded vector store with zero-cost 16-dimensional term-hash embeddings retrieves relevant codebase snippets without external API dependencies.
- **Real-Time Reasoning SSE Streamer:** Streams live cognitive deliberations directly to client coding agents using OpenAI `reasoning_content` and Anthropic `thinking_delta` protocols.

---

## Architecture

Skail operates under a **Two-Plane Architecture** where the Fast-Path Proxy is the primary authority and the Plugin Plane is an optional, non-blocking telemetry and escalation layer:

```text
                    Two-Plane Architecture (Proxy = authority, Plugin = optional)

  Client Coding Agents (Claude Code / OpenCode / Pi / OMP)
                           │
                           ▼
             FastAPI Proxy — Pure Router (Always On)
      ┌─────────────────────────────────────────────────────────┐
      │  Turn Guard (Regex <2ms, I/O-free)                      │
      │    DIRECT_ACTIVE_TIER ──► keep active tier (no SLM)     │
      │    CLEAN user turn    ──► SLM classify                  │
      │    STAGNATION (3×identical / 2×errors) ──► re-classify  │
      │                     │                                   │
      │                     ▼                                   │
      │  SLM Classifier (task_type/confidence/complexity_score, │
      │    2000ms circuit breaker, deterministic fallback)      │
      │                     │                                   │
      │                     ▼                                   │
      │  Proxy Complexity Gating (oma_enabled=true)             │
      │    High complexity (score ≥ 0.75 or full_workflow)      │
      │    depth=0 & x-oma-sidecar!=1 ──► OMA Node.js Sidecar   │
      │    (recursion protected; fail-soft fallback to router)  │
      │                     │                                   │
      │                     ▼                                   │
      │  Capability Floor 4D Model Routing                      │
      │    filters: enabled → tools → reasoning → context →     │
      │             capability floor → optional price cap       │
      │    floor = base + 0.15*(1-conf) [cap 0.60]              │
      │           + session_bias [additive, cap 0.75]           │
      │    sort: absolute cost ascending → cheapest qualifying  │
      │    upstream dispatch via LiteLLM                        │
      └─────────────────────────────────────────────────────────┘
                           │
                           ▼
                  Upstream Model Provider

  Plugin Plane (Daemon-side, Python/Node.js — Active when plugins.enabled=true)
      ┌─────────────────────────────────────────────────────────┐
      │  OMA Node.js Sidecar (skail/plugin/oma_sidecar/)  │
      │    runner.js + tools.js (workspace tool suite & runner) │
      │                     │                                   │
      │  Shims (Thin, Non-blocking, <10ms overhead)             │
      │    Claude Code hooks → POST /plugin/events (HTTP, 10ms) │
      │    fallback: skail hook claude <Event> (spool)    │
      │    Pi / OpenCode: gated stubs (inert)                   │
      │                     │                                   │
      │                     ▼                                   │
      │  Spool File → Tailer (skail/plugin/spool.py)      │
      │    ──► POST /plugin/events                              │
      │                     │                                   │
      │                     ▼                                   │
      │  Daemon Runtime (skail/plugin/)                   │
      │    ledger (SQLite WAL, batched, durable-only events)    │
      │    bias (SessionBiasStore, TTL turns, cap 0.75)         │
      │    runtime (start_task OMA sidecar launcher & proof)    │
      │    synthesis (templated; LLM stub off)                  │
      │                     │                                   │
      │            escalation ─┘                                │
      │                     ▼                                   │
      │  Selection Bias (Next-turn floor bump) ──► Proxy        │
      └─────────────────────────────────────────────────────────┘
      Control endpoints: /plugin/events, /plugin/contract,
        /plugin/escalate, /plugin/execute (fail-soft, never 5xx).
```

### Core Architecture Pillars

1. **Turn Guard (`server/turn_guard.py`):** Pure synchronous regex classifier executing in <2ms, I/O-free. Distinguishes clean user turns (→ classify), active healthy tool loops (`DIRECT_ACTIVE_TIER` — client drives its own loop), and genuine stagnation (3+ identical consecutive calls or 2+ consecutive errors → re-classify). No replanning or task graph recompilation.
2. **SLM Classifier (`routing/slm_planner.py`):** Local ONNX/GGUF model emitting a lightweight `TaskClassification` (`task_type`, `confidence`, `complexity_score`) with a configurable circuit breaker (default 2000 ms) and deterministic fallback. Optional non-binding signal per the Brain Ladder.
3. **Proxy Complexity Gating & OMA Sidecar Intercept (`server/server_router.py` + `plugin/oma_sidecar/`):** When `plugins.enabled` and `plugins.oma_enabled` are true, top-level turns (`request_depth == 0` and `x-oma-sidecar != 1`) with high complexity (`complexity >= 0.75` or task types `full_workflow`/`refactor`) are intercepted and delegated to the OMA Node.js sidecar runner (`runner.js` + `tools.js` workspace tool suite). Recursion headers (`x-oma-sidecar: 1`) prevent loops, and any OMA error fails soft back to direct LLM dispatch.
4. **Capability Vector Model Selection (`routing/model_pool.py` + `routing/dispatcher.py`):** Multi-dimensional capability scoring (`reasoning`, `tool_reliability`, `code_quality`, `latency_class`) weighted across task types via `TASK_TYPE_WEIGHTS`. Capability Floor Routing picks the cheapest qualifying model; per-turn confidence floor $\min(\text{base} + 0.15 \times (1 - \text{conf}), 0.60)$ on every classified turn plus optional additive session escalation bias (cap 0.75, TTL in turns).
5. **Plugin Runtime (`skail/plugin/` — Brain Ladder, Deterministic-First):** SQLite WAL ledger (async bounded queue, batched, durable-only events), bias store (`SessionBiasStore`), OMA task launcher (`start_task`), salvaged executor proof path, and templated synthesis (LLM stub off). SLM is never an authority for escalation, stagnation, completion, or safety.
6. **Session Guard (`server/session_guard.py`):** Enforces byte-identical prompt prefix immutability across turns for upstream provider cache hits, and compacts non-structural message history at 80% context capacity.
7. **Knowledge Vector Store (`knowledge/vector_store.py`):** Embedded LanceDB vector index using deterministic 16-dimensional term-hash embeddings for zero-overhead local code symbol retrieval.

---

## Quick Start

### Installation

Install globally via **npm** or directly into Python with **pip**:

```bash
# Option A: Global installation via npm (recommended for agent users)
npm install -g skail

# Option B: Direct Python installation
pip install -r requirements.txt
pip install -e .
```

### Launching

```bash
# 1. Interactive onboarding & TUI dashboard
skail

# 2. Start headless daemon in background
skail start --headless --daemon

# 3. Stop background daemon
skail stop

# 4. Direct agent launch shortcuts
skail start --claude
skail start --opencode
skail start --pi
```

> [!NOTE]
> By default, the local proxy server listens on `http://127.0.0.1:11434/v1` (OpenAI format) and `http://127.0.0.1:11434` (Anthropic format).

---

## Supported Agents

Skail provides automated configuration, shims, and lifecycle hooks for major coding assistants:

```bash
# Configure and install launcher shims for all agents:
skail install all

# Or install specific agents:
skail install claude opencode pi omp
```

> [!IMPORTANT]
> Agent configuration edits are bounded between `# BEGIN SKAIL` and `# END SKAIL` markers, with automated backups saved to `~/.skail/backups/<agent>/<timestamp>.bak` (retaining the last 5 backups). Running `skail reset` or `skail uninstall` cleanly restores all original configuration files.

### Claude Code

Skail provides an Anthropic-compatible `/v1/messages` translation shim and configures `settings.json`. When `plugins.enabled=true` **and** `plugins.claude_enabled=true`, Claude Code hooks (`PreToolUse`, `PostToolUse`, `Stop`, `SubagentStart`, `SubagentStop`) are installed via marker-bounded edits to `settings.json` as direct HTTP hooks to `http://127.0.0.1:<port>/plugin/events` with a 10 ms timeout. The legacy `skail hook claude <Event>` CLI remains as a fallback and still exits 0-always, appending to the spool file if the host agent or older hook protocol needs it.

```bash
# Launch Claude Code directly through Skail
skail start --claude

# Or manually configure Claude Code environment:
export ANTHROPIC_BASE_URL="http://127.0.0.1:11434"
export ANTHROPIC_AUTH_TOKEN="skail-local"
export ANTHROPIC_MODEL="skail"
claude
```

### OpenCode

Skail configures `opencode.json` with structured OpenAI-compatible provider endpoints. The OpenCode plugin shim is doc-only/stubbed behind `plugins.opencode_enabled=false`.

```json
{
  "provider": {
    "skail": {
      "type": "openai",
      "baseURL": "http://127.0.0.1:11434/v1"
    }
  },
  "model": "skail/skail"
}
```

```bash
# Launch directly through Skail
skail start --opencode
```

### Pi Coding Agent

Pi integration installs a TypeScript extension `<pi_dir>/extensions/skail.ts` using `pi.registerProvider()` and sets `defaultProvider: "skail"` in `settings.json`. The Pi extension is a gated constant (inert) behind `plugins.pi_enabled=false`.

```bash
# Launch directly through Skail
skail start --pi
```

### Oh My Pi (OMP)

Skail provides native integration with Oh My Pi via provider registration (`~/.omp/agent/models.yml`), default model role configuration (`~/.omp/agent/config.yml`), and the TypeScript extension `~/.omp/agent/extensions/skail.ts`.

When `plugins.enabled=true` and `plugins.omp_enabled=true`, the extension installs:
- **Subagent tracking & tier routing:** Automatically observes `agent_start`/`agent_end` events and routes child subagents to the budget model tier.
- **Session & tool observability:** Dispatches `session_start`, `tool_call`, and `tool_result` events directly to `/plugin/events` with fail-soft spool file fallback.
- **Codebase knowledge search:** Registers the `skail_search` tool calling Skail's local RAG MCP endpoint (`/mcp/tools/call`).

```bash
# Link Oh My Pi to Skail
skail omp link

# Unlink Oh My Pi
skail omp unlink
```

---

## The Three Pseudo-Models

Skail exposes three virtual model endpoints to connected coding assistants:

| Pseudo-Model | Selection Behavior | Best For |
| :--- | :--- | :--- |
| **`skail`** | Capability Floor Routing; selects the **cheapest qualifying model** | Everyday software engineering, feature work, & mixed workflows |
| **`skail-budget`** | Capability Floor Routing; selects the **cheapest qualifying model** | Repetitive tasks, single edits, docs, & high-frequency runs |
| **`skail-expensive`** | Capability Floor Routing; selects the **most capable qualifying model** | Complex architectural refactoring, deep reasoning, & greenfield design |

---

## How It Works Internally

### 1. Turn Guard (`server/turn_guard.py`)

Turn Guard evaluates incoming messages synchronously in <2ms (regex-only, I/O-free):
- **Clean User Turn** → Routes to local SLM classification, followed by Capability Floor Routing with per-turn confidence floor.
- **`DIRECT_ACTIVE_TIER` (Active Tool Loop)** → Bypasses SLM and routes directly to the active model tier (inheriting active session capability floor). Healthy loops touching multiple files or turns are never interrupted or re-evaluated.
- **Stagnation Trigger** (3+ identical consecutive tool calls or 2+ consecutive tool execution errors) → Triggers deterministic re-classification via the SLM classifier (no replanning, no plan mutation).

### 2. SLM Classification (`routing/slm_planner.py`)

The local Small Language Model (defaulting to Qwen 2.5 Coder 0.5B ONNX) emits a lightweight `TaskClassification`:
- **`task_type`**: One of `chat`, `explain`, `reconnaissance`, `single_edit`, `multi_edit`, `debug`, `refactor`, `full_workflow`, `git_ops`, `routine`, `read_answer`, `knowledge_query`, `research`.
- **`confidence`**: Classification confidence score between `0.0` and `1.0`.
- **`complexity_score`**: Scalar complexity score in `[0, 1]`.
- The classifier is protected by a 2000 ms circuit breaker with deterministic fallback. There are no sub-tasks, phases, or task graph topologies.

### 3. Capability Floor Routing (`routing/model_pool.py` + `routing/dispatcher.py`)

Skail matches candidate models using a multi-dimensional capability vector:

$$\text{Dimensions} = (\text{reasoning},\; \text{tool\_reliability},\; \text{code\_quality},\; \text{latency\_class})$$

1. **Task-Specific Weighting:** Dimension weights are assigned based on `task_type` (`TASK_TYPE_WEIGHTS`).
2. **Capability Fit Scoring:** Computes `capability_fit(vector, weights)` as:

$$\text{fit} = \min_{d \in \text{dominant}} (\text{vector}[d]) + 0.1 \times \sum_{d} (w_d \times \text{vector}[d])$$

3. **Confidence Floor Tightening (Every Classified Turn):** Lower classification confidence raises the capability floor:

$$\text{floor} = \min(\text{base} + 0.15 \times (1 - \text{confidence}),\; 0.60)$$

4. **Session Escalation Bias (Optional, Additive, Cap 0.75):** When the plugin runtime fires a deterministic escalation trigger (e.g., consecutive errors), `SessionBiasStore` applies an additive bump to the floor for subsequent turns in that session (TTL in turns).
5. **Hard Filters:** Filters candidates by active status, tool support, reasoning support, minimum context window, and capability floor.
6. **Opt-In Price Cap:** `path_price_cap_usd_per_mtok` sets an optional price ceiling in USD per 1M tokens. If the price cap empties the pool, Skail falls back to the cheapest qualifying model with `fallback_reason = "price_cap_emptied_pool"`.
7. **Cheapest Selection:** Qualifying models are sorted by absolute cost ($P = \text{cost\_input} + 0.5 \times \text{cost\_output}$) ascending, picking the cheapest model (or most capable if `skail-expensive`).

### 4. Plugin Plane — Deterministic-First (Brain Ladder)

The plugin plane is **opt-in** (`plugins.enabled=false` by default) and **never on the routing hot path**. Ledger I/O and bias lookups are off the hot path; routing stays sub-ms.

**Brain Ladder (Binding Hierarchy):** Every plugin duty has a deterministic baseline; the local SLM is an optional non-binding refinement; the routed LLM handles judgment when needed—via the router.

| Duty | Deterministic Baseline (Primary) | SLM Role | Routed LLM Role |
| :--- | :--- | :--- | :--- |
| **Turn Classification** | Event type, tool/error counts, explicit intent | Optional label refinement (non-binding) | Never required |
| **Task Contract** | Fixed schema from request + harness metadata | Suggest missing fields only | Generate/revise when ambiguous |
| **Stagnation Judgment** | 3-identical / 2-errors thresholds | None by default | Optional diagnosis after trigger |
| **Quality / Progress** | Completion criteria, exit codes, diffs | Summarize evidence only | Semantic evaluation when requested |
| **Final-Output Synthesis** | Template from ledger facts | Optional concise wording | Best-effort synthesis (stub off) |
| **Escalation Decisions** | Explicit trigger matrix | Tie-breaker only after ambiguity | Select higher-capability model via router |

> [!CAUTION]
> **Never SLM-only:** Escalation, stagnation detection, success/completion claims, tool safety, contract constraints, and factual assertions in final output.

---

## Open-Multi-Agent (OMA) Sidecar

Skail includes an embedded **Open-Multi-Agent (OMA)** sidecar (`@skail/oma-sidecar`) for autonomous multi-agent task execution and workspace orchestration.

While Skail's primary proxy plane operates as a synchronous, zero-overhead (<2ms) router for everyday agent turns, high-complexity tasks (such as full architectural refactors, greenfield scaffolding, or multi-stage pipelines) require structured decomposition and multi-step tool execution. The OMA sidecar delivers this capability out-of-band, preserving sub-millisecond proxy routing while delegating heavy workflows to a dedicated Node.js multi-agent engine.

```text
               Proxy Complexity Gating & OMA Sidecar Intercept
 
   Client Agent (Claude / OpenCode / Pi / OMP)
         │
         ▼
   FastAPI Proxy (server/server_router.py)
         │
    Complexity Check (depth == 0, score ≥ 0.75 or task in {full_workflow, refactor})
         │
         ├─ Normal Turn (< 0.75) ────────► Capability Floor Routing (Sub-ms fast path)
         │
         └─ High Complexity (≥ 0.75) ────► Intercept & Delegate
                                                  │
                                                  ▼
                                       Python Plugin Runtime (start_task)
                                                  │
                                                  ▼
                                       OMA Node.js Sidecar (runner.js)
                                         mode: auto | runAgent | runTasks | runTeam
                                                  │
                                         ┌────────┴────────┐
                                         ▼                 ▼
                                   Workspace Tools     Child LLM Calls
                                   (oma_sidecar/       (x-oma-sidecar: 1)
                                    tools.js)              │
                                         │                 ▼
                                         │         Skail Proxy
                                         │         (No recursion loop)
                                         ▼                 │
                                   Execution Report ◄──────┘
                                         │
                                         ▼
                               Relay Stream / Response
                               (OpenAI SSE / Anthropic blocks)
```

### Key Capabilities & Architecture

1. **Proxy Complexity Gating (`server/server_router.py`):**
   When `plugins.enabled=true` and `plugins.oma_enabled=true`, incoming requests are evaluated for complexity. If a request is at top-level depth (`request_depth == 0` and `x-oma-sidecar != 1`) and exceeds the complexity threshold (`complexity_score >= 0.75` or task type is `full_workflow` or `refactor`), the router intercepts the turn before direct model dispatch and delegates the goal to the OMA runner.

2. **Execution Modes (`oma_mode`):**
   The OMA runner classifies or executes the task according to one of three orchestration modes:
   - **`runAgent` (Single Agent):** Focused autonomous agent executing iterative actions for single-domain tasks.
   - **`runTasks` (Sequential Pipeline):** Decomposes complex goals into an ordered sequence of discrete dependency tasks.
   - **`runTeam` (Multi-Agent Swarm):** Coordinates a team of specialized agents—decomposing the goal into a DAG, coordinating subagent workers in parallel, and synthesizing their deliverables.
   - **`auto` (Default):** Dynamically analyzes the user prompt to select `runTeam`, `runTasks`, or `runAgent`.

3. **Workspace-Bounded Tool Suite (`skail/plugin/oma_sidecar/tools.js`):**
   The OMA sidecar provides a secure, sandboxed set of tools strictly bounded to the workspace root:
   - **`read`**: Line-slice file reader with total line counts and range filtering.
   - **`write`**: Safe file creator with automatic recursive directory creation.
   - **`patch`**: Precision search-and-replace text patcher for targeted diff application.
   - **`bash`**: Shell command execution with configurable timeouts and workspace sandboxing.
   - **`glob`**: Fast file tree discovery matching glob patterns.
   - **`search`**: Workspace-wide regular expression and substring search.
   - **`git`**: Sandboxed version control operations (`status`, `diff`, `log`, `commit`).
   - **`subagent`**: Spawns isolated child agent sessions with scoped sub-goals.

4. **Recursion Protection:**
   When the OMA sidecar issues completion requests back to Skail (`http://127.0.0.1:11434/v1`), it attaches the `x-oma-sidecar: 1` and `x-skail-depth >= 1` headers. Skail detects these markers, bypassing the complexity gate and routing them directly via Capability Floor Routing. This guarantees zero infinite recursion loops.

5. **Synthesis Relay Streaming (`server_chat.py`, `server_messages.py`):**
   When OMA completes, its structured execution report (tasks completed, synthesis output, token usage) is streamed or formatted directly to the calling agent in their native wire protocol (OpenAI SSE `chatcmpl` chunks or Anthropic `content_block_delta` events).

6. **Fail-Soft Degradation:**
   If Node.js is not installed, the sidecar process fails, or execution times out, Skail automatically logs a warning and falls back immediately to normal fast-path LLM router dispatch. It **never returns a 500 or broken connection** to the connected client.

### OMA Configuration

Configure the OMA sidecar under the `plugins` section of `~/.skail/config.yaml`:

```yaml
plugins:
  enabled: true             # Enable plugin plane
  oma_enabled: true         # Enable OMA sidecar intercept (default: true when plugins enabled)
  oma_mode: "auto"          # Execution mode: "auto", "runAgent", "runTasks", or "runTeam"
  oma_node_path: null       # Path to node executable (defaults to "node" on PATH)
```

---

## Interactive TUI Dashboard

Skail includes an interactive terminal UI built with Textual:

```bash
skail
```

### Main Navigation Hub

Navigate directly to all major views from the main menu:

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
| `Ctrl+C` | Quit current screen / exit Skail (`Ctrl+Q` disabled) |

---

## CLI Command Reference

| Command | Description | Options & Flags |
| :--- | :--- | :--- |
| `skail` | Launches interactive TUI dashboard | `--version` |
| `skail start` | Starts the Skail proxy server | `--headless`, `--daemon`, `--port <int>`, `--host <str>`, `--claude`, `--opencode`, `--pi`, `--new-terminal` |
| `skail stop` | Stops the running proxy server & supervisor | `--port <int>` |
| `skail install [agents...]` | Configures agents & installs launcher shims | Positional: `claude`, `opencode`, `pi`, `omp`, `all` |
| `skail hook claude <Event>` | Legacy fallback shim — observe-only, appends to spool file, **exit-0-always** | Event: `PreToolUse`, `PostToolUse`, `Stop`, etc. The primary Claude Code path is direct HTTP to `/plugin/events` with a 10 ms timeout. |
| `skail omp link` | Links Oh My Pi configuration to Skail | |
| `skail omp unlink` | Reverts Oh My Pi configuration | |
| `skail edit` | Opens TUI directly on model/provider editor | |
| `skail stats` | Displays routing audit telemetry & cost stats | `--json`, `--days <int>`, `--reset`, `--force` |
| `skail update` | Upgrades Skail to the latest release | `--dry-run` |
| `skail reset` | Reverts all agent configurations & cleans shims | `--force` |
| `skail uninstall` | Reverts configs, removes shims, & uninstalls | `--force` |

---

## Configuration Reference

Configuration is stored in `~/.skail/config.yaml` (or `$SKAIL_HOME/config.yaml`), and credentials are kept in `~/.skail/auth.yaml` (`0o600` permissions).

```yaml
host: "127.0.0.1"
port: 11434
log_level: "INFO"
pseudo_model: "skail"
routing_log: true
launch_in_new_terminal: false

selection:
  # SLM Engine Settings
  slm_model_path: "models/qwen2.5-coder-0.5b-instruct-q4.onnx"
  slm_circuit_breaker_timeout_ms: 2000

  # Session Guard & RAG
  session_guard_compaction_ratio: 0.80
  rag_max_tokens: 250
  rag_db_path: "~/.skail/rag_db"

  # Selection & Capability Floor Tunables
  confidence_floor_k: 0.15
  confidence_floor_max: 0.60
  capability_tiebreak_price_band_pct: 0.0

  # Price Caps (USD per 1M tokens)
  path_price_cap_usd_per_mtok: {}

  # Workspace Tools
  executor_enable_tools: true
  executor_max_tool_rounds: 10
  executor_tool_time_budget_s: 180.0
  executor_max_read_bytes: 200000
  executor_enable_bash: false
  progress_verbosity: "verbose"

plugins:
  enabled: false
  claude_enabled: false
  pi_enabled: false
  opencode_enabled: false
  oma_enabled: true
  oma_mode: "auto"
  oma_node_path: null
  ledger_retention_days: 30
  escalation_ttl_turns: 10
  escalation_floor_bump: 0.15
  llm_synthesis_enabled: false
  execute_enabled: false
```

> [!NOTE]
> **Deprecated Keys:** Dead config keys removed in the two-plane transformation are tolerated with a startup warning and never cause a crash.

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

Skail exposes standard operational and proxy endpoints:

| Endpoint | Method | Description |
| :--- | :---: | :--- |
| `/healthz` | `GET` | Health check endpoint (`{"status": "ok"}`) |
| `/v1/models` | `GET` | OpenAI-compatible active models list |
| `/v1/chat/completions` | `POST` | OpenAI-compatible chat completion proxy (supports SSE `reasoning_content`) |
| `/v1/messages` | `POST` | Anthropic-compatible messages proxy (supports SSE `thinking_delta`) |
| `/v1/messages/count_tokens` | `POST` | Anthropic token counting endpoint |
| `/stats` | `GET` | Live audit telemetry, decision breakdowns, token volume, latency histograms, and explainability metrics |
| `/plugin/events` | `POST` | Plugin event ingestion (HTTP hook direct to daemon; spool remains fallback for legacy shims). Never 5xx; returns `ignored` when disabled |
| `/plugin/contract?session=` | `GET` | Returns the JSON task contract for a session |
| `/plugin/escalate` | `POST` | Deterministic trigger matrix → session bias update (`floor_bump`, `ttl_turns`) |
| `/plugin/execute` | `POST` | Internal executor proof path (gated by `plugins.execute_enabled`) |

> [!TIP]
> Plugin endpoints are fail-soft by design: they **never return 5xx** and are **no-ops when `plugins.enabled=false`**.

```bash
# View live telemetry in terminal
skail stats

# Export JSON audit telemetry
skail stats --json
```

---

## Development

```bash
# Clone repository and set up environment
git clone https://github.com/plum-sorathorn/Skail.git
cd Skail
pip install -r requirements.txt
pip install -e .

# Run test suite
python -m pytest

# Run smoke tests
python scripts/end_to_end_smoke.py              # Mode A: router-only liveness
python scripts/end_to_end_smoke.py --plugin     # Mode B: router + plugin plane

# Update graphify knowledge graph
graphify update .
```

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
