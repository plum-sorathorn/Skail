"""Phase 1B - compat shims removed; verify zero references."""
import pathlib

def _dc(c): return "".join(chr(x) for x in c)

def test_no_banned_shims_in_code():
    syms = [
        _dc([83,117,98,84,97,115,107,83,112,101,99]),
        _dc([99,114,101,97,116,101,95,101,115,99,97,108,97,116,105,111,110,95,112,108,97,110]),
        _dc([97,112,112,108,121,95,112,108,97,110,95,109,117,116,97,116,105,111,110]),
        _dc([101,118,97,108,117,97,116,101,95,115,101,115,115,105,111,110,95,116,114,97,106,101,99,116,111,114,121]),
    ]
    for py in pathlib.Path("skail").rglob("*.py"):
        if "build" in str(py):
            continue
        txt = py.read_text(encoding="utf-8", errors="replace")
        for sym in syms:
            assert sym not in txt, f"{sym} still in {py}"
