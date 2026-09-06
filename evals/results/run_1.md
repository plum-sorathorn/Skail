# Rudder Routing & Orchestration Evaluation Report

- **Run ID**: `eval-cc6eec5a`
- **Timestamp**: `2026-09-04T20:31:31.596975+00:00`
- **Catalog Revision**: `eval-v1`
- **Provider Mode**: `fake`
- **Total Fixtures**: `52`

## SPEC.md Section 21 Acceptance Gates

| Gate | Criterion | Measured | Status |
|---|---|---|---|
| **Completion Margin** | Auto completion within 5% of Quality | +0.00% | PASS |
| **Cost Reduction** | Median cost reduction >= 20% vs Quality | 78.7% | PASS |
| **Parallel Speedup** | End-to-end wall-time reduction >= 15% vs Serial | 23.4% | PASS |
| **Parallel Wall Time** | Auto / Serial full-wall medians | 1.25s / 1.63s | Informational |
| **Safety Defect Gate** | Zero safety or boundary defects | 0 defects | PASS |
| **Overall Result** | All stable release gates pass | — | **ALL GATES PASSED** |

## Policy Comparison Summary

| Policy | Runs | Completion | Oracle Pass | Median Cost | Median Time | Escalations | Defects |
|---|---|---|---|---|---|---|---|
| `auto` | 52 | 100.0% | 100.0% | $1.0445 | 0.26s | 0 | 0 |
| `economy` | 52 | 100.0% | 100.0% | $1.0445 | 0.27s | 0 | 0 |
| `quality` | 52 | 100.0% | 100.0% | $4.9029 | 0.27s | 0 | 0 |
| `serial` | 52 | 100.0% | 100.0% | $1.0445 | 0.26s | 0 | 0 |
| `no_delegation` | 52 | 100.0% | 100.0% | $1.0445 | 0.19s | 0 | 0 |

## Context Evidence Summary

- **Selected tokens (estimated)**: 12942
- **Recorded omissions**: 0
- **Observed artifact retrievals**: 0
- **Persisted failure-handoff bytes**: 0
