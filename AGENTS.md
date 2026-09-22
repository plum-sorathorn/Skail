# Repository Guidelines

Skail is a Python 3.12+ native, budget-aware multi-agent coding harness. The console command is
`skail`; the distribution is `skail-harness`.

## Project Structure

- `src/skail/`: runtime, agents, routing, providers, sessions, tools, CLI, and TUI code.
- `tests/`: unit, contract, integration, end-to-end, and security tests.
- `evals/`: deterministic evaluation schemas, fixtures, and reports.
- `docs/skail/`: specification, architecture, feature contracts, and release documentation.
- `tasks/plan.md`: implementation phases and acceptance criteria.
- `scripts/`: smoke, evaluation, and release checks. `legacy/skail/` is inert.

## Development Commands

```powershell
python -m pip install -e ".[dev]"   # editable install
rtk pytest -q                       # offline test suite
rtk pytest tests\unit -q            # focused unit tests
python -m ruff check src tests scripts evals
python -m mypy src\skail
python scripts\smoke.py --fake-provider
python -m build
```

Use the fake provider by default. Live-provider tests are opt-in and require named credentials.

## Code Style and Testing

Use Python type hints, four-space indentation, `snake_case` functions/modules, and `PascalCase`
classes. Ruff enforces a 100-character line limit; mypy runs in strict mode. Add or update tests
before changing behavior, then run focused and affected suites plus the full offline suite.

## Architecture and Safety

Keep framework/provider types behind adapters. Preserve direct launch, immutable per-attempt model
assignments, at most two child attempts, and a hard maximum of three concurrent children. Shared
workspace writers must not overlap. Enforce filesystem, shell, trust, approval, and secret-redaction
boundaries in code; never rely on prompts alone. Do not import or address `legacy/skail/`.

## Contributions

Read the relevant specification, architecture section, feature contract, and accepted ADR before
editing. Query Graphify before unfamiliar exploration, use `apply_patch`, and run `graphify update .`
after changes. Review the complete diff before committing. Follow the existing Conventional Commit
style, for example `fix(workspaces): confine child tool roots` or `docs(plan): record a blocker`.
Pull requests should explain the change, list verification commands, identify risks or follow-ups,
and update relevant documentation or contracts.
