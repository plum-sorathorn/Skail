# Embedded SLM Architecture (Qwen 2.5 Coder 0.5B Instruct)

## 1. Overview
AutoConduck's per-turn classification intelligence is powered by embedded Small Language Models (SLMs) such as **Qwen 2.5 Coder 0.5B / 1.5B Instruct** and **Liquid LFM 2.5 1.2B** (ONNX / GGUF), backed by instant zero-overhead rule heuristics. The SLM emits a lightweight `TaskClassification` (`task_type` / `confidence` / `complexity_score`) that feeds Capability Floor Routing on every classified turn. Per the Brain Ladder, the SLM is an optional non-binding signal — never an authority for escalation, stagnation, or completion.

## 2. Invariants & Performance Constraints
- **Local Model Execution**: Quantized local weights execute on CPU/GPU via ONNX Runtime / llama.cpp or fallback shims.
- **Strict JSON Schema Conformance**: Guided generation via structured schemas or Pydantic JSON validation.
- **Dedicated SLM Classifier Circuit Breaker**: Any SLM inference timeout (configurable via `slm_circuit_breaker_timeout_ms`, default 2000ms) or parsing error trips the circuit breaker and falls back immediately to a deterministic classification and capability SLA-based direct dispatch without crashing.

## 3. Schema & Output Contract
The SLM produces a `TaskClassification` with the following structure:
- `task_type`: `chat` | `explain` | `reconnaissance` | `single_edit` | `multi_edit` | `debug` | `refactor` | `full_workflow` | `git_ops` | `routine` | `read_answer` | `knowledge_query` | `research`
- `confidence`: float [0.0, 1.0]
- `complexity_score`: float [0.0, 1.0]

`TaskClassification` feeds `routing/dispatcher.py::_select_planned`, which applies the per-turn confidence floor `min(base + 0.15*(1-confidence), 0.60)` and optional session escalation bias (additive, cap 0.75) before Capability Floor Routing. In addition, high complexity classification (`complexity_score >= 0.75` or task types `full_workflow`/`refactor`) triggers the Proxy Complexity Gating Intercept (`server/server_router.py`) to launch the OMA Node.js sidecar runner (`autoconduck/plugin/oma_sidecar/runner.js`) when `plugins.enabled` and `plugins.oma_enabled` are true. Detailed weights are defined in `routing/model_pool.py::TASK_TYPE_WEIGHTS`.
