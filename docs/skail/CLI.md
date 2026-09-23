# Skail CLI Specification and Contract

The command line interface for Skail Harness is `skail`.

## 1. Invocation Syntax

```text
skail [PROMPT...]
skail -p|--print [PROMPT...]
skail --jsonl|--json [PROMPT...]
skail -c|--continue
skail -r|--resume [SESSION_ID]
skail --no-session
skail --mode auto|economy|quality|manual
skail --model PROVIDER:MODEL
skail --lead-model PROVIDER:MODEL
skail --agent-model PROFILE=PROVIDER:MODEL
skail --budget USD
skail --max-agents 1|2|3
skail --delegation auto|ask|off
skail --workspace shared|worktree
skail --approve-project|--deny-project
skail auth ...
skail models ...
skail sessions ...
skail config ...
```

## 2. Exit Codes

Skail uses standardized, deterministic process exit codes:

| Exit Code | Name | Meaning |
|---|---|---|
| `0` | `EXIT_OK` | Run completed successfully; command executed without error. |
| `1` | `EXIT_FAILURE` | Unhandled error or task run failure. |
| `2` | `EXIT_USAGE` | Invalid command syntax, conflicting flags, missing required arguments, or attempted use of removed aliases. |
| `3` | `EXIT_BLOCKED` | Work was blocked by safety policy, project trust denial, or budget ceiling. |
| `4` | `EXIT_CANCELLED` | Execution was interrupted or cancelled by the user. |

## 3. Output Modes

### 3.1 Print Mode (`-p`, `--print`)

Non-interactive single-response mode:
- **stdout**: Contains strictly the final lead agent response text. No progress indicators, banners, or diagnostic logging.
- Registered secret values are redacted from the returned lead output before it is rendered.
- **stderr**: Contains progress logs, warnings, approvals, and error details.

### 3.2 JSONL Mode (`--jsonl`, with `--json` alias)

Machine-readable event streaming mode:
- **stdout**: Emits valid UTF-8 JSON lines, each encoding an `EventEnvelope` (schema version 1).
- **terminal event**: The final emitted JSON line is guaranteed to be a terminal lifecycle event: `run.completed`, `run.failed`, `run.blocked`, or `run.cancelled`.
- **interrupts**: `user.question`, `user.answer`, and `user.cancellation` carry a typed interrupt
  kind and stable ID. Question events use `kind=question`; expected graph waits are not failed tool
  calls.
- **completed output**: `run.completed.payload.output` preserves the redacted final model response. Valid JSON is emitted as structured JSON data; plain-text output remains a string.
- **invocation identity**: Every event emitted for one CLI invocation carries the same `invocation_id`, which is distinct from the resumable `run_id`.
- Exactly one terminal lifecycle event is emitted for an invocation that creates or resumes a persisted run. Failures before run persistence return the documented exit code without fabricating a terminal event.
- **stderr**: Reserved for fatal process-level panics or critical runtime errors.

## 4. Subcommands

### `skail config`
- `skail config show`: Display the effective layered configuration and provenance.
- `skail config path`: Display filesystem paths for user/project configuration and data stores.

### `skail sessions`
- `skail sessions list`: List stored local sessions with ID, status, and timestamps.
- `skail sessions show <session_id>`: Display overview of runs, tasks, and budget state for a session.
- `skail sessions export <session_id> [--output PATH]`: Export a redacted session record as JSON to stdout or a file.
- `skail sessions archive <session_id>`: Move session to archived status.
- `skail sessions resume <session_id>`: Restore state and activate an interrupted or idle session.

### `skail auth`
- `skail auth status`: Report configuration state for known provider credentials without exposing secrets.
- `skail auth check`: Report whether credentials are available from the environment or OS
  credential store; it does not contact a provider or reveal key material.

### `skail models`
- `skail models list`: List built-in profiles, selected provider models, and the last validated local LLMGateway catalog snapshot, including refresh age and price coverage.
- `skail models show <name>`: Display built-in profile details or local catalog fields, pricing, timestamps, and provenance for `PROVIDER:MODEL`.

Configured model names are listed independently from the validated catalog. Missing prices display
as unavailable; selecting an unpriced model does not qualify it for automatic hard-budget routing.
Unpriced manual assignment is limited to `manual` mode with no Skail hard budget or task limit.

The authenticated LLMGateway catalog is refreshed when `skail` starts and stored at
`~/.skail/catalog/llmgateway.json`. A transient refresh failure may use the last validated snapshot;
authentication, protocol, malformed-response, and empty-access failures remain actionable errors.
The snapshot is never a hardcoded model list and contains no credentials.

If no model has trusted capability evidence for automatic routing, interactive startup reaches a
model-selection state and opens the picker. Select a discovered model or use `--model
llmgateway:MODEL`; the explicit selection is persisted for future launches. Headless mode exits
promptly with a model-selection diagnostic instead of waiting indefinitely.

## 5. Global State, Themes, and Live Validation

Normal operation creates one Skail state root at `~/.skail`. Workspace configuration, approvals,
questions, artifacts, and locks are namespaced below that root; `skail config path` reports those
resolved paths. A repository-local `.skail` directory is legacy input only and is never created by
the CLI. Recognized legacy files are imported non-destructively and idempotently.

Onboarding choices are device-global and non-secret. Provider credentials resolve from an explicit
environment variable, then the OS credential store, then secure interactive entry. If secure
storage is unavailable, set the named environment variable; Skail never writes a key to TOML,
JSON, SQLite, logs, screenshots, or exported sessions. Project trust remains workspace-specific.

The picker is keyboard-only: printable input filters, Up/Down moves, Enter selects, Ctrl+Space
toggles the highlighted model, Ctrl+Shift+A toggles the filtered set, and Escape closes. Available
themes are Dark, Light, System, Pistachio Night, Pistachio Paper, and Mint Porcelain; preview is
temporary until Enter commits it.

Budget output distinguishes historical provider-authoritative actual, token-derived estimate,
conservative estimate, unknown cost, and reserved amount. New measured calls use token counts
and prices frozen on the assignment; provider-supplied dollar amounts do not settle the ledger.
The current-run budget total includes lead and child tasks; the TUI status strip shows cumulative
cost across the session's runs. Session export schema version 2 adds
`provider_calls` with token counts, call IDs, statuses, and frozen pricing, plus `model_usage`
totals across the session. An unresolved call makes its model's total cost null.

Provider-live validation is explicit and bounded:

```powershell
python scripts\live_check.py --max-cost-usd 1.00
```

The runner reads only allowlisted credential names from the repository `.env`, injects them into an
isolated child process, redacts diagnostics, and writes evidence only below ignored
`out/live-validation/`. It never falls back to fake execution.

## 6. Security and Removed Architecture

Skail is a native multi-agent harness that interacts directly with provider APIs. It does not run background daemons, HTTP proxy servers, or sidecar classifiers.

The following legacy commands and options are removed and will exit immediately with code `2` (`EXIT_USAGE`):
- Subcommands: `proxy`, `serve`, `oma`, `daemon`, `plugin`, `slm`.
- Options: `--proxy`, `--port`, `--host`.
