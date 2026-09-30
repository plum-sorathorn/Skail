# Skail Threat Model & Security Posture

Status: Active contract with residual-risk limits
Date: 2026-09-13
Reference: ADR 0006, ADR 0005, SPEC.md Section 20

## 1. System Architecture & Trust Boundaries

Skail executes locally as a developer pairing tool without cloud daemons, proxy servers, or plugin planes. Trust boundaries are enforced in deterministic application code, never via model prompt compliance.

```
+-------------------------------------------------------------------+
| USER WORKSTATION                                                  |
|                                                                   |
| [User / Terminal] <---> [CLI / TUI Presentation]                  |
|                                 |                                 |
| ===================== TRUST BOUNDARY 1 ========================== |
|                                 v                                 |
|                      [RunController Engine]                       |
|                      - Task Registry & Leases                     |
|                      - Budget Ledger (SQLite)                     |
|                      - Secret Redactor                            |
|                                 |                                 |
| ===================== TRUST BOUNDARY 2 ========================== |
|          |                      |                       |         |
|          v                      v                       v         |
| [Model Providers]      [Workspace Filesystem]     [Shell Engine]  |
| - API keys out-of-band - FilesystemBoundary       - ExecutionPol. |
| - Response schema val  - Symlink & junction check - ApprovalStore |
| - Usage normalization  - Sensitive pattern block  - Policy checks |
+-------------------------------------------------------------------+
```

## 2. Threat Analysis & Mitigations

### 2.1 Workspace Boundary & File Access Escape
- **Threat**: Adversarial path traversal (`../../`, UNC shares, symlink/junction hops) to read or write files outside the user-selected workspace.
- **Mitigation**: `FilesystemBoundary` strictly enforces that all resolved paths (with symlinks followed) remain inside `workspace.resolve()`. Canonical grants outside the workspace require exact, non-wildcard file path entries.
- **Sensitive Path Guard**: Common credential patterns (`.env`, `id_rsa`, `*.pem`, `*.key`, `.git`, `.skail`) cannot be read into agent context without explicit elevation.

### 2.2 Shell Execution & Command Injection
- **Threat**: Malicious prompt injections chaining commands (`; rm -rf /`, `& del /f`, piping to netcat or curl).
- **Mitigation**: `ExecutionPolicy` strictly rejects destructive executables (`rm`, `rmdir`, `del`, `format`, `shutdown`, `sudo`, `runas`, `git clean -fdx`, `git reset --hard`) and rejects commands executed outside the workspace CWD.
- **Human Approval**: Shell interpreters (`bash`, `sh`, `pwsh`, `cmd`) and external network commands
  (`curl`, `wget`, `ssh`, `git push`) require explicit human approval via `ApprovalStore`.
  Ordinary allowlisted build, test, and read commands may run in an approved trusted project;
  unknown commands still require approval. `ALLOW_ONCE` grants are consumed immediately.

### 2.3 Untrusted Project Extensions & Configuration
- **Threat**: Repository contains malicious `.skail/agents/` or `.skail/skills/` attempting privilege escalation.
- **Mitigation**: Project configurations remain completely inactive until the project trust record is explicitly promoted to `ProjectTrustLevel.TRUSTED`. Even when trusted, custom profiles cannot exceed the global permission ceiling.

### 2.4 Credential & Secret Exfiltration
- **Threat**: API keys, bearer tokens, SSH private keys, or passwords leaking into lead conversation transcripts, subagent context packets, or exported session dumps.
- **Mitigation**: `SecretRedactor` automatically scrubs registered secrets and standard auth patterns (`[REDACTED]`). Bounded subagent context packets never inherit the full parent conversation transcript. Session exports pass through full redaction before serialization.

### 2.5 Crash Recovery, Leases, and Budget State
- **Threat**: Process termination or crash corrupts SQLite state, duplicates charges, or strands shared workspace write locks.
- **Mitigation**:
  - `BudgetLedger` uses idempotent reservation keys and transactional SQLite operations. Double-settlement of reservations is rejected.
  - `WorkspaceLeaseManager` supports `recover_stale()` to reclaim stranded locks without deadlocking subsequent tasks.
  - `process_file_lock` uses atomic OS file locking with timeouts to prevent multi-process session race conditions.

## 3. Documented Limitations & Residual Risks

1. **Host-Level Permissions**: Skail operates with the permissions of the invoking user. While `ExecutionPolicy` and `FilesystemBoundary` prevent agent-initiated breakout, running Skail as `root` or `Administrator` is discouraged.
2. **Untrusted Workspace Scripts**: Code executed during project testing (e.g. `pytest` or `cargo test`) executes natively. Users must only mark projects as trusted if they trust the codebase's test suite.
3. **Live Provider Telemetry**: When configured with external commercial APIs, prompts sent to providers are governed by the respective provider's data retention policies. Secret redaction occurs prior to request dispatch.
4. **Application boundary, not host control**: The tested filesystem, command, trust, and redaction controls constrain Skail's application paths. They do not guarantee zero host compromise, zero secret leakage through a trusted program, or control over a privileged external process.
