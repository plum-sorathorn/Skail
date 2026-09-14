"""Phase 1B stub - SLOW DAG tests removed, session_guard tests preserved via server path."""
import pytest
from skail.server.session_guard import SessionGuard

def test_session_guard_60_turn_simulation_prefix_invariance():
    guard = SessionGuard()
    msgs = [{"role": "system", "content": "sys"}] + [{"role": "user", "content": f"msg {i}"} for i in range(60)]
    res = guard.guard_context(msgs, context_window=4000)
    assert res.cache_prefix_preserved is True

def test_session_guard_150kb_massive_tool_log():
    guard = SessionGuard()
    big = "x" * 150000
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hello"}, {"role": "tool", "content": big}]
    res = guard.guard_context(msgs, context_window=2000)
    assert res.compacted is True

def test_session_guard_code_fences_and_headers_preservation():
    guard = SessionGuard()
    content = "# Header\n```python\nprint(1)\n```\n" + "y"*5000
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": content}]
    res = guard.guard_context(msgs, context_window=500)
    assert res.compacted is True
    assert "```" in str(res.messages)

def test_session_guard_unclosed_nested_code_fences():
    guard = SessionGuard()
    content = "```python\nprint(1)\n" + "y"*5000
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": content}]
    res = guard.guard_context(msgs, context_window=100)
    assert res is not None

def test_session_guard_edge_case_content_types():
    guard = SessionGuard()
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": ""}]
    res = guard.guard_context(msgs, context_window=100)
    assert res is not None
