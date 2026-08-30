"""Router-only smoke: check liveness, skip model tests if no models configured."""
from __future__ import annotations
import sys
import json
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:11434"

def check(path: str, expect=200):
    url = BASE + path
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            body = r.read().decode()
            status = r.status
            return status == expect, f"{path} -> {status} {body[:200]}"
    except urllib.error.HTTPError as e:
        return False, f"{path} -> HTTP {e.code} {e.read().decode()[:200]}"
    except Exception as e:
        return False, f"{path} -> ERROR {e}"

def has_models():
    # Check config for models
    try:
        import yaml
        for cfg_path in ["~/.autoconduck/config.yaml", ".autoconduck/config.yaml", "config/config.yaml"]:
            import pathlib, os
            p = pathlib.Path(cfg_path).expanduser()
            if p.exists():
                data = yaml.safe_load(p.read_text())
                if data and (data.get("custom_models") or data.get("models")):
                    return True
        # Also check via API /v1/models
        url = BASE + "/v1/models"
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read().decode())
            models = data.get("data") or data.get("models") or []
            # Filter non-empty
            return len(models) > 1  # pseudo models count
    except Exception:
        pass
    return False

def main():
    ok_all = True
    for path in ["/healthz", "/v1/models", "/stats"]:
        ok, msg = check(path)
        print(msg)
        if not ok:
            ok_all = False
    if not ok_all:
        print("FAIL: liveness endpoints failed")
        sys.exit(1)
    print("Liveness OK")
    if not has_models():
        print("SKIP: no models configured — endpoint liveness verified only")
        sys.exit(0)
    # With models, exercise chat paths
    for name, payload in [
        ("chat fast", {"model": "autoconduck", "messages": [{"role": "user", "content": "hi"}], "stream": False}),
        ("chat budget", {"model": "autoconduck-budget", "messages": [{"role": "user", "content": "hi"}], "stream": False}),
        ("messages", None),
    ]:
        if name == "messages":
            url = BASE + "/v1/messages"
            data = json.dumps({"model": "autoconduck", "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}], "max_tokens": 16}).encode()
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    print(f"{name} -> {r.status} OK")
            except Exception as e:
                print(f"{name} -> ERROR {e}")
                ok_all = False
        else:
            url = BASE + "/v1/chat/completions"
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
