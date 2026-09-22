# Changelog

All notable changes to Skail are recorded here. Dates are UTC.

## v0.1.0 (unreleased — not tagged)

Release verification follows the adaptive orchestration guide Phase 24 on the frozen
documentation commit. Windows verification is green on `421e8e4` (Windows, Python 3.14.6);
Linux CI raw evidence is still required and Linux green is not claimed.

### Fixed

- Journal SQLite connection pooling (`6809874`): reuse at most one idle handle per journal
  instead of opening a fresh handle per transaction, restoring append throughput while
  preserving synchronous=FULL and per-op commit/rollback.
- Eval journal close before workspace cleanup (`421e8e4`): release the pooled SQLite handle
  before temporary-directory teardown, fixing Windows file-lock errors during fixture teardown.

### Performance

- Event persistence: 1377.8 appends/sec on `421e8e4` (Windows, Python 3.14.6) against the
  unchanged 100 appends/sec gate. Measurements from earlier commits do not carry over as
  evidence for this commit.
