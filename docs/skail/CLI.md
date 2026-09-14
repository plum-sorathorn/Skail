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
skail smoke --fake-provider
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
- **stderr**: Contains progress logs, warnings, approvals, and error details.

### 3.2 JSONL Mode (`--jsonl`, with `--json` alias)

Machine-readable event streaming mode:
- **stdout**: Emits valid UTF-8 JSON lines, each encoding an `EventEnvelope` (schema version 1).
- **terminal event**: The final emitted JSON line is guaranteed to be a terminal lifecycle event: `run.completed`, `run.failed`, `run.blocked`, or `run.cancelled`.
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
- `skail auth check`: Report whether known provider credential environment variables are configured; it does not contact a provider.

### `skail models`
- `skail models list`: List built-in profiles and the deterministic fake models. Configured production providers are resolved at run time.
- `skail models show <name>`: Display details for a built-in profile, or echo an otherwise unverified model/profile name.

### `skail smoke`
- `skail smoke --fake-provider`: Offline deterministic package smoke verification.

## 5. Security and Removed Architecture

Skail is a native multi-agent harness that interacts directly with provider APIs. It does not run background daemons, HTTP proxy servers, or sidecar classifiers.

The following legacy commands and options are removed and will exit immediately with code `2` (`EXIT_USAGE`):
- Subcommands: `proxy`, `serve`, `oma`, `daemon`, `plugin`, `slm`.
- Options: `--proxy`, `--port`, `--host`.
