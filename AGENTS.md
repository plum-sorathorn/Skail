# Repository Guidelines

Skail is a Python 3.12+ native, budget-aware multi-agent coding harness. The console command is
`skail` (entry point `skail.cli.main:main`); the distribution is `skail-harness`.

## Setup

```powershell
python -m pip install -e ".[dev]"   # pyproject.toml is the only dependency/build config
```

Python >= 3.12; CI covers 3.12-3.14. Extras: `dev`, `openai-compatible`/`openai`, `anthropic`.
`langchain-openai` and `langchain-anthropic` are pinned to exact versions in those extras.

## Commands

CI runs these in order - match the order locally:

```powershell
python -m ruff check src tests scripts evals   # 100-char lines, rules E,F,I,UP
python -m mypy src/skail                       # strict
python -m pytest tests/unit tests/contract -m "not provider_live" -q
python scripts/smoke.py                        # offline package/CLI smoke check
python -m pytest -q                            # full offline suite
python -m pytest tests\unit\test_x.py::test_y -q   # single test
```

`rtk pytest ...` is the preferred wrapper. Release checks: `python scripts/package_check.py` then
`python scripts/release_check.py`. `python -m build` produces the distribution.

## Testing quirks

- `addopts` includes `--strict-markers` and `--strict-config`: a new `@pytest.mark.*` must be
  registered under `[tool.pytest.ini_options] markers` in `pyproject.toml` or collection fails.
  Existing markers: `unit`, `contract`, `integration`, `e2e`, `provider_live`.
- `asyncio_mode = "auto"` - do not add `@pytest.mark.asyncio`.
- `pythonpath` includes `tests`, so test doubles import as `from fakes.provider import
  FakeProviderAdapter, FakeProviderChatModel` and `from fakes.models import ScriptedChatModel`.
  There is no shared fixture for them; construct the fake inline in the test.
- `provider_live` tests are skipped unless `--run-provider-live` is passed AND the env vars named in
  the marker kwarg are set, e.g. `@pytest.mark.provider_live(env=("LLMGATEWAY_API_KEY",))`. The fake
  provider is the default for all routine work.
- `tests/conftest.py` has an autouse fixture that fails the session if a `.skail/` runtime dir
  exists, but only when `SKAIL_ASSERT_CLEAN_TEST_ROOT=1`.
- `import-mode=importlib` and `pythonpath` mean test dirs need no `__init__.py`.

## Evals

Deterministic and offline (scripted model responses, fixed seed):

```powershell
python scripts/eval_routing.py --fixtures evals/fixtures --policies all --seed 42 --output out/audit-eval.json --markdown out/audit-eval.md
```

## Layout

- `src/skail/`: `cli` (entry point), `runtime`, `agents`, `routing`, `providers`, `sessions`,
  `tools`, `tui`, `config`, `domain`.
- `tests/`: `unit`, `contract`, `integration`, `e2e`, `security`, plus `fakes/` (test doubles) and
  `fixtures/`. `scripts/`: smoke, eval, and release checks.
- `docs/skail/`: specification, architecture, feature contracts, CLI. Decisions live in
  `docs/decisions/` (ADRs 0001-0006).
- Generated or non-source, do not hand-edit or commit: `.skail/`, `out/`, `evals/results/`,
  `graphify-out/`, `build/`, `run_logs/`. `design/` is reference assets.

## Architecture constraints

- Framework and provider types stay behind adapters; no caller outside an adapter imports framework
  Agent/Protocol types. `TaskExecutor` is the seam for async subagents.
- Skail-owned semantics that may not be delegated to prompts: task IDs and parentage, budget gates,
  model stickiness, concurrency leases, trust/approval/permissions, context scope.
- Direct launch only - no proxies or daemons. At most two child attempts per task, hard maximum
  three concurrent children, and only the lead creates first-level tasks. Assignments are
  immutable; escalation creates a new assignment. Task packets do not inherit the lead transcript
  by default.
- Shared workspace writers must not overlap. Enforce filesystem, shell, trust, approval, and
  secret-redaction boundaries in code, never in prompts.

## Workflow

- Query Graphify before unfamiliar exploration (`graphify query "..."`); run `graphify update .`
  after changes. Invoke it as plain `graphify` - never via npx/npm exec.
- Read the relevant spec, architecture section, feature contract, and ADR before editing.
- Definition of done: acceptance criteria covered by tests where deterministic; focused tests pass
  before the full affected suite; stable error codes; contract tests for new framework assumptions;
  no secrets or unrestricted tool output in logs, events, or fixtures; no unrelated reformatting;
  spec/ADR updated in the same task when a public contract changes.
- Conventional Commits, e.g. `fix(workspaces): confine child tool roots`. PRs list verification
  commands, risks, and follow-ups.
- A root `.env` exists and is gitignored - never read it into output or commit it.
- `.gitattributes` forces LF on `evals/fixtures/*.json`; on Windows, writing CRLF there rewrites the
  whole file in diffs.

## Style

Type hints, four-space indentation, `snake_case` functions/modules, `PascalCase` classes. Add or
update tests before changing behavior.
