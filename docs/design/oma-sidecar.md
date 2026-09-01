# Open-Multi-Agent (OMA) Sidecar & Proxy Complexity Gating

## 1. Overview

AutoConduck operates as a zero-overhead, per-turn Capability Floor Routing selector for everyday coding turns. However, high-complexity tasks (such as full architectural refactorings, multi-module migrations, or multi-step execution workflows) benefit from structured multi-agent coordination, iterative tool loops, and task decomposition.

Rather than embedding an expensive graph-compilation engine into the synchronous proxy routing hot path, AutoConduck introduces the **Open-Multi-Agent (OMA)** Node.js sidecar (`@autoconduck/oma-sidecar`). High-complexity requests are intercepted via **Proxy Complexity Gating** (`server/server_router.py`) and delegated asynchronously to the OMA runner (`autoconduck/plugin/oma_sidecar/runner.js`).

---

## 2. Proxy Complexity Gating Intercept (`server/server_router.py`)

Every incoming chat or messages completion request passes through `route_target()`. Before proceeding to direct model selection and LiteLLM dispatch, the router evaluates whether the request qualifies for OMA delegation:

```text
                         route_target()
                               │
            Depth == 0 and x-oma-sidecar != 1?
                               │
               ┌───────────────┴───────────────┐
              YES                              NO
               │                               │
    plugins.enabled & oma_enabled?             ▼
               │                        Direct Fast-Path Routing
        ┌──────┴──────┐
       YES            NO
        │              │
  High Complexity?     ▼
  (score ≥ 0.75 or   Direct Fast-Path Routing
   full_workflow /
   refactor)
        │
   ┌────┴────┐
  YES        NO
   │          │
   │          ▼
   │   Direct Fast-Path Routing
   ▼
Delegate to OMA Sidecar
(plugin.runtime.start_task)
   │
   ├─ Success ──► Relay OMA Report (server_chat / server_messages)
   └─ Error   ──► Fail-Soft Degrade to Direct Fast-Path Routing
```

### Intercept Gating Criteria
1. **Top-Level Request**: `request_depth == 0` (extracted from `x-autoconduck-depth` header).
2. **Non-Reentrant**: `x-oma-sidecar != 1` (requests originating from the sidecar pass this header to prevent infinite recursion).
3. **Configuration Gate**: `plugins.enabled == True` AND `plugins.oma_enabled == True`.
4. **Complexity Gate**:
   - `complexity_score >= 0.75` (from SLM classification or heuristics), OR
   - `task_type in ("full_workflow", "refactor")`.

---

## 3. OMA Node.js Runner Architecture (`runner.js`)

The OMA sidecar is a pure Node.js (>=18) runner located at `autoconduck/plugin/oma_sidecar/runner.js`.

### Dynamic Mode Determination
The sidecar dynamically determines the execution mode based on the user goal:

| Mode | Trigger / Criteria | Execution Strategy |
| :--- | :--- | :--- |
| **`runTeam`** | Goals containing "team", "coordinate", "swarm", "architect", "multi-agent", "parallel", or length > 300 chars | Decomposes goal into a dependency DAG, executes coordinator and worker subagents, and synthesizes deliverables. |
| **`runTasks`** | Goals containing "step", "task", "sequence", "pipeline", numbered lists | Decomposes the goal into an ordered sequence of discrete tasks executed in succession. |
| **`runAgent`** | Standard single-purpose goals | Single focused autonomous agent executing iterative actions. |

### Workspace Tool Suite (`tools.js`)
The runner provides a suite of sandboxed tools strictly bounded to the workspace root:
- **`read`**: Reads file contents with optional line-slice parameters (`start_line`, `end_line`) and returns total line counts.
- **`write`**: Creates or replaces files, automatically creating missing parent directories.
- **`patch`**: Applies targeted search-and-replace text modifications to files.
- **`bash`**: Executes shell commands with timeout enforcement and workspace directory bounds.
- **`glob`**: Discovers matching files using glob patterns.
- **`search`**: Recursively searches file contents for regular expressions or literal strings.
- **`git`**: Executes bounded git operations (`status`, `diff`, `log`, `commit`).
- **`subagent`**: Spawns scoped child agent executions with isolated context.

All tools enforce `resolveWorkspacePath()`: any path traversal attempting to escape `workspaceRoot` raises a `Security Violation` error.

---

## 4. Recursion Protection & Wire Protocol

When the OMA sidecar issues model completion requests back to AutoConduck (`http://127.0.0.1:11434/v1`), it attaches:
```http
x-oma-sidecar: 1
x-autoconduck-depth: 1
```

`server/server_router.py` detects these headers and immediately bypasses the complexity gate, routing child model requests directly through Capability Floor Routing.

Upon sidecar completion:
- **OpenAI Streaming (`/v1/chat/completions`)**: `server_chat.py` relays the execution summary as chunks:
  ```json
  {"choices": [{"delta": {"content": "<oma_report>"}}]}
  ```
- **Anthropic Messages (`/v1/messages`)**: `server_messages.py` relays the output as content block deltas:
  ```json
  {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "<oma_report>"}}
  ```

---

## 5. Fail-Soft Guarantee

In accordance with AutoConduck's core fail-soft invariant:
- If Node.js is missing or unavailable,
- If the OMA runner process crashes or exits with non-zero status,
- Or if parsing the OMA output fails,

`server_router.py` logs a warning and degrades gracefully to standard fast-path LLM router dispatch. The client assistant is guaranteed to receive a valid response and **never receives a 500 error**.
