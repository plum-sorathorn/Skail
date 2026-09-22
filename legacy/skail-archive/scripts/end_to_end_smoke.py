"""Router-only smoke: check liveness, skip model tests if no models configured.
Mode A (default): original behavior.
Mode B (--plugin): offline-safe plugin control-plane checks.
"""
from __future__ import annotations
import sys
import pathlib as _pathlib_for_smoke
# Ensure repo root on sys.path so `skail` is importable without pip install -e
try:
    _REPO_ROOT = _pathlib_for_smoke.Path(__file__).resolve().parents[1]
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
except Exception:
    pass
import json
import urllib.request
import urllib.error
import argparse
import pathlib

DEFAULT_BASE = "http://127.0.0.1:11434"


def _check_http(base: str, path: str, expect=200):
    url = base + path
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            body = r.read().decode()
            status = r.status
            return status == expect, f"{path} -> {status} {body[:200]}", status, body
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode()
        except Exception:
            body = ""
        return False, f"{path} -> HTTP {e.code} {body[:200]}", e.code, body
    except Exception as e:
        return False, f"{path} -> ERROR {e}", None, str(e)


def has_models(base: str = DEFAULT_BASE):
    # Check config for models
    try:
        import yaml
        for cfg_path in ["~/.skail/config.yaml", ".skail/config.yaml", "config/config.yaml"]:
            import os
            p = pathlib.Path(cfg_path).expanduser()
            if p.exists():
                data = yaml.safe_load(p.read_text())
                if data and (data.get("custom_models") or data.get("models")):
                    return True
        # Also check via API /v1/models
        url = base + "/v1/models"
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read().decode())
            models = data.get("data") or data.get("models") or []
            return len(models) > 1
    except Exception:
        pass
    return False


def _get_plugins_enabled() -> bool:
    try:
        from skail.config.manager import get_config
        cfg = get_config()
        plugins = getattr(cfg, "plugins", None)
        return bool(getattr(plugins, "enabled", False)) if plugins is not None else False
    except Exception:
        return False


class _Target:
    """Abstraction over live HTTP vs in-process TestClient."""

    def __init__(self, base: str | None, use_testclient: bool = False):
        self.base = base
        self.use_testclient = use_testclient
        self.client = None
        if use_testclient:
            from fastapi.testclient import TestClient
            from skail.server.server_streaming import _get_app
            import os as _os_smoke
            # For TestClient fallback, auto-enable plugins unless SKAIL_HOME
            # explicitly points to a user config (respects the "disabled -> ignored" branch
            # when the user runs smoke with a custom HOME that has plugins.enabled=false).
            _explicit_home = _os_smoke.environ.get("SKAIL_HOME")
            try:
                from skail.config.manager import get_config as _gc
                cfg = _gc()
                plugins = getattr(cfg, "plugins", None)
                enabled = bool(getattr(plugins, "enabled", False)) if plugins is not None else False
                if not enabled and not _explicit_home:
                    if plugins is not None:
                        try:
                            plugins.enabled = True  # type: ignore
                        except Exception:
                            pass
                        try:
                            from skail.plugin.bias import get_bias_store
                            get_bias_store().clear_all()
                        except Exception:
                            pass
                    self._patched_disabled = True
                else:
                    self._patched_disabled = not enabled
            except Exception:
                self._patched_disabled = False
            app = _get_app()
            self.client = TestClient(app)

    def get(self, path: str):
        if self.use_testclient and self.client is not None:
            resp = self.client.get(path)
            return resp.status_code, resp.text, resp.json() if resp.headers.get("content-type","").startswith("application/json") else None
        else:
            url = self.base + path  # type: ignore
            try:
                with urllib.request.urlopen(url, timeout=5) as r:
                    body = r.read().decode()
                    try:
                        j = json.loads(body)
                    except Exception:
                        j = None
                    return r.status, body, j
            except urllib.error.HTTPError as e:
                try:
                    body = e.read().decode()
                except Exception:
                    body = ""
                try:
                    j = json.loads(body) if body else None
                except Exception:
                    j = None
                return e.code, body, j
            except Exception as e:
                return None, str(e), None

    def post(self, path: str, body_dict: dict):
        data = json.dumps(body_dict).encode()
        if self.use_testclient and self.client is not None:
            resp = self.client.post(path, json=body_dict)
            try:
                j = resp.json()
            except Exception:
                j = None
            return resp.status_code, resp.text, j
        else:
            url = self.base + path  # type: ignore
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    body = r.read().decode()
                    try:
                        j = json.loads(body)
                    except Exception:
                        j = None
                    return r.status, body, j
            except urllib.error.HTTPError as e:
                try:
                    body = e.read().decode()
                except Exception:
                    body = ""
                try:
                    j = json.loads(body) if body else None
                except Exception:
                    j = None
                return e.code, body, j
            except Exception as e:
                return None, str(e), None

    def post_with_headers(self, path: str, body_dict: dict, headers: dict):
        """For chat completions with session header; only used for mode B + e2e."""
        data = json.dumps(body_dict).encode()
        if self.use_testclient and self.client is not None:
            resp = self.client.post(path, json=body_dict, headers=headers)
            try:
                j = resp.json()
            except Exception:
                j = None
            return resp.status_code, resp.text, j
        else:
            url = self.base + path  # type: ignore
            hdrs = {"Content-Type": "application/json"}
            hdrs.update(headers)
            req = urllib.request.Request(url, data=data, headers=hdrs)
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    body = r.read().decode()
                    try:
                        j = json.loads(body)
                    except Exception:
                        j = None
                    return r.status, body, j
            except urllib.error.HTTPError as e:
                try:
                    body = e.read().decode()
                except Exception:
                    body = ""
                try:
                    j = json.loads(body) if body else None
                except Exception:
                    j = None
                return e.code, body, j
            except Exception as e:
                return None, str(e), None


