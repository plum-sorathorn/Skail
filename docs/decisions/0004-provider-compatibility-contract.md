# ADR 0004: Evidence-gate provider compatibility

Status: Accepted
Date: 2026-09-02
Depends on: [ADR 0002](./0002-framework-version-contract.md)

## Context

OpenAI-compatible endpoints differ in streaming tool fragments, structured output, model
discovery, usage extensions, and error semantics. Treating construction as full support would make
Rudder's routing and cost claims unreliable.

## Decision

Rudder reports provider support as separate constructible, contract-tested, automatic-routing,
and maintained-CI dimensions. Generic compatible models default to manual/unverified. Automatic
routing requires trusted model capability and pricing evidence.

LLM Gateway is first-class at `https://api.llmgateway.io/v1`. Its adapter parses raw SSE and HTTP
responses so fragmented tool arguments and gateway usage fields remain observable. When a response
reports tokens but omits `usage.cost`, token counts are observed but cost remains estimated; zero is
never presented as an authoritative charge.

DevPass retains a separate Rudder provider/catalog identity but uses the same current LLM Gateway
base URL and bearer credential. Its distinction is plan billing and canonical model namespace, not
a separate inference endpoint.

`langchain-openai==1.6.0` is pinned as the optional `openai-compatible` integration. Compatible
construction explicitly disables Responses API inference and provider retry ownership. Rudder's
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
