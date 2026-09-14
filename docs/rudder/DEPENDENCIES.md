# Rudder Dependency and License Audit

Status: Active
Audit date: 2026-09-13

## Scope and method

This is a direct-runtime-dependency audit of the versions declared in `pyproject.toml`, checked
against installed package metadata and the [OSV vulnerability database](https://osv.dev/). It is
not a claim that every resolved transitive dependency is locked: Rudder currently has no lockfile,
so a clean-candidate audit must repeat the resolved dependency check before release.

## Direct runtime dependencies

| Package | Declared / observed version | License | Audit result |
| --- | --- | --- | --- |
| deepagents | 0.7.13 / 0.7.13 | MIT | No matching direct-package OSV finding identified. |
| langchain | 1.3.18 / 1.3.18 | MIT | No matching direct-package OSV finding identified. |
| langchain-core | 1.6.1 / 1.6.1 | MIT | No matching direct-package OSV finding identified. |
| langgraph | 1.2.11 / 1.2.11 | MIT | No matching direct-package OSV finding identified. |
| langgraph-checkpoint | 4.2.0 / 4.2.0 | MIT | Not affected by [GHSA-fjqc-hq36-qh5p](https://osv.dev/vulnerability/GHSA-fjqc-hq36-qh5p), which is fixed in 4.1.1. |
| langgraph-checkpoint-sqlite | 3.1.1 / 3.1.1 | MIT | At the fixed version for [GHSA-47pj-3jcm-6whg](https://github.com/advisories/GHSA-47pj-3jcm-6whg). |
| httpx | `>=0.28,<1` / 0.28.1 | BSD-3-Clause | No matching direct-package OSV finding identified; the non-exact range requires candidate-time resolution evidence. |
| textual | `>=1.0.0` / 1.0.0 | MIT | No matching direct-package OSV finding identified; the non-exact range requires candidate-time resolution evidence. |

The two LangGraph checkpoint findings above were reviewed on 2026-09-13. They are not release
findings for the declared installed versions. Findings for `langgraph-api`, JavaScript packages,
Redis checkpointing, or PostgreSQL checkpointing do not apply to this local SQLite application
because those packages and server modes are not dependencies or runtime surfaces here.

## Release limitations

Direct metadata licensing is permissive (MIT or BSD-3-Clause), but downstream notices and any
candidate-specific transitive advisories must be regenerated from the exact built artifact. A
future advisory or a different resolver result is actionable release work, not waived by this
record.
