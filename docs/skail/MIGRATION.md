# Skail Repository Transition

Status: Approved and in progress
Date: 2026-09-02
Depends on: [SPEC.md](./SPEC.md), [ADR 0001](../decisions/0001-skail-native-multi-agent-harness.md)

## 1. Goal

Create Skail Harness as a clean product on a dedicated branch while retaining the archived
predecessor source as an inert, readable reference under `legacy/skail/`.

This is a source-tree transition, not an end-user migration. Skail does not read the archived
predecessor's configuration, expose its commands, run its proxy/plugin services, or provide a
compatibility layer.

## 2. Transition rules

1. Preserve an immutable Git reference to the last archived predecessor state before moving files.
2. Create the new development branch before structural changes.
3. Use Git-aware moves so history remains traceable.
4. Keep archived code importable only within its archived project, never from Skail.
5. Replace root packaging, tests, instructions, and CI with Skail-owned equivalents.
6. Do not maintain both products in the same root environment.
7. Consult legacy code only for explicitly approved concepts; do not port modules wholesale.
8. No migration helpers, deprecation warnings, or dual command aliases are required.

## 3. Branch and preservation sequence

Exact names may be adjusted to repository convention, but the intended sequence is:

```powershell
rtk git status
rtk git switch -c skail
```

Before the move, create a clearly named commit or tag on the archived predecessor state. Do not
create a tag or branch automatically until the user approves the specification and implementation
begins.

Recommended references:

- branch: `skail`;
- preservation tag: `legacy-v0.5.2-final` if `0.5.2` accurately describes the checked-out state;
- first Skail architecture commit: documentation and legacy relocation only.

Version accuracy must be verified from package metadata and Git history before tagging; the old AGENTS document contains conflicting historical version text.

## 4. Target repository layout

```text
/
  pyproject.toml                 Skail packaging only
  README.md                      Skail product readme
  AGENTS.md                      Skail development rules
  src/skail/                    new runtime
  tests/                         Skail tests only
  evals/                         Skail evaluation fixtures
  scripts/                       Skail developer scripts only
  docs/skail/                   product/architecture specifications
  docs/decisions/                Skail ADRs
  docs/plans/archive/            completed historical plans
  tasks/                         active Skail plan/checklist
  legacy/skail/
    README.md                    archive status and usage warning
    pyproject.toml               old package metadata
    requirements.txt
    skail/                       archived runtime package
    tests/
    scripts/
    npm-packaging/
    docs/                        old product documentation
    AGENTS.md                    old project instructions
    README.original.md           old root README
```

Root-level files shared by license or repository infrastructure should be evaluated rather than duplicated blindly.

## 5. Move manifest

The relocation task must produce and review an exact manifest before mutation. Expected classifications follow.

### Move into `legacy/skail/`

- `skail/`;
- archived predecessor `tests/`;
- archived predecessor `scripts/`;
- `npm-packaging/`;
- old `requirements.txt`;
- archived `pyproject.toml` copied or moved before the Skail one replaces it;
- old product README as `README.original.md`;
- archived design, model catalog, changelog, reports, and phase documents;
- old project instructions as `AGENTS.md`;
- other packaging/runtime files discovered by the reviewed manifest.

### Keep at root

- repository license unless its terms require product-name edits;
- `.gitignore`, updated only for Skail paths;
- Git metadata and platform-neutral repository settings;
- `docs/skail/` and `docs/decisions/`;
- archived historical implementation plans;
- active Skail `tasks/`.

### Replace at root

- `README.md`;
- `pyproject.toml`;
- `AGENTS.md`;
- `tests/`, `scripts/`, and other developer entrypoints;
- CI workflows and release configuration;
- Graphify output after the source layout changes.

### Inspect before deciding

- generic issue templates or contribution documents;
- assets that may contain Skail branding;
- editor configurations;
- security policy and code of conduct;
- generated caches and build artifacts, which should generally not be archived.

## 6. Legacy archive contract

`legacy/skail/README.md` must state:

- this directory is an inert reference snapshot;
- it is excluded from Skail packaging, tests, type checks, Graphify scope where configurable, and normal CI;
- dependencies should not be installed alongside Skail in the same environment;
- no security or compatibility maintenance is promised in this directory;
- fixes for the former product belong on its preserved branch/tag, not in the Skail branch;
- Skail runtime code may not import it.

The archive is kept so agents can inspect proven provider, pricing, Textual, deterministic failure, and accounting concepts when a Skail task explicitly calls for that reference.

## 7. Packaging isolation

The root package must use a `src/` layout and include only `skail*`. Required checks:

