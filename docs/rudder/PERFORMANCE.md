# Rudder Performance & Context Hardening

Status: Active
Date: 2026-09-03
Reference: ADR 0005, SPEC.md Section 20

## 1. Objectives

Rudder bounds the overhead introduced by local multi-agent orchestration, structured event streaming, and local observability. The design avoids heavy daemon processes, IPC bridges, or unconstrained prompt expansion.

## 2. Empirical Performance Baselines

Benchmarks were executed on standard commodity hardware (Windows x64):

| Metric | Target | Measured | Result |
|---|---|---|---|
| **CLI Startup Latency** | < 800ms | **~450ms** | **PASS** |
| **Event Persistence (1,000 events)** | > 100 appends/sec | **227.9 appends/sec** | **PASS** |
| **Event Stream Query (1,000 events)** | < 100ms | **11.0ms** | **PASS** |
| **TUI Projection (1,000 events, 3 agents)** | > 50,000 events/sec | **> 1,500,000 events/sec** | **PASS** |
| **Context Assembly & Redaction (100 items)** | < 10ms | **0.2ms** | **PASS** |
| **Database Storage Footprint** | < 1 KB/event | **~720 bytes/event** | **PASS** |

## 3. Key Architectural Invariants

### 3.1 Sub-Second Startup via Lazy Imports
Heavy framework imports (`deepagents`, `langchain`, `langgraph`) are deferred until a task run instruction actually begins. CLI argument parsing, subcommand help (`rudder --help`), session lists (`rudder sessions list`), and configuration inspection execute within ~450ms.

### 3.2 TUI Responsiveness Under Concurrency
`TuiProjection` is a pure-Python state machine decoupled from Textual's rendering tree. Replaying 1,000 structured lifecycle, model delta, and tool completion events takes less than 1 millisecond. Even during rapid token streaming with three concurrent child subagents, the TUI event loop remains fluid with zero UI stutter.

### 3.3 Context-Packet Token Pressure & Truncation
- Bounded token allocation: `ContextAssembler` enforces strict token budgets (default 2,000 tokens for context packets).
- Items exceeding token limits are tracked in `omissions` with explicit omission labels rather than silently dropped or overflowing the model context window.
- Large tool outputs (e.g. multi-megabyte grep or file reads) are stored as durable SQLite artifacts with only bounded excerpts injected into prompt context.

### 3.4 Database Growth & Retention
At ~720 bytes per structured event, a typical 50-event multi-agent coding session consumes approximately 36 KB of storage in the local SQLite journal. Compaction safely summarizes older transcripts while preserving all lineage, model assignments, budget states, and artifact references.
