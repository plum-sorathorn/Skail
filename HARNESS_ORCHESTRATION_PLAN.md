# AutoConduck Architecture & Harness Orchestration Plan

---

## 1. Executive Summary & Objective

### The Core Problem
AutoConduck was attempting to act as a **second orchestrator running inside a proxy below an external agent harness**. Because AutoConduck has no workspace access, file locks, or shell tools, its internal subagents ran as text-only prompts that hallucinated analysis, injected synthetic messages into the conversation history (busting prompt caches), and hijacked tool-turn errors into runaway replanning loops.

### The New Architecture
AutoConduck's role is strictly partitioned:
1. **The Router**: O(models) in-memory selection based on capability floor and cost, plus passive model tier escalation during tool stagnation.
2. **The Topological Planner (SLM)**: Pure, abstract DAG generation (`ExecutionPlan`: phases, scopes, dependencies).
3. **Dedicated Harness Translation Layer**: Translating the DAG into the **exact native protocol** of each specific harness (`omp`, `Claude Code`, `OpenCode`, `Generic`) so the **outer harness** executes the subagents in its own workspace.

---

## 2. Component-by-Component Specifications

### Component A: Abstract DAG Generation (SLM Planner)
**Location:** `autoconduck/routing/smm_planner.py`
* **Responsibility:** Produces a pure, harness-agnostic topological graph.
* **Invariants:**
  - Has zero knowledge of `omp`, `Claude Code`, or tool names.
  - Strictly guarded: simple turns (<12 words, low complexity) never trigger DAGs.
  - Outputs standard `ExecutionPlan` containing `PhaseSpec` / `SubTaskSpec`:
    - `id`: unique phase identifier (e.g. `recon_auth`, `read_config`, `modify_session`)
    - `role`: `recon` | `read` | `edit` | `verify`
    - `goal`: concise objective
    - `scope`: targeted file paths
    - `depends_on`: prerequisite phase IDs for topological ordering

---

### Component B: Dedicated Harness Adapters (Translation Layer)
**Location:** `autoconduck/harnesses/<harness>.py`

Each adapter implements a clean contract:
```python
class BaseAdapter(ABC1:
    @abstractmethod
    def render_plan(self, plan: ExecutionPlan, tools: list[dict[str, Any]] | None = None) -> str:
        """Translate abstract ExecutionPlan into this harness's native execution syntax."""
        ...
```

**1. OmpAdapter (`autoconduck/harnesses/omp.py`)`:**
* Produces explicit batch delegation text for OMP(s coordinator:
```markdown
### AutoConduck Task Decomposition
Batch 1 (Independent Parallel Tasks):
- Agent 1 (recon) => Analyze auth token validation in autoconduck/auth.py
- Agent 2 (recon) => Analyze session store lifecycle in autoconduck/session.py

Batch 2 (Sequential Follow-up):
- Agent 3 (edit) [requires: Agent 1, Agent 2] => Implement rate-limiting middleware
```

**2. ClaudeCodeAdapter (`autoconduck/harnesses/claude_code.py`)`:**
  Injects a system-level steering directive instructing the lead model to invoke the native `Task` tool for Level 0 DAG tasks:
```markdown
[AUTOCONDUCK EXECUTION DIRECTIVE]
This task requires structured multi-agent decomposition.
Before performing direct workspace modifications, you MUST invoke your `Task` tool in parallel for the following independent subtasks:
1. Task(description="Analyze auth token validation in autoconduck/auth.py", prompt="...")
2. Task(description="Analyze session store lifecycle in autoconduck/session.py", prompt="...")
```

**3. OpenCodeAdapter (`autoconduck/harnesses/opencode.py`)`:**
  Injects directive targeting OpenCode's `subagent(type='Explore'|'Build', prompt='...')` tool.

**4. GenericAdapter (`autoconduck/harnesses/generic_openai.py`)`:**
  Used for single-agent harnesses (Cursor, Aider, Continue). Subagents are disabled; outputs a sequential phase checklist.

---

## 3. Implementation Phases & Step-by-Step Roadmap

| Phase | Tasks | Target Files |
| :--- | :--- | :--- |
| **Phase 1: Topological Core & Data Models** | Ensure `ExecutionPlan` exposes clean topological batches without harness text formatting. | `slm_planner.py`, `fan_out.py` |
| **Phase 2: Dedicated Harness Adapters** | Add `render_plan()` to `OmpAdapter`, `ClaudeCodeAdapter`, `OpenCodeAdapter`, and `GenericAdapter`. | `autoconduck/harnesses/*.py` |
| **Phase 3: Router Integration** | Wire Turn 0 handoff rendering to the detected harness adapter in `server_router.py`. | server_router.py, server_chat.py, handoff.py |
| **Phase 4: Deprecate Internal Execution** | Remove internal LLM subagent runner and cleanup legacy synthetic user message injections. | `subagents.py`, `dynamic_factory.py` |
| **Phase 5: Test Suite & Verification** | Add unit tests for each adapter's rendering output; run full test suite and update code graph with `graphify`. | `tests/test_harness_rendering.py`, `tests/` |
