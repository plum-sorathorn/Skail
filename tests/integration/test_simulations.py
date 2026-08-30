"""Integration simulations — fast-path only (SLOW path removed in Phase 1B)."""
import pytest

def test_router_fast_path_liveness():
    from autoconduck.routing.dispatcher import route
    from autoconduck.config import get_config
    cfg = get_config()
    msgs = [{"role": "user", "content": "hello"}]
    decision = route(msgs, [], pseudo_model="autoconduck", config=cfg)
    assert decision.path == "fast"
    assert decision.model is not None

def test_fast_path_direct_dispatch():
    from autoconduck.server.turn_guard import TurnGuard
    guard = TurnGuard()
    res = guard.classify_turn([{"role": "user", "content": "hello"}])
    assert res is not None
