# ADR 0008: Calculate the Skail ledger from tokens and frozen model prices

Status: Accepted
Date: 2026-09-23
Supersedes: the provider-cost precedence in [ADR 0007](./0007-global-state-and-instruction-precedence.md)

## Context

Provider responses can contain a dollar amount as well as token counts. Depending on that amount
made Skail's ledger depend on a provider-specific cost extension, while another response for the
same model could be priced locally. The interactive test also needs an auditable per-model record
that includes child agents in the parent run's displayed total.

## Decision

1. Skail takes input, output, and cached-input token counts from completed model responses. It
   ignores a provider-supplied dollar amount for ledger settlement. The assignment freezes the
   model's catalog revision and per-million-token rates before the call.
2. Each measured call is priced with decimal arithmetic:
   `((input - cached_input) × input_rate + cached_input × cached_rate + output × output_rate)
   / 1,000,000`. When no cached rate is published, cached input uses the input rate. The call
   retains its model, task, run, token counts, frozen prices, and local cost. Stored Decimal costs
   are not rounded per call; display formatting may use fewer places.
3. A response with incomplete usage is not priced from a partial token count. The existing
   conservative attempt estimate is used where possible and remains labelled as an estimate;
   an ambiguous in-flight call remains unresolved and blocks unsafe replay. Missing usage is
   never represented as a measured zero-dollar call.
4. The run ledger includes the lead and every child task in that run exactly once. The TUI
   status strip shows cumulative cost across all runs in the session; its budget panel and meter
   remain scoped to the current run. Session export schema version 2 includes per-call token
   and price evidence and per-model totals. A model total is null when any of its calls is
   unresolved.
5. The LLM Gateway CLI is not part of the accounting or live-test workflow. The in-house ledger
   is an estimate of token-priced usage, not a claim about actual provider charges. Non-token
   fees, tiered prices, cache-write premiums, and calls with missing usage may make billed spend
   differ; tests must state these limits.

## Consequences

- Model price changes affect only future assignments. Earlier calls retain their frozen rates.
- Parent-run spend includes subagent calls even when they use different models or finish later.
- The TUI budget breakdown can still display historical provider-authoritative records, while
  new measured calls settle as token-derived estimates.
- A local budget gate cannot guarantee the provider's billed total when charges exist outside
  the token-price formula.

## Reference

[OpenCode's cost calculation](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/session.ts)
prices token categories per model, and its
[TUI prompt component](https://github.com/anomalyco/opencode/blob/dev/packages/tui/src/component/prompt/index.tsx)
displays the stored session cost. Its
[reported child-session omission](https://github.com/anomalyco/opencode/issues/11027)
motivates Skail's explicit lead-plus-child run regression.
