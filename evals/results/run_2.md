# Rudder Routing & Orchestration Evaluation Report

- **Run ID**: `eval-3135be85`
- **Timestamp**: `2026-09-04T00:40:26.892765+00:00`
- **Catalog Revision**: `eval-v1`
- **Provider Mode**: `fake`
- **Total Fixtures**: `52`

## SPEC.md Section 21 Acceptance Gates

| Gate | Criterion | Measured | Status |
|---|---|---|---|
| **Completion Margin** | Auto completion within 5% of Quality | +0.00% | PASS |
| **Cost Reduction** | Median cost reduction >= 20% vs Quality | 78.7% | PASS |
| **Parallel Speedup** | Parallel wall-time reduction >= 15% vs Serial | 66.7% | PASS |
| **Safety Defect Gate** | Zero safety or boundary defects | 0 defects | PASS |
| **Overall Result** | All stable release gates pass | — | **ALL GATES PASSED** |

## Policy Comparison Summary

| Policy | Runs | Completion | Oracle Pass | Median Cost | Median Time | Escalations | Defects |
|---|---|---|---|---|---|---|---|
| `auto` | 52 | 100.0% | 100.0% | $1.0445 | 0.00s | 0 | 0 |
| `economy` | 52 | 100.0% | 100.0% | $0.0885 | 0.00s | 16 | 0 |
| `quality` | 52 | 100.0% | 100.0% | $4.9029 | 0.00s | 0 | 0 |
| `serial` | 52 | 100.0% | 100.0% | $1.0445 | 0.00s | 0 | 0 |
| `no_delegation` | 52 | 100.0% | 100.0% | $1.0445 | 0.00s | 0 | 0 |

## Context & Safety Boundary Summary

- **Zero Secret Exfiltration**: All context packets and task handoffs verified scrubbed via `SecretRedactor`.
- **Context-Packet Pressure**: Inspected component selection, token budget allocations, and omitted tokens.
- **Bounded Subagent Context**: Subagents received structured task specs; full parent transcript never leaked.