def _resolve_target(base_arg: str | None | argparse.Namespace) -> _Target:
    # support both old BASE and new arg parsing
    if isinstance(base_arg, argparse.Namespace):
        base = base_arg.base or base_arg.url or DEFAULT_BASE
        if base_arg.port:
            # override port if base is default
            base = f"http://{base_arg.host}:{base_arg.port}"
    elif isinstance(base_arg, str):
        base = base_arg
    else:
        base = DEFAULT_BASE
    # try live probe
    probe_ok = False
    try:
        with urllib.request.urlopen(base + "/healthz", timeout=2) as r:
            if r.status == 200:
                probe_ok = True
    except Exception:
        probe_ok = False
    if probe_ok:
        return _Target(base, use_testclient=False)
    # fallback to TestClient in-process
    print(f"[smoke] live server not reachable at {base} — using TestClient in-process")
    return _Target(base, use_testclient=True)


def main():
    parser = argparse.ArgumentParser(description="Skail end-to-end smoke")
    parser.add_argument("--plugin", action="store_true", help="enable mode B plugin checks")
    parser.add_argument("--base", default=None, help="base URL (default http://127.0.0.1:11434)")
    parser.add_argument("--url", default=None, help="alias for --base")
    parser.add_argument("--port", type=int, default=None, help="port override")
    parser.add_argument("--host", default="127.0.0.1", help="host override")
    args, _unknown = parser.parse_known_args()

    base = args.base or args.url or DEFAULT_BASE
    if args.port:
        base = f"http://{args.host}:{args.port}"

    target = _resolve_target(args)

    ok_all = True
    # liveness checks
    for path in ["/healthz", "/v1/models", "/stats"]:
        status, body, j = target.get(path)
        ok = status == 200
        print(f"{path} -> {status} {(body or '')[:200]}")
        if not ok:
            ok_all = False
    if not ok_all:
        print("FAIL: liveness endpoints failed")
        sys.exit(1)
    print("Liveness OK")

    # Mode B plugin checks
    if args.plugin:
        print("\n[smoke] Mode B (router+plugin) checks")
        # Determine plugin enabled via config (if TestClient fallback we already patched to enabled)
        plugins_enabled = _get_plugins_enabled()
        # If using TestClient and we patched, consider enabled for assertion purposes
        if target.use_testclient:
            # after patch, re-read
            plugins_enabled = _get_plugins_enabled()

        # 1. POST /plugin/events valid
        status, body, j = target.post("/plugin/events", {"session_id": "smoke", "kind": "tool_result", "data": {"tool": "read"}})
        print(f"POST /plugin/events valid -> {status} {body[:400]}")
        if status is None or status >= 500:
            print("FAIL: /plugin/events valid returned 5xx")
            sys.exit(1)
        j_status = (j or {}).get("status") if isinstance(j, dict) else None
        if plugins_enabled:
            if j_status != "ok":
                print(f"FAIL: expected status ok when plugins enabled, got {j_status}")
                sys.exit(1)
        else:
            if j_status != "ignored":
                print(f"FAIL: expected ignored when plugins disabled, got {j_status}")
                sys.exit(1)
            print("plugin plane disabled — mode B skipped (liveness only)")
            # still run remaining checks but expect ignored/rejected appropriately
        # 2. POST /plugin/events invalid kind expect graceful non-5xx
        status2, body2, j2 = target.post("/plugin/events", {"session_id": "smoke", "kind": "bogus_kind_xyz", "data": {}})
        print(f"POST /plugin/events invalid kind -> {status2} {body2[:400]}")
        if status2 is None or status2 >= 500:
            print("FAIL: invalid kind returned 5xx")
            sys.exit(1)
        if isinstance(j2, dict):
            # should be ignored or rejected, not 500
            assert j2.get("status") in ("ignored", "rejected", "ok"), f"unexpected status {j2}"

        # 3. GET /plugin/contract?session=smoke expect 200 + schema_version and execution_authority
        status3, body3, j3 = target.get("/plugin/contract?session=smoke")
        print(f"GET /plugin/contract?session=smoke -> {status3} {body3[:400]}")
        if status3 != 200:
            print("FAIL: /plugin/contract not 200")
            sys.exit(1)
        if not isinstance(j3, dict) or "schema_version" not in j3 or "execution_authority" not in j3:
            print(f"FAIL: contract missing keys: {j3}")
            sys.exit(1)

        # 4. POST /plugin/escalate valid reason
        status4, body4, j4 = target.post("/plugin/escalate", {"session_id": "smoke", "reason": "consecutive_errors"})
        print(f"POST /plugin/escalate consecutive_errors -> {status4} {body4[:400]}")
        if status4 is None or status4 >= 500:
            print("FAIL: /plugin/escalate valid returned 5xx")
            sys.exit(1)
        if plugins_enabled:
            if not isinstance(j4, dict) or j4.get("status") != "ok":
                print(f"FAIL: expected ok, got {j4}")
                sys.exit(1)
            bump = j4.get("floor_bump")
            try:
                if float(bump) <= 0:
                    print(f"FAIL: expected floor_bump >0, got {bump}")
                    sys.exit(1)
            except Exception:
                print(f"FAIL: floor_bump missing or invalid: {j4}")
                sys.exit(1)
        else:
            if isinstance(j4, dict) and j4.get("status") != "ignored":
                print(f"FAIL: expected ignored when disabled, got {j4}")
                sys.exit(1)

        # 5. POST /plugin/escalate bogus
        status5, body5, j5 = target.post("/plugin/escalate", {"session_id": "smoke", "reason": "bogus"})
        print(f"POST /plugin/escalate bogus -> {status5} {body5[:400]}")
        if status5 is None or status5 >= 500:
            print("FAIL: bogus escalate returned 5xx")
            sys.exit(1)
        if plugins_enabled:
            if not isinstance(j5, dict) or j5.get("status") != "rejected":
                print(f"FAIL: expected rejected for bogus, got {j5}")
                sys.exit(1)
        else:
            if isinstance(j5, dict) and j5.get("status") not in ("ignored", "rejected"):
                print(f"FAIL: expected ignored/rejected when disabled, got {j5}")
                sys.exit(1)

        # 6. GET /mcp expect 200 + protocolVersion and tools
        status6, body6, j6 = target.get("/mcp")
        print(f"GET /mcp -> {status6} {body6[:400]}")
        if status6 != 200:
            print(f"FAIL: GET /mcp returned {status6}")
            sys.exit(1)
        if not isinstance(j6, dict) or "protocolVersion" not in j6 or "tools" not in j6:
            print(f"FAIL: GET /mcp missing protocolVersion or tools: {j6}")
            sys.exit(1)

        # 7. POST /mcp/tools/call with skail_search expect 200
        status7, body7, j7 = target.post("/mcp/tools/call", {"tool": "skail_search", "args": {"query": "test"}})
        print(f"POST /mcp/tools/call skail_search -> {status7} {body7[:400]}")
        if status7 != 200:
            print(f"FAIL: POST /mcp/tools/call returned {status7}")
            sys.exit(1)

        # 8. POST /plugin/events SubagentStart expect 200
        status8, body8, j8 = target.post("/plugin/events", {"kind": "SubagentStart", "session_id": "parent_smoke", "subagent_id": "child_smoke"})
        print(f"POST /plugin/events SubagentStart -> {status8} {body8[:400]}")
        if status8 != 200:
            print(f"FAIL: POST /plugin/events SubagentStart returned {status8}")
            sys.exit(1)
        if plugins_enabled and isinstance(j8, dict) and j8.get("status") != "ok":
            print(f"FAIL: expected status ok for SubagentStart, got {j8}")
            sys.exit(1)

        print("[smoke] Mode B OK")
        sys.exit(0)

    # Original mode A tail
    if not has_models(base):
        print("SKIP: no models configured - endpoint liveness verified only")
        sys.exit(0)
    # With models, exercise chat paths (mode A)
    # For TestClient fallback, still try but will likely fail due to no litellm; skip gracefully
    if target.use_testclient:
        print("SKIP: TestClient mode - chat streaming not exercised (no upstream)")
        print("Smoke OK")
        sys.exit(0)
    for name, payload in [
        ("chat fast", {"model": "skail", "messages": [{"role": "user", "content": "hi"}], "stream": False}),
        ("chat budget", {"model": "skail-budget", "messages": [{"role": "user", "content": "hi"}], "stream": False}),
        ("messages", None),
    ]:
        if name == "messages":
            url = base + "/v1/messages"
            data = json.dumps({"model": "skail", "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}], "max_tokens": 16}).encode()
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    print(f"{name} -> {r.status} OK")
            except Exception as e:
                print(f"{name} -> ERROR {e}")
                ok_all = False
        else:
            url = base + "/v1/chat/completions"
            data = json.dumps(payload).encode()
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    body = r.read().decode()
                    print(f"{name} -> {r.status} {body[:200]}")
                    if r.status != 200:
                        ok_all = False
            except Exception as e:
                print(f"{name} -> ERROR {e}")
                ok_all = False
    if not ok_all:
        sys.exit(1)
    print("Smoke OK")
    sys.exit(0)

if __name__ == "__main__":
    main()
