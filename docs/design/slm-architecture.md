# Embedded SLM Architecture (Qwen 2.5 Coder 0.5B Instruct)

## 1. Overview
AutoConduck's core routing and planning intelligence is powered by embedded Small Language Models (SLMs) such as **Qwen 2.5 Coder 0.5B / 1.5B Instruct** and **Liquid LFM 2.5 1.2B** (ONNX / GGUF), backed by instant zero-overhead rule heuristics. This replaces naive complexity scoring with structured cognitive task planning.

## 2. Invariants & Performance Constraints
- **Local Model Execution**: Quantized local weights execute on CPU/GPU via ONNX Runtime / llama.cpp or fallback shims.
- **Strict JSON Schema Conformance**: Guided generation via structured schemas or Pydantic JSON validation.
- **Dedicated SLM Planning Circuit Breaker**: Any SLM planning timeout (configurable via `slm_circuit_breaker_timeout_ms`, default 2000ms) or parsing error trips the circuit breaker and falls back immediately to deterministic capability SLA-based direct dispatch without crashing. Subagent fan-out and DAG execution operate under independent per-subagent budgets (120s).

## 3. Schema & Output Contract
The SLM produces an `ExecutionPlan` with the following structure:
- `route`: `fast_direct` | `dynamic_dag`
- `confidence`: float [0.0, 1.0]
- `task_type`: `chat` | `explain` | `recon` | `single_edit` | `multi_edit` | `debug` | `refactor` | `full_workflow` | `git_ops` | `routine`
- `suggested_sla`: `CapabilitySLA` requirements for the selected model
- `needs_rag`: boolean flag
- `rag_queries`: list of query strings
- `subtasks`: list of `SubTaskSpec` items
- `synthesizer_sla`: `CapabilitySLA` requirements for final synthesis
