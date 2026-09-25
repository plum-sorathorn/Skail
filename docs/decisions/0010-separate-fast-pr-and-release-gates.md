# ADR 0010: Separate the required fast PR gate from release validation

Status: Accepted  
Date: 2026-09-24

## Context

`ci.yml` and `release.yml` both ran on pull requests to `main` and `skail`. The overlap repeated
Ruff, mypy, smoke, and the Python 3.12 Windows/Linux test work, while release validation also built
and inspected a wheel that `package_check.py` had already built in the same job.

## Decision

1. `ci.yml` is the required pull request gate. Its matrix retains Windows and Linux on Python 3.12,
   3.13, and 3.14. Each matrix job runs Ruff over `src`, `tests`, `scripts`, and `evals`, strict
   mypy, unit/contract tests, and the fake-provider smoke check.
2. A single `CI / Required fast gate` job aggregates the complete matrix result. Branch protection
   should require that stable aggregate check rather than each matrix job or the release workflow.
3. `release.yml` runs on `v*` tags and manual `workflow_dispatch`, not on pull requests or branch
   pushes. Its Windows/Linux Python 3.12 matrix runs the full offline suite, smoke, package checks,
   isolated wheel installation, and release validation. The Python 3.12–3.14 Windows/Linux matrix
   remains covered by the required CI workflow.
4. The release job runs `package_check.py` before pytest and writes its verified wheel and sdist to
   the runner temporary directory. `test_packaging.py` and the release checker inspect that same
   wheel through `SKAIL_PACKAGE_ARTIFACT_DIR` and `--artifact-dir`; both retain the real built-wheel
   boundary without building a second copy in that job. Local and fast-PR test runs still build a
   wheel independently when no artifact directory is supplied.

## Required-check migration

For the `main` and `skail` branch protection rules, make `CI / Required fast gate` the required
status check. Remove the old required `CI / <os> / Python <version>` matrix contexts and
`Release CI / Test & Build (<os>)` contexts after this workflow change is installed. Keep release
workflow results visible on version tags and manual runs; they are not required PR checks.

The branch protection rules live in repository hosting settings and are not represented in this
worktree. Apply the migration above there when installing this workflow revision.

## Consequences

- Each pull request has one stable required check while still exercising all six supported
  platform/interpreter combinations.
- Release tags retain full-suite Windows/Linux validation and package evidence without duplicating
  the wheel build inside the same job.
- The release gate may be started manually for a candidate branch without making every branch push
  wait for release-scale evaluation.
