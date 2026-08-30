> SUPERSEDED (two-plane transformation): the described DAG/SLOW-path machinery was removed in the two-plane transformation. Current architecture: README.md and docs/phase-reports/PHASE1A.md..PHASE4.md. This document is retained for historical reference only.

# Dynamic DAG Factory — HISTORICAL (superseded)

## 1. Overview (historical)
AutoConduck replaced fixed 6-phase static orchestrators with an on-the-fly **Dynamic StateGraph Factory** (orchestrator/dynamic_factory.py). Graphs were compiled dynamically at runtime based on the topology of subtasks defined in the SLM ExecutionPlan. This machinery was removed in Phase 1 of the two-plane transformation. The proxy is now a pure fast-only model router (Turn Guard → SLM classifier → fit-gate-then-cheapest selection) with no DAG, no subtasks, and no phases.

## 2. Dynamic Graph Topology (historical)
1. **Init Node (init)**: Initializes execution metadata, session IDs, and loads verified context.
2. **RAG Node (rag)**: (Optional) Ingests semantic code snippets from LanceDB when plan.needs_rag == True.
3. **Subtask Fan-Out Nodes (subtask_*)**: Generated dynamically per subtask. Independent subtasks execute concurrently in parallel worker threads.
4. **Synthesizer Node (synthesizer)**: Combines verified context and subtask outputs into a cohesive final answer.

## 3. Concurrency & State Reducer Architecture (historical)
To support arbitrary parallel fan-out without state update conflicts, DynamicState uses typing.Annotated reducers:
- subtask_outputs: Annotated[dict[str, str], _merge_dict]
- subtask_errors: Annotated[dict[str, str], _merge_dict]
- verified_context: Annotated[list[str], operator.add]
- active_node: Annotated[str, _latest_val]

## 4. SQLite State Checkpointing (historical)
State is persisted via SqliteSaverFallback inheriting from BaseCheckpointSaver, guarded by thread-safe threading.Lock() to prevent multi-threaded SQLite concurrency collisions.
