# AutoConduck to Rudder Repository Transition

Status: Approved and in progress
Date: 2026-09-02
Depends on: [SPEC.md](./SPEC.md), [ADR 0001](../decisions/0001-rudder-native-multi-agent-harness.md)

## 1. Goal

Create Rudder Harness as a clean product on a dedicated branch while retaining the current AutoConduck source as an inert, readable reference under `legacy/autoconduck/`.

This is a source-tree transition, not an end-user migration. Rudder will not read AutoConduck configuration, expose AutoConduck commands, run its proxy/plugin services, or provide a compatibility layer.

## 2. Transition rules

1. Preserve an immutable Git reference to the last AutoConduck state before moving files.
2. Create the new development branch before structural changes.
3. Use Git-aware moves so history remains traceable.
4. Keep old code importable only within its archived project, never from Rudder.
5. Replace root packaging, tests, instructions, and CI with Rudder-owned equivalents.
6. Do not maintain both products in the same root environment.
7. Consult legacy code only for explicitly approved concepts; do not port modules wholesale.
8. No migration helpers, deprecation warnings, or dual command aliases are required.

## 3. Branch and preservation sequence

Exact names may be adjusted to repository convention, but the intended sequence is:

```powershell
rtk git status
rtk git switch -c rudder
```

Before the move, create a clearly named commit or tag on the current AutoConduck state. Do not create a tag or branch automatically until the user approves the specification and implementation begins.

Recommended references:

- branch: `rudder`;
- preservation tag: `autoconduck-v0.5.2-final` if `0.5.2` accurately describes the checked-out state;
- first Rudder architecture commit: documentation and legacy relocation only.

Version accuracy must be verified from package metadata and Git history before tagging; the old AGENTS document contains conflicting historical version text.

## 4. Target repository layout

