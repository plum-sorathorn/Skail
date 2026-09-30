# ADR 0004: Evidence-gate provider compatibility

Status: Accepted
Date: 2026-09-02
Depends on: [ADR 0002](./0002-framework-version-contract.md)

The dollar-cost authority and missing-usage settlement described below were superseded by
[ADR 0008](./0008-in-house-token-cost-ledger.md). Provider-supplied dollar amounts are no longer
the spending authority; Skail prices measured tokens in-house and labels estimates.

## Context

OpenAI-compatible endpoints differ in streaming tool fragments, structured output, model
discovery, usage extensions, and error semantics. Treating construction as full support would make
Skail's routing and cost claims unreliable.

## Decision

Skail reports provider support as separate constructible, contract-tested, automatic-routing,
and maintained-CI dimensions. Generic compatible models default to manual/unverified. Automatic
routing requires trusted model capability and pricing evidence.

LLM Gateway is first-class at `https://api.llmgateway.io/v1`. Its adapter parses raw SSE and HTTP
responses so fragmented tool arguments and gateway usage fields remain observable. When a response
omits or malforms `usage.cost`, Skail records unknown provider cost and settles from the frozen
assignment estimate when available; it never synthesizes zero as an authoritative or estimated
charge.

The authenticated `GET /v1/models?exclude_deprecated=true` response is the runtime catalog source.
Prompt, completion, and input cache-read prices are parsed as `Decimal` per-token values and
normalized to per-million-token fields. Discovered entries retain retrieval time and endpoint
provenance. Malformed, missing, or stale prices remain unavailable for hard-budget authorization;
unknown capability evidence remains manual-only until trusted evidence is supplied. A bounded local
cache may display stale entries for offline inspection, but it cannot authorize a hard-budget route.

DevPass retains a separate Skail provider/catalog identity but uses the same current LLM Gateway
base URL and its configured bearer credential. It participates in the same authenticated model
discovery and local-snapshot flow. Its distinction is plan billing and canonical model namespace,
not a separate inference endpoint.

The local catalog snapshot is versioned JSON at `~/.skail/catalog/<provider>.json`. A successful
refresh is written atomically with UTC retrieval metadata, endpoint/query provenance, and all
validated accessible entries. Startup may use a validated snapshot only for retry-safe transient
failures; stale or missing prices remain unavailable to hard-budget routing.

`langchain-openai==1.6.0` is pinned as the optional `openai-compatible` integration. Compatible
construction explicitly disables Responses API inference and provider retry ownership. Skail's
registry imports optional integrations only when selected and validates options before construction.

## Evidence

- LLM Gateway developer overview and canonical compatible endpoint:
  <https://docs.llmgateway.io/developers>
- LLM Gateway chat, streaming, and usage contract:
  <https://docs.llmgateway.io/v1_chat_completions>
- LLM Gateway model discovery contract: <https://docs.llmgateway.io/v1_models>
- DevPass relationship and usage: <https://docs.llmgateway.io/developers/devpass-usage>
- LangChain OpenAI-compatible construction:
  <https://reference.langchain.com/python/langchain-openai/chat_models/base>

## Consequences

The default suite remains credential-free. Live LLM Gateway and DevPass quality, tenant catalog,
and billing validation require explicit credentials and remain pending until run. Provider-specific
extensions not covered by normalized contracts are ignored rather than passed through implicitly.
