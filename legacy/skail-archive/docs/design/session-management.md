# Session Lifecycle & Context Guard

## 1. Overview
Coding assistants frequently maintain long sessions (40+ turns). Naive context manipulation breaks upstream prompt caching (e.g. Anthropic prompt caching, OpenAI prefix caching). Skail provides SessionGuard (`server/session_guard.py` — relocated from `orchestrator/` in the two-plane transformation) to enforce strict prefix immutability and context window ceiling protection.

## 2. Invariants
- **Immutable Prefix Contract**: System prompts and initial user instructions (turns 0 and 1) are guaranteed to remain byte-identical across all turns.
- **80% Context Window Ceiling**: When estimated token volume exceeds 80% of model context window, intelligent compaction is applied to intermediate turns.
- **Fenced Content Preservation**: Compaction preserves code fences and markdown structural headers (#, ##), compacting only verbose tool output logs.
- **Session Extraction & Bias Tracking**: Session identifiers are extracted from request headers (`x-skail-session-id`, `x-session-id`, `x-conversation-id`) with fallback conversation-hash derivation. Active session capability floors and escalation bias (+0.15, cap 0.75, TTL 10 turns) persist across turns via `SessionBiasStore`.