```text
/
  pyproject.toml                 Rudder packaging only
  README.md                      Rudder product readme
  AGENTS.md                      Rudder development rules
  src/rudder/                    new runtime
  tests/                         Rudder tests only
  evals/                         Rudder evaluation fixtures
  scripts/                       Rudder developer scripts only
  docs/rudder/                   product/architecture specifications
  docs/decisions/                Rudder ADRs
  docs/plans/archive/            completed historical plans
  tasks/                         active Rudder plan/checklist
  legacy/autoconduck/
    README.md                    archive status and usage warning
    pyproject.toml               old package metadata
    requirements.txt
    autoconduck/                 old runtime package
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

### Move into `legacy/autoconduck/`

- `autoconduck/`;
- existing AutoConduck `tests/`;
- existing AutoConduck `scripts/`;
- `npm-packaging/`;
- old `requirements.txt`;
- old `pyproject.toml` copied or moved before the Rudder one replaces it;
- old product README as `README.original.md`;
- AutoConduck-specific design, model catalog, changelog, reports, and phase documents;
- old project instructions as `AGENTS.md`;
- other packaging/runtime files discovered by the reviewed manifest.

### Keep at root

- repository license unless its terms require product-name edits;
- `.gitignore`, updated only for Rudder paths;
- Git metadata and platform-neutral repository settings;
- `docs/rudder/` and `docs/decisions/`;
- archived historical implementation plans;
- active Rudder `tasks/`.

### Replace at root

- `README.md`;
- `pyproject.toml`;
- `AGENTS.md`;
- `tests/`, `scripts/`, and other developer entrypoints;
- CI workflows and release configuration;
- Graphify output after the source layout changes.

### Inspect before deciding

- generic issue templates or contribution documents;
- assets that may contain AutoConduck branding;
- editor configurations;
- security policy and code of conduct;
- generated caches and build artifacts, which should generally not be archived.

## 6. Legacy archive contract

`legacy/autoconduck/README.md` must state:

- this directory is an inert reference snapshot;
- it is excluded from Rudder packaging, tests, type checks, Graphify scope where configurable, and normal CI;
- dependencies should not be installed alongside Rudder in the same environment;
- no security or compatibility maintenance is promised in this directory;
- fixes for the former product belong on its preserved branch/tag, not in the Rudder branch;
- Rudder runtime code may not import it.

The archive is kept so agents can inspect proven provider, pricing, Textual, deterministic failure, and accounting concepts when a Rudder task explicitly calls for that reference.

## 7. Packaging isolation

The root package must use a `src/` layout and include only `rudder*`. Required checks:

- built wheel contains `rudder` and no `autoconduck` package;
- installed console scripts include `rudder` and no `autoconduck`/`conduck` aliases;
- test discovery excludes `legacy/`;
- static/type/lint tooling excludes `legacy/`;
- runtime import scan finds no `legacy.autoconduck` or path manipulation into the archive;
- distribution metadata and descriptions contain Rudder branding.

The Python distribution name is `rudder-harness`. The console command is `rudder`.

## 8. Dependency disposition

The new root dependency list is derived from Rudder requirements, not copied from AutoConduck.

| Existing dependency area | Initial disposition |
|---|---|
| FastAPI / Uvicorn | Remove from core; no local HTTP server. |
| LiteLLM proxy extra | Remove from core; use LangChain/provider adapters. |
| ONNX / Outlines SLM stack | Remove. |
| LanceDB | Remove from initial runtime. |
| Textual | Retain if chosen for the new conversation-first TUI. |
| Pydantic | Retain for boundaries/config/events. |
| HTTPX | Retain only if provider/catalog adapters need direct HTTP. |
| YAML | Do not retain by inertia; Rudder's primary config is TOML. |
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

Each reuse requires a Rudder-native contract and test. Copying a module unchanged is not presumed safe.

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

- `Fail-soft` becomes explicit agent recovery and structured failure. Rudder must not turn genuine failures into successful-looking results.
- Per-turn routing becomes lead-run and task-attempt routing.
- Session bias becomes explicit attempt escalation.
- Plugin ledger becomes the authoritative local task/route/budget journal.
- Harness adapters disappear because Rudder owns the interaction loop.

## 10. User data and compatibility

AutoConduck data remains under `~/.autoconduck/`. Rudder uses `~/.rudder/` and never modifies or deletes the old directory.

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

- AutoConduck/autoconduck/conduck names;
- old console commands and environment variables;
- `~/.autoconduck` paths;
- proxy/plugin/OMA/SLM claims;
- old screenshots, package metadata, badges, and URLs.

Matches are acceptable only in migration/history documents or explicit legacy-boundary tests. A reviewed allowlist should document those exceptions.

## 12. Transition verification

### After relocation

- the legacy snapshot has the expected files and archive README;
- no untracked deletion occurred;
- Git recognizes moves where practical;
- the new root contains no runnable AutoConduck entrypoint;
- `graphify update .` reflects the target boundary.

### After Rudder skeleton

- `python -m pip install -e ".[dev]"` succeeds in a clean environment;
- `rudder --help` resolves to the new package;
- fake-provider smoke starts without AutoConduck, Node, ONNX, FastAPI, or LiteLLM proxy dependencies;
- built wheel inspection contains no legacy package;
- tests do not collect under `legacy/`;
- import-boundary test rejects any `src/rudder` dependency on `legacy` or `autoconduck`.

### Rollback

Because work occurs on a new branch and begins with a preservation reference, rollback means leaving the Rudder branch and returning to the previous branch/tag. The implementation must not use destructive history rewriting as a rollback method.

## 13. Completion criteria

The transition phase is complete when:

- the preservation reference is verified;
- all old runtime/support code is under the inert legacy boundary;
- root packaging and commands describe only Rudder;
- the minimal Rudder package, tests, and fake-provider smoke run on Windows;
- CI has an explicit Linux job ready for later implementation tasks;
- no migration helper or old alias exists;
- the reviewed diff contains only relocation, new skeleton, and documentation needed for the new boundary.
