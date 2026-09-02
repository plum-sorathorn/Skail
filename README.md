# Rudder

Rudder is a local, provider-neutral coding harness for orchestrated multi-agent work within a
budget. It launches directly as `rudder`; it is not a proxy, daemon, plugin, or compatibility
layer for another coding agent.

The stable design uses one capable DeepAgents lead and as many as three synchronous child tasks.
Rudder owns task-bound model assignment, budget reservations, single-writer scheduling, safety,
recovery, and a versioned local event record.

## Development quick start

Python 3.12 or newer is required.

```powershell
python -m pip install -e ".[dev]"
rudder --help
python scripts\smoke.py --fake-provider
python -m pytest
```

The default suite is offline and credential-free. Provider-live tests require an explicit flag
and the provider's environment-variable credentials.

## Project status

Rudder is under implementation on the `rudder` branch. The approved contracts live in
[`docs/rudder/`](docs/rudder/README.md), with delivery tracked in [`tasks/plan.md`](tasks/plan.md).
The former AutoConduck product is an inert reference under [`legacy/autoconduck/`](legacy/autoconduck/README.md).

The provisional Python distribution name is `rudder-agent`; the executable is `rudder`.
