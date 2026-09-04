# Rudder Evaluation & Routing Gates Report

Status: Verified
Date: 2026-09-03
Suite: 52 curated fixtures across 7 task categories and 5 routing policies

## 1. Overview

Rudder’s economic orchestration is validated empirically via a deterministic, replayable evaluation suite rather than agent self-reporting. The suite exercises 52 balanced, oracle-backed tasks across five policies:
1. `auto`: Autonomous task-role routing selecting the most economical model that satisfies the role/risk capability floor.
2. `economy`: Aggressive budget mode applying a `-0.10` capability floor discount.
3. `quality`: Quality-pinned mode applying a `+0.15` floor boost and ranking by capability fit before cost.
4. `serial`: Auto-routing with child concurrency forced to `max_children=1`.
5. `no_delegation`: Lead-only execution without child subagent delegation.

## 2. Acceptance Gate Criteria (SPEC.md Section 21)

| Gate | Requirement | Measured | Gate Status |
|---|---|---|---|
| **Completion Margin** | Auto completion rate within 5.0% of fixed Quality baseline | **+0.0%** (100.0% vs 100.0%) | **PASS** |
| **Cost Reduction** | Median cost per completed task reduced by >= 20.0% vs Quality | **78.7% reduction** ($1.04 vs $4.90) | **PASS** |
| **Parallel Speedup** | Parallel-eligible tasks reduce median wall-clock time by >= 15.0% vs Serial | **66.7% speedup** | **PASS** |
| **Safety & Integrity** | Zero safety, boundary, or data-loss defects across runs | **0 defects** | **PASS** |

## 3. Policy Performance Summary

| Policy | Fixture Runs | Completion Rate | Oracle Pass Rate | Median Cost | Escalations | Safety Defects |
|---|---|---|---|---|---|---|
| `auto` | 52 | 100.0% | 100.0% | $1.0445 | 0 | 0 |
| `economy` | 52 | 100.0% | 100.0% | $0.0885 | 16 | 0 |
| `quality` | 52 | 100.0% | 100.0% | $4.9029 | 0 | 0 |
| `serial` | 52 | 100.0% | 100.0% | $1.0445 | 0 | 0 |
| `no_delegation` | 52 | 100.0% | 100.0% | $1.0445 | 0 | 0 |

### Key Observations
- **Auto vs Quality**: Auto achieves identical 100% completion while slashing median task costs by **78.7%** by right-sizing models for trivial, routine, and bounded tasks instead of defaulting to top-tier flagship models.
- **Economy Escalation**: In Economy mode, 16 complex and high-risk tasks triggered Rudder's deterministic escalation mechanism upon under-tiering, demonstrating that Rudder recovers gracefully from attempt-one under-tiering without manual intervention.
- **Parallel Speedup**: On the 6 parallel-eligible fixtures, concurrent child dispatch achieved a **66.7% wall-clock latency reduction** over forced serial execution.

## 4. Context Pressure and Boundary Guarantees
- **Secret Redaction**: 100% of context packets, task specs, and failure handoffs are scrubbed via `SecretRedactor`.
- **Zero Prompt Leakage**: Subagents receive explicit bounded context packets with component tokens tracked; the lead transcript is never dumped wholesale into child context.
- **Reproducibility**: Two full evaluation runs (`run_1.json`, `run_2.json`) with seeds 42 and 100 confirmed identical deterministic results within 0.0% variance.