- built wheel contains `skail` and no archived package content;
- installed console scripts include `skail` and no archived compatibility aliases;
- test discovery excludes `legacy/`;
- static/type/lint tooling excludes `legacy/`;
- runtime import scan finds no dependency on the legacy archive or path manipulation into it;
- distribution metadata and descriptions contain Skail branding.

The Python distribution name is `skail-harness`. The console command is `skail`.

## 8. Dependency disposition

The new root dependency list is derived from Skail requirements, not copied from the archived
predecessor.

| Existing dependency area | Initial disposition |
|---|---|
| FastAPI / Uvicorn | Remove from core; no local HTTP server. |
| LiteLLM proxy extra | Remove from core; use LangChain/provider adapters. |
| ONNX / Outlines SLM stack | Remove. |
| LanceDB | Remove from initial runtime. |
| Textual | Retain if chosen for the new conversation-first TUI. |
| Pydantic | Retain for boundaries/config/events. |
| HTTPX | Retain only if provider/catalog adapters need direct HTTP. |
| YAML | Do not retain by inertia; Skail's primary config is TOML. |
| DeepAgents / LangGraph / LangChain | Add and pin after framework contract spikes. |
| SQLite async helper | Choose from actual concurrency/checkpointer needs during skeleton design. |

Provider integrations should be optional extras. The core environment must run fake-provider tests without commercial SDKs or credentials.

## 9. Concept disposition

### Reuse by redesign

- model pricing normalization;
- LLM Gateway and DevPass endpoint/auth knowledge;
- capability-floor terminology and explainability;
- deterministic repeated-call/error detection;
- off-hot-path usage/event accounting principles;
- selected TUI implementation techniques;
- model-catalog sync lessons.

Each reuse requires a Skail-native contract and test. Copying a module unchanged is not presumed safe.

### Do not port

- HTTP proxy routes and compatibility shims;
- plugin endpoints/runtime/spool/hook machinery;
- OMA sidecar and Node runner;
- SLM classifier/downloader/native-compat layer;
- proxy session guard and client prompt-prefix compatibility;
- agent-configuration mutation;
- daemon launcher/control;
- proxy-specific fail-soft semantics;
- old modes, commands, configuration keys, and user data paths.

### Special semantic changes

- `Fail-soft` becomes explicit agent recovery and structured failure. Skail must not turn genuine failures into successful-looking results.
- Per-turn routing becomes lead-run and task-attempt routing.
- Session bias becomes explicit attempt escalation.
- Plugin ledger becomes the authoritative local task/route/budget journal.
- Harness adapters disappear because Skail owns the interaction loop.

## 10. User data and compatibility

Pre-transition user data remains in its original location. Skail uses `~/.skail/` for current data
and never discovers, modifies, deletes, or automatically imports archived predecessor data.

There is no automatic import of:

- credentials;
- provider configuration;
- model presets;
- usage history;
- plugin/harness settings;
- sessions or ledgers.

Documentation may show users how to re-enter provider credentials safely, but must not encourage copying secrets into project files.

## 11. Branding replacement

The structural transition must scan active, non-legacy paths for:

- archived product names, console commands, and compatibility aliases;
- old console commands and environment variables;
- archived configuration and user-data paths;
- proxy/plugin/OMA/SLM claims;
- old screenshots, package metadata, badges, and URLs.

Matches are acceptable only in migration/history documents or explicit legacy-boundary tests. A reviewed allowlist should document those exceptions.

## 12. Transition verification

### After relocation

- the legacy snapshot has the expected files and archive README;
- no untracked deletion occurred;
- Git recognizes moves where practical;
- the new root contains no runnable predecessor entrypoint;
- `graphify update .` reflects the target boundary.

### After Skail skeleton

- `python -m pip install -e ".[dev]"` succeeds in a clean environment;
- `skail --help` resolves to the new package;
- fake-provider smoke starts without archived proxy/plugin code, Node, ONNX, FastAPI, or LiteLLM
  proxy dependencies;
- built wheel inspection contains no legacy package;
- tests do not collect under `legacy/`;
- import-boundary test rejects any `src/skail` dependency on the legacy archive.

### Rollback

Because work occurs on a new branch and begins with a preservation reference, rollback means leaving the Skail branch and returning to the previous branch/tag. The implementation must not use destructive history rewriting as a rollback method.

## 13. Completion criteria

The transition phase is complete when:

- the preservation reference is verified;
- all old runtime/support code is under the inert legacy boundary;
- root packaging and commands describe only Skail;
- the minimal Skail package, tests, and fake-provider smoke run on Windows;
- CI has an explicit Linux job ready for later implementation tasks;
- no migration helper or old alias exists;
- the reviewed diff contains only relocation, new skeleton, and documentation needed for the new boundary.
