# ADR 0002: Pin the DeepAgents runtime contract

Status: Accepted
Date: 2026-09-02
Depends on: [ADR 0001](./0001-rudder-native-multi-agent-harness.md)

## Context

Rudder depends on model assignment occurring before a compiled child's first call, stable nested
streaming, checkpointed interrupts, concurrent synchronous subagents, and cooperative
cancellation. DeepAgents is a beta dependency and these framework behaviors are not Rudder-owned
APIs. Phase 1 repeated the compatibility spike against current official documentation and the
installed packages on Python 3.12+.

## Decision

The initial supported runtime tuple is pinned exactly:

- `deepagents==0.7.13`;
- `langchain==1.3.18`;
- `langchain-core==1.6.1`;
- `langgraph==1.2.11`;
- `langgraph-checkpoint==4.2.0`;
- `langgraph-checkpoint-sqlite==3.1.1`.

Rudder will consume these packages behind `rudder.runtime` adapters and retain contract tests for
every framework assumption. Dependency loosening requires the same contract suite to pass.

The adapter owns four current limitations:

1. The standard `task` tool exposes only `description` and `subagent_type`; Rudder lifecycle state
   is constructed deterministically behind that boundary.
2. A `CompiledSubAgent` must provide its own `messages`-compatible state and interrupt policy.
3. Stable foreground cancellation is whole-run cooperative cancellation. Individual child steering
   is not promised by the synchronous path.
4. Tool-indirected child state cannot be reconstructed from parent checkpoint inspection alone, so
   Rudder's journal remains authoritative for task visibility and reconciliation.

DeepAgents currently brings Anthropic and Google integrations transitively. Rudder will not expose
or initialize them without explicit provider configuration or credentials. Provider support and
automatic-routing eligibility remain Rudder-owned, lazy, evidence-bearing decisions.

## Evidence

- DeepAgents subagents and the standard task surface:
  <https://docs.langchain.com/oss/python/deepagents/subagents>
- `CompiledSubAgent` state and result requirements:
  <https://reference.langchain.com/python/deepagents/middleware/subagents/CompiledSubAgent>
- `create_deep_agent` state, interrupt, and checkpointer parameters:
  <https://reference.langchain.com/python/deepagents/graph/create_deep_agent>
- LangChain model-request override middleware:
  <https://docs.langchain.com/oss/python/langchain/middleware/custom#dynamic-model-selection>
- LangGraph v2 nested streaming:
  <https://docs.langchain.com/oss/python/langgraph/streaming#subgraph-outputs>
- LangGraph persistence and SQLite checkpointers:
  <https://docs.langchain.com/oss/python/langgraph/persistence>

## Consequences

Framework upgrades are deliberately explicit. The stable event, assignment, task, executor, and
error contracts do not expose framework types. Optional v3 event streaming and preview async
subagents remain outside the stable boundary until separately proven.
