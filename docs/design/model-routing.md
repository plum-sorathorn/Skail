# Model Routing & Selection Engine

## 1. Overview

AutoConduck operates as a **fast-only, per-turn "fit-gate then cheapest"** selector, designed to minimize token costs on routine coding turns while seamlessly routing complex architecture/debugging turns to capable frontier models.

Routing is synchronous, in-memory, sub-millisecond, and operates on an $O(\text{models})$ hot path without slow-path branching, replanning loops, or runtime task graphs.

---

## 2. Selection Pipeline (`routing/model_pool.py` & `routing/dispatcher.py`)

Every incoming request passes through the following deterministic pipeline:

```
Request Arrival
   │
   ▼
Turn Guard (Regex, <2ms, synchronous)
   ├─ DIRECT_ACTIVE_TIER ──► Active Tool Loop (inherits session capability floor)
   ├─ ESCALATE_SLM       ──► Stagnation Trigger (applies immediate +0.15 floor bump)
   └─ CLEAN / RE-CLASSIFY ─► SLM Classifier (TaskClassification)
                                │
                                ▼
                       Capability Floor Calculation
                                │
                                ▼
                       Filtering & Capability Fit Gate
                                │
                                ▼
                       Equal-Cost Capability Tiebreaker
                                │
                                ▼
                       Cheapest Qualifying Model Selected
```

### 1. Hard Filtering
- **Enabled Status**: Model must be enabled and not marked degraded.
- **Tools Requirement**: If the request requires tool calling, models without tool support are excluded.
- **Reasoning Requirement**: If frontier reasoning is requested, models without reasoning capabilities are excluded.
- **Context Window**: Models whose context window cannot accommodate the active message payload are filtered out.

### 2. 4D Capability Vector & Fit Gating
Each model is characterized by a 4-dimensional `capability_vector`:
1. `reasoning` (0.0 – 1.0)
2. `tool_reliability` (0.0 – 1.0)
3. `code_quality` (0.0 – 1.0)
4. `latency_class` (0.0 – 1.0)

For each turn, `capability_fit(model, task_type)` is evaluated:
$$\text{fit} = \min_{w_i > 0.25} (v_i) + 0.1 \times \sum (w_i \cdot v_i)$$
where weights $w_i$ are assigned dynamically based on `task_type` (`TASK_TYPE_WEIGHTS`).

### 3. Dynamic Capability Floor & Confidence Scaling
The minimum required capability floor is derived dynamically per turn:
$$\text{floor} = \min(\text{base} + 0.15 \times (1 - \text{confidence}), 0.60) + \text{session\_bias}$$
where `base` is determined by `TASK_BASE_FLOORS` scaled by `complexity_score`:
- `debug`: base 0.35 + $0.2 \times \text{complexity}$
- `refactor`: base 0.40 + $0.2 \times \text{complexity}$
- `full_workflow`: base 0.45 + $0.2 \times \text{complexity}$
- `multi_edit`: base 0.25 + $0.15 \times \text{complexity}$
- `single_edit` / `routine` / `chat`: base 0.0 – 0.10

### 4. Tool Loop Floor Inheritance & Deterministic Stagnation Bias
- **Tool Loop Inheritance**: Turns on `TurnAction.DIRECT_ACTIVE_TIER` inherit the session's active capability floor (`SessionBiasStore.get_session_floor`), preventing deep debugging or refactoring loops from down-tiering to inadequate models mid-session.
- **Deterministic Stagnation Escalation**: If Turn Guard detects genuine stagnation (3+ identical calls or 2+ consecutive errors), `TurnAction.ESCALATE_SLM` applies an immediate $+0.15$ bias bump (capped at $0.75$, TTL = 10 turns).

### 5. Cost Sorting & Capability Tiebreaking
All qualifying models that meet or exceed the capability floor are sorted by:
1. `absolute_cost` ascending (price per 1M tokens)
2. $-\text{capability\_fit}$ descending (capability tiebreaker for equal-cost and zero-cost models)

The cheapest qualifying model is selected for upstream dispatch via LiteLLM.

---

## 3. Multi-Provider Preset Synchronization (`scripts/sync_all_presets.py`)

AutoConduck maintains an automated catalog of 1,000+ model presets across 11 providers (`openai`, `anthropic`, `google`, `mistral`, `deepseek`, `groq`, `openrouter`, `together`, `xai`, `devpass`, `llmgateway`).

- **Upstream Ingestion**: Dynamically fetches the upstream LiteLLM database and live gateway endpoints (`https://devpass.llmgateway.io/models`, `https://api.llmgateway.io/v1/models`).
- **Automatic Classification**: Classifies models by tier (`budget`, `balanced`, `expensive`), filtering non-chat artifacts (embeddings, audio, image gen).
- **Direct Atomic Persistence**: Writes synchronized presets directly to `autoconduck/presets/presets_data.py`, refreshes `presets_fallback.py`, and regenerates `docs/model_catalog.md`.
