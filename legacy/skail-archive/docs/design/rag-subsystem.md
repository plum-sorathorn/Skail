# Knowledge Vector Store & RAG Subsystem

## 1. Overview
The Knowledge Subsystem (knowledge/vector_store.py) provides embedded semantic retrieval using **LanceDB** to furnish ground-truth code snippets to SLM subagents and orchestrator nodes.

## 2. Architecture & Invariants
- **Local Embedded Storage**: Vector records stored in ~/.skail/rag_db without external cloud dependencies.
- **Sub-50ms Retrieval**: Vector similarity search filtered by file paths, symbols, and token budgets (default 250 tokens per snippet).
- **Graceful Fallback**: If LanceDB native binary is unavailable or database is empty, search degrades soft-fail to deterministic keyword/regex extraction.
- **Harness & Sidecar Integration**: Serves codebase search queries via local MCP endpoint (`/mcp/tools/call`) registered as `skail_search` in Oh My Pi (`~/.omp/agent/extensions/skail.ts`) and OMA Node.js sidecar workspace tool suite (`skail/plugin/oma_sidecar/tools.js`).
