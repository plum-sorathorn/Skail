"""Main entrypoint — thin delegation to cli.main; preserves app for uvicorn string targets."""

from __future__ import annotations

import sys

from autoconduck import cli as _cli
from autoconduck import server as _server

try:
    from autoconduck.server import app as _app  # noqa: F401
    app = _app
except Exception:
    app = None  # type: ignore[assignment]

from autoconduck.cli import (  # noqa: F401
    cmd_edit as _orig_cmd_edit,
    cmd_ensure as _orig_cmd_ensure,
    cmd_install as _orig_cmd_install,
    cmd_launch_agent as _orig_cmd_launch_agent,
    cmd_release as _orig_cmd_release,
    cmd_reset as _orig_cmd_reset,
    cmd_start as _orig_cmd_start,
    cmd_stats as _orig_cmd_stats,
    cmd_stop as _orig_cmd_stop,
    cmd_uninstall as _orig_cmd_uninstall,
    cmd_update as _orig_cmd_update,
    main as _orig_cli_main,
)
import autoconduck.cli.cli as _cli_sub

cmd_edit = _orig_cmd_edit
cmd_ensure = _orig_cmd_ensure
cmd_install = _orig_cmd_install
cmd_launch_agent = _orig_cmd_launch_agent
cmd_release = _orig_cmd_release
cmd_reset = _orig_cmd_reset
cmd_start = _orig_cmd_start
cmd_stats = _orig_cmd_stats
cmd_stop = _orig_cmd_stop
cmd_uninstall = _orig_cmd_uninstall
cmd_update = _orig_cmd_update

from autoconduck.server import (  # noqa: F401
    DEFAULT_PORT,
    _check_port_available as _orig_check_port_available,
    _find_free_port as _orig_find_free_port,
    _run_proxy as _orig_run_proxy,
    _run_supervisor as _orig_run_supervisor,
)

_check_port_available = _orig_check_port_available
_find_free_port = _orig_find_free_port
_run_proxy = _orig_run_proxy
_run_supervisor = _orig_run_supervisor

# Snapshot originals for patch propagation (exclude entry points that are themselves wrappers)
_ORIG_CLI = {
    "cmd_edit": _orig_cmd_edit,
    "cmd_ensure": _orig_cmd_ensure,
    "cmd_install": _orig_cmd_install,
    "cmd_launch_agent": _orig_cmd_launch_agent,
    "cmd_release": _orig_cmd_release,
    "cmd_reset": _orig_cmd_reset,
    "cmd_start": _orig_cmd_start,
    "cmd_stats": _orig_cmd_stats,
    "cmd_stop": _orig_cmd_stop,
    "cmd_uninstall": _orig_cmd_uninstall,
    "cmd_update": _orig_cmd_update,
    "main": _orig_cli_main,
}


def _sync_patches() -> None:
    for name, orig in _ORIG_CLI.items():
        cur = globals().get(name)
        if cur is not orig and cur is not None:
            try:
                setattr(_cli, name, cur)
            except Exception:
                pass
            try:
                setattr(_cli_sub, name, cur)
            except Exception:
                pass
    for extra in ("load_config", "home_dir", "subprocess", "sys", "time", "shutil"):
        if extra in globals():
            cur = globals()[extra]
            try:
                if getattr(_cli, extra, None) is not cur:
                    setattr(_cli, extra, cur)
                    setattr(_cli_sub, extra, cur)
            except Exception:
                pass


def _build(*args, **kwargs):  # type: ignore[no-untyped-def]
    global app
    result = _server._build(*args, **kwargs)
    try:
        app = _server.app
    except Exception:
        pass
    return result


def _get_app(*args, **kwargs):  # type: ignore[no-untyped-def]
    global app
    result = _server._get_app(*args, **kwargs)
    try:
        app = _server.app
    except Exception:
        pass
    return result


SUPERVISOR_MAX_RAPID_FAILURES = 5
SUPERVISOR_FAILURE_WINDOW = 60.0
SUPERVISOR_INITIAL_BACKOFF = 1.0
SUPERVISOR_MAX_BACKOFF = 30.0

for _name in ("SUPERVISOR_MAX_RAPID_FAILURES", "SUPERVISOR_FAILURE_WINDOW", "SUPERVISOR_INITIAL_BACKOFF", "SUPERVISOR_MAX_BACKOFF"):
    try:
        setattr(_server._impl, _name, globals()[_name])  # type: ignore[attr-defined]
    except Exception:
        pass


def _run_supervisor_impl(port, log_level="info", host="127.0.0.1", child_cmd=None):  # type: ignore[no-untyped-def]
    for _n in ("SUPERVISOR_MAX_RAPID_FAILURES", "SUPERVISOR_FAILURE_WINDOW", "SUPERVISOR_INITIAL_BACKOFF", "SUPERVISOR_MAX_BACKOFF"):
        try:
            setattr(_server._impl, _n, globals()[_n])  # type: ignore[attr-defined]
        except Exception:
            pass
    # Propagate auxiliary patches (time.sleep, subprocess.Popen, home_dir) so tests
    # patching autoconduck.main.* affect the supervisor loop.
    for _extra in ("time", "subprocess", "home_dir"):
        if _extra in globals():
            try:
                setattr(_server._impl, _extra, globals()[_extra])  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                import autoconduck.server.server_streaming as _ss

                setattr(_ss, _extra, globals()[_extra])
            except Exception:
                pass
    # Call the original impl directly — never via _server._run_supervisor which may have been monkeypatched to this wrapper
    return _orig_run_supervisor(port, log_level, host, child_cmd)


# Export as _run_supervisor (tests patch autoconduck.main._run_supervisor)
_run_supervisor = _run_supervisor_impl  # type: ignore[assignment]


def main(argv=None):  # type: ignore[no-untyped-def]
    _sync_patches()
    return _orig_cli_main(argv)


def _cmd_start_wrapper(args):  # type: ignore[no-untyped-def]
    _sync_patches()
    return _orig_cmd_start(args)


globals()["cmd_start"] = _cmd_start_wrapper


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    try:
        return getattr(_server._impl, name)
    except AttributeError:
        pass
    try:
        return getattr(_cli, name)
    except AttributeError:
        pass
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    sys.exit(main())
