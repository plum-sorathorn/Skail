# Rudder CLI Specification and Contract

The command line interface for Rudder is `rudder`.

## 1. Invocation Syntax

```text
rudder [PROMPT...]
rudder -p|--print [PROMPT...]
rudder --json [PROMPT...]
rudder -c|--continue
rudder -r|--resume [SESSION_ID]
rudder --no-session
rudder --mode auto|economy|quality|manual
rudder --model PROVIDER:MODEL
rudder --lead-model PROVIDER:MODEL
rudder --agent-model PROFILE=PROVIDER:MODEL
rudder --budget USD
rudder --max-agents 1|2|3
rudder --delegation auto|ask|off
rudder --workspace shared|worktree
rudder --approve-project|--deny-project
rudder auth ...
rudder models ...
rudder sessions ...
rudder config ...
rudder smoke --fake-provider
```

## 2. Exit Codes

Rudder uses standardized, deterministic process exit codes:

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

### 3.2 JSONL Mode (`--json`)

Machine-readable event streaming mode:
- **stdout**: Emits valid UTF-8 JSON lines, each encoding an `EventEnvelope` (schema version 1).
- **terminal event**: The final emitted JSON line is guaranteed to be a terminal lifecycle event: `run.completed`, `run.failed`, `run.blocked`, or `run.cancelled`.
- **stderr**: Reserved for fatal process-level panics or critical runtime errors.

## 4. Subcommands

### `rudder config`
- `rudder config show`: Display the effective layered configuration and provenance.
- `rudder config path`: Display filesystem paths for user/project configuration and data stores.

### `rudder sessions`
- `rudder sessions list`: List stored local sessions with ID, status, and timestamps.
- `rudder sessions show <session_id>`: Display overview of runs, tasks, and budget state for a session.
- `rudder sessions export <session_id> [--output PATH]`: Export redacted session record to JSON or file.
- `rudder sessions archive <session_id>`: Move session to archived status.
- `rudder sessions resume <session_id>`: Restore state and activate an interrupted or idle session.

### `rudder auth`
- `rudder auth status`: Report configuration state for known provider credentials without exposing secrets.
- `rudder auth check`: Verify configured provider credentials and endpoint connectivity.

### `rudder models`
- `rudder models list`: List available built-in agent profiles and configured provider models.
- `rudder models show <name>`: Display capability floors, tool permissions, and details for a profile or model.

### `rudder smoke`
- `rudder smoke --fake-provider`: Offline deterministic package smoke verification.

## 5. Security and Removed Architecture

Rudder is a native multi-agent harness that interacts directly with provider APIs. It does not run background daemons, HTTP proxy servers, or sidecar classifiers.

The following legacy commands and options are removed and will exit immediately with code `2` (`EXIT_USAGE`):
- Subcommands: `proxy`, `serve`, `oma`, `daemon`, `plugin`, `slm`.
- Options: `--proxy`, `--port`, `--host`.
