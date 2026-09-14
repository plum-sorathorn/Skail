# Phase 16 Economics and Isolation Review

Status: Complete
Date: 2026-09-10
Reviewed baseline: `c45eb26`

## Scope and governing contracts

This review applies ADR 0006 decisions 6–10, SPEC sections 6–10 and 19–22,
Architecture sections 7–9 and 13, Features sections 7–12 and 25, and the Phase 16 contract in the
adaptive orchestration and release guide. It reviews Phase 15's committed evaluation behavior and
rechecks the previously implemented workspace, integration, approval, recovery, and budget
boundaries that the evaluation relies on.

The reviewed evaluation is deterministic `synthetic_offline` evidence. It can support engineering
checks, but it is not held out and cannot qualify a production economic route or support a
real-provider savings claim.

## Findings and disposition

No critical or high finding remains open.

1. **High — closed: the cost gate used median per-run cost.** A cheap success plus expensive failed
   work could pass the old calculation even when total spend per successful task was worse than the
   fixed-quality baseline. `compare_policies` now derives the reduction from each policy's total
   spend divided by independently successful tasks. Median cost remains diagnostic only.
2. **High — closed: a synthetic report did not carry an enforceable qualification boundary.** An
   offline report now has an explicit `synthetic_offline` evidence class and a schema-enforced
   `production_qualified = false`. Markdown output says that passing synthetic gates is not
   production qualification.
3. **High — closed: future-dated reports passed the freshness check.** The offline release validator
   now rejects timestamps after the verifier's current time as well as naive or expired timestamps.
4. **Medium — closed: serialized rows could claim completion without passing their oracle.** Policy
   summaries now count a success only when both runtime completion and the independent oracle pass;
   mismatched rows are failed work and their spend remains in the denominator.
5. **Medium — closed for Phase 16: the visible curated workload could be mistaken for held-out
   evidence.** Manifest 1.1.2 explicitly records `evidence_class = "synthetic_offline"` and
   `held_out = false`. The source digests remain frozen and verified; this corpus is not eligible for
   live economic qualification.
6. **Medium — assigned to Phase 17: the legacy release checker still consumes serialized scored
   rows and comparison fields instead of independently rebuilding every gate from bound raw
   evidence.** Release sign-off remains withheld. Phase 17 owns fail-closed raw/source/platform
   recomputation and forged-summary adversarial cases before this checker can support a candidate.

## Independent recomputation

A fresh two-fixture, five-policy run produced ten controller cells. A separate calculation over its
raw usage records and scored completion rows reproduced, for every policy, two successes, total
cost `$0.004`, and cost per success `$0.002`. It also independently confirmed that every raw cost
equalled the sum of its usage records and that fixed economy/quality assignments used only their
pinned model with manual routing.

A separate one-fixture `paired-runtime-v1` run retained all 50 policy/seed/repetition cells. An
independent median calculation reproduced seed speedups of 40.97% and 38.40%, with a 2.57-point
spread. This small review sample is a mechanics check, not a replacement for Phase 15's complete
six-fixture result and not economic qualification. Its synthetic cost gate remained failed.

## Isolation checkpoint

Focused controller and boundary tests demonstrate:

- changing an oracle changes scoring without changing the raw execution record;
- suppressing writes makes a required mutation fail through `RunController`;
- fixed economy and quality policies pin both lead and delegated assignments;
- dirty and untracked workspace inputs are content-addressed without mutating the source workspace;
- disjoint worktree writers may overlap, while canonical integration remains serialized;
- an interrupted apply becomes `in_doubt` and is not replayed;
- network and external-effect commands require approval; and
- batch admission retains and later releases one lead continuation allowance.

Platform capability tests may skip when the local Windows account cannot create a hard link,
symbolic link, or junction. These skips exercise fail-closed setup paths and do not waive the
corresponding boundary.

## Claims that remain unproven

- real-provider completion parity with a capable direct baseline;
- at least 20% lower live aggregate cost per successful request;
- held-out live quality, latency, cost, and safety qualification;
- production promotion of any novel economic strategy;
- exact-candidate Windows/Linux release readiness; and
- publication or tag eligibility.

Those claims require Q1 or later release phases and their separately authorized evidence. No live
provider, paid evaluation, push, publication, remote change, or tag was performed in Phase 16.
