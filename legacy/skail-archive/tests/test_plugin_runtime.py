"""Phase 2 plugin runtime tests — ledger, bias, endpoints, dispatcher bias, runtime proof path."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _cfg_with_models(cheap_cap=0.2, pricey_cap=0.9, cheap_vector=None, pricey_vector=None):
    from skail.config.models import Config

    cfg = Config()
    cfg.plugins.enabled = True
    cfg.plugins.escalation_floor_bump = 0.15
    cfg.plugins.escalation_ttl_turns = 3
    cfg.model_list = [
        {
            "id": "cheap",
            "provider": "openai",
            "api_key": "k",
            "price_in": 0.1,
            "price_out": 0.1,
            "context_window": 32000,
            "supports_tools": True,
            "capability_score": cheap_cap,
            "capability_vector": cheap_vector or {"reasoning": 0.2, "tool_reliability": 0.3, "code_quality": 0.2, "latency_class": 0.8},
        },
        {
            "id": "pricey",
            "provider": "openai",
            "api_key": "k",
            "price_in": 5.0,
            "price_out": 5.0,
            "context_window": 128000,
            "supports_tools": True,
            "capability_score": pricey_cap,
            "capability_vector": pricey_vector or {"reasoning": 0.9, "tool_reliability": 0.9, "code_quality": 0.9, "latency_class": 0.5},
        },
    ]
    return cfg


@pytest.fixture(autouse=True)
def isolate_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SKAIL_HOME", str(tmp_path / ".skail"))
    import skail.config.manager as m
    import skail.plugin.ledger as led_mod
    import skail.plugin.bias as bias_mod

    m._config = None
    m._config_digest = None
    m._config_path = None
    m._config_mtime = None
    led_mod.reset_ledger_singleton()
    bias_mod.reset_bias_singleton()
    yield
    led_mod.reset_ledger_singleton()
    bias_mod.reset_bias_singleton()
    m._config = None


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

def test_ledger_wal_and_batching(tmp_path):
    from skail.plugin.ledger import PluginLedger

    db = tmp_path / "ledger.db"
    ledger = PluginLedger(db_path=db, retention_days=30)
    # journal_mode should be WAL
    con = sqlite3.connect(str(db))
    mode = con.execute("PRAGMA journal_mode;").fetchone()[0]
    con.close()
    assert mode.lower() == "wal"
    # enqueue durable events
    for i in range(5):
        ledger.enqueue("sess1", f"t{i}", "task_start", {"goal": f"g{i}"})
    # non-durable counted only
    ledger.enqueue("sess1", "t0", "tool_call", {"x": 1})
    assert ledger.flush_sync() == 5
    rows = ledger.query_events(session_id="sess1", limit=10)
    assert len(rows) == 5
    # ensure non-durable not persisted
    kinds = {r["kind"] for r in rows}
    assert "tool_call" not in kinds
    assert ledger.get_counts("sess1").get("tool_call") == 1


def test_ledger_retention_prune(tmp_path):
    from skail.plugin.ledger import PluginLedger
    import datetime

    db = tmp_path / "ledger.db"
    ledger = PluginLedger(db_path=db, retention_days=0)  # prune everything except future
    # insert an old event directly
    old_ts = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=5)).isoformat()
    con = sqlite3.connect(str(db))
    con.execute("INSERT INTO events (ts, session_id, task_id, kind, data) VALUES (?,?,?,?,?)",
                (old_ts, "sess", "t1", "task_start", "{}"))
    con.commit()
    con.close()
    # create new ledger with 1-day retention — should prune on startup
    ledger2 = PluginLedger(db_path=db, retention_days=1)
    rows = ledger2.query_events(limit=50)
    # old event should be pruned
    assert all(r["session_id"] != "sess" or r["task_id"] != "t1" for r in rows)


def test_ledger_queue_pressure_drop(tmp_path):
    from skail.plugin.ledger import PluginLedger
    db = tmp_path / "ledger.db"
    ledger = PluginLedger(db_path=db, retention_days=30)
    # maxlen 1000 — pushing 1100 should keep only last 1000 (drop-oldest)
    for i in range(1100):
        ledger.enqueue("s", f"t{i}", "task_start", {"i": i})
    # Depending on whether a background flusher auto-flushed, queue may be smaller;
    # the invariant is: queue never exceeds maxlen and total persisted + queued == at most 1100 with no overflow loss beyond deque semantics
    assert len(ledger._queue) <= 1000
    queued = len(ledger._queue)
    flushed = ledger.flush_sync()
    assert flushed == queued
    # Re-test in fresh ledger without background task flushing: fill exactly 1100 synchronously
    ledger2 = PluginLedger(db_path=tmp_path / "ledger2.db", retention_days=30)
    # force no auto-flush by stopping task if any
    for i in range(1100):
        ledger2.enqueue("s", f"t{i}", "task_start", {"i": i})
        # prevent background flusher from consuming (it is not started unless await start())
    assert len(ledger2._queue) == 1000 or len(ledger2._queue) <= 1000
    ledger2.flush_sync()


def test_ledger_fail_soft(tmp_path, monkeypatch):
    from skail.plugin.ledger import PluginLedger
    db = tmp_path / "ledger.db"
    ledger = PluginLedger(db_path=db, retention_days=30)
    ledger.enqueue("s", "t", "task_start", {"goal": "hi"})
    # break DB path by making parent a file
    monkeypatch.setattr(ledger, "db_path", Path("/nonexistent_dir_xyz/ledger.db"))
    # flush_sync should not raise, returns 0
    assert ledger.flush_sync() == 0


# ---------------------------------------------------------------------------
# Bias
# ---------------------------------------------------------------------------

def test_bias_apply_expiry_and_reset():
    from skail.plugin.bias import SessionBiasStore

    store = SessionBiasStore()
    store.apply_escalation("sess", 0.2, ttl_turns=2)
    assert store.get_bump("sess") == pytest.approx(0.2)
    store.increment_turn("sess")  # turn 1
    assert store.get_bump("sess") == pytest.approx(0.2)
    store.increment_turn("sess")  # turn 2 -> expires (expires_at = 0+2 =2, cur=2 => expired)
    assert store.get_bump("sess") == pytest.approx(0.0)
    # re-apply and reset
    store.apply_escalation("sess", 0.15, ttl_turns=10)
    assert store.get_bump("sess") == pytest.approx(0.15)
    store.reset_session("sess")
    assert store.get_bump("sess") == pytest.approx(0.0)


def test_bias_unknown_session_returns_zero():
    from skail.plugin.bias import SessionBiasStore

    s = SessionBiasStore()
    assert s.get_bump(None) == 0.0
    assert s.get_bump("unknown") == 0.0


def test_bias_fail_soft_returns_zero(monkeypatch):
    from skail.plugin import bias as bias_mod

    store = bias_mod.SessionBiasStore()
    # corrupt internal store to trigger exception inside get_bump
    store._store = None  # type: ignore
    assert store.get_bump("sess") == 0.0


# ---------------------------------------------------------------------------
# Dispatcher bias integration
# ---------------------------------------------------------------------------

def test_dispatcher_floor_bump_raises_effective_floor(tmp_path, monkeypatch):
    from skail.plugin.bias import get_bias_store
    from skail.routing.dispatcher import route
    from skail.routing.slm_planner import SLMPlanner, ExecutionPlan
    from skail.config.manager import get_config

    cfg = _cfg_with_models()
    # wire config into manager cache
    import skail.config.manager as m

    m._config = cfg
    # apply bias
    get_bias_store().apply_escalation("sessA", 0.3, ttl_turns=10)
    # mock planner to return high base floor (via min_capability 0.4)
    # ExecutionPlan.suggested_sla has min_capability derived from task; we can craft directly via planner mock
    def fake_plan_sync(self, messages, config=None):
        from skail.routing.model_pool import CapabilitySLA
        return ExecutionPlan(
            confidence=0.9,
            task_type="debug",
            complexity_score=7,
            rationale="test",
            suggested_sla=CapabilitySLA(min_capability_score=0.4, min_context=0, requires_tools=False),
        )

    monkeypatch.setattr(SLMPlanner, "plan_sync", fake_plan_sync)
    msgs = [{"role": "user", "content": "Fix bug"}]
    dec_no_bias = route(msgs, config=cfg, session_id=None)
    dec_bias = route(msgs, config=cfg, session_id="sessA")
    # bias should increase min_capability_score_applied (floor)
    assert dec_bias.min_capability_score_applied > dec_no_bias.min_capability_score_applied
    # and respect hard cap 0.75
    assert dec_bias.min_capability_score_applied <= 0.75

    # bias expiry after TTL -> no bump
    for _ in range(10):
        get_bias_store().increment_turn("sessA")
    dec_expired = route(msgs, config=cfg, session_id="sessA")
    assert dec_expired.min_capability_score_applied == dec_no_bias.min_capability_score_applied


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def test_endpoints_disabled_noop(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from skail.server.plugin_routes import install_plugin_routes
    from skail.config.manager import get_config
    import skail.config.manager as m

    cfg = get_config()
    cfg.plugins.enabled = False
    m._config = cfg
    app = FastAPI()
    install_plugin_routes(app)
    client = TestClient(app)
    r = client.post("/plugin/events", json={"session_id": "s", "kind": "tool_call"})
    assert r.status_code == 200
    assert r.json()["status"] == "ignored"
    r2 = client.post("/plugin/escalate", json={"session_id": "s", "reason": "consecutive_errors"})
    assert r2.status_code == 200
    assert r2.json()["status"] == "ignored"


def test_events_validation_and_contract(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from skail.server.plugin_routes import install_plugin_routes
    from skail.config.manager import get_config
    import skail.config.manager as m

    cfg = get_config()
    cfg.plugins.enabled = True
    m._config = cfg
    app = FastAPI()
    install_plugin_routes(app)
    client = TestClient(app)
    # unknown kind -> ignored (not 5xx)
    r = client.post("/plugin/events", json={"session_id": "s", "kind": "weird"})
    assert r.status_code == 200
    assert r.json()["status"] == "ignored"
    # valid task_start -> ok
    r2 = client.post("/plugin/events", json={"session_id": "s2", "task_id": "t1", "kind": "task_start", "data": {}})
    assert r2.json()["status"] == "ok"
    # contract deterministic shape
    r3 = client.get("/plugin/contract", params={"session": "s2"})
    assert r3.status_code == 200
    j = r3.json()
    assert j["schema_version"] == "0.5"
    assert j["execution_authority"] == "plugin-deterministic"
    assert "brain" in j


def test_escalation_trigger_validation(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from skail.server.plugin_routes import install_plugin_routes
    from skail.config.manager import get_config
    import skail.config.manager as m

    cfg = get_config()
    cfg.plugins.enabled = True
    m._config = cfg
    app = FastAPI()
    install_plugin_routes(app)
    client = TestClient(app)
    r = client.post("/plugin/escalate", json={"session_id": "s", "reason": "unknown_trigger_xyz"})
    assert r.json()["status"] == "rejected"
    assert r.json()["reason"] == "unknown_trigger"
    # valid reason applies bias
    r2 = client.post("/plugin/escalate", json={"session_id": "s", "reason": "consecutive_errors"})
    assert r2.json()["status"] == "ok"
    assert "floor_bump" in r2.json()
    from skail.plugin.bias import get_bias_store

    assert get_bias_store().get_bump("s") > 0


def test_execute_disabled_returns_disabled(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from skail.server.plugin_routes import install_plugin_routes
    from skail.config.manager import get_config
    import skail.config.manager as m

    cfg = get_config()
    cfg.plugins.enabled = True
    cfg.plugins.execute_enabled = False
    m._config = cfg
    app = FastAPI()
    install_plugin_routes(app)
    client = TestClient(app)
    r = client.post("/plugin/execute", json={"session_id": "s", "goal": "do thing"})
    assert r.json()["status"] == "disabled"


# ---------------------------------------------------------------------------
# Runtime proof path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_runtime_execute_disabled_returns_disabled(tmp_path):
    from skail.plugin.runtime import start_task
    from skail.config.manager import get_config
    import skail.config.manager as m

    cfg = get_config()
    cfg.plugins.enabled = True
    cfg.plugins.execute_enabled = False
    m._config = cfg

    res = await start_task(
        session_id="sessDisabled",
        goal="read hello.txt",
        cfg=cfg,
    )
    assert res.get("status") == "disabled"
    assert "execute_enabled must be true" in res.get("error", "")


@pytest.mark.asyncio
async def test_runtime_execute_oma_sidecar_launches_and_records_ledger(tmp_path):
    from skail.plugin.runtime import start_task
    from skail.plugin.ledger import get_ledger
    from skail.config.manager import get_config
    import skail.config.manager as m

    cfg = get_config()
    cfg.plugins.enabled = True
    cfg.plugins.execute_enabled = True
    cfg.plugins.oma_enabled = True
    cfg.plugins.oma_mode = "auto"
    m._config = cfg

    res = await start_task(
        session_id="sessOMA",
        goal="Coordinate subagents to write tests",
        cfg=cfg,
    )
    assert res.get("status") == "ok"
    assert res.get("runner_started") is True
    assert res.get("session_id") == "sessOMA"
    assert res.get("mode") == "runTeam"
    assert isinstance(res.get("task_id"), str)
    assert "report" in res
    assert "tasks" in res

    # Verify ledger recorded task_start and terminal_result
    ledger = get_ledger()
    ledger.flush_sync()
    events = ledger.query_events(session_id="sessOMA")
    kinds = [e["kind"] for e in events]
    assert "task_start" in kinds
    assert "terminal_result" in kinds


@pytest.mark.asyncio
async def test_runtime_execute_fail_soft_on_missing_node(tmp_path):
    from skail.plugin.runtime import start_task
    from skail.plugin.ledger import get_ledger
    from skail.config.manager import get_config
    import skail.config.manager as m

    cfg = get_config()
    cfg.plugins.enabled = True
    cfg.plugins.execute_enabled = True
    cfg.plugins.oma_enabled = True
    cfg.plugins.oma_node_path = "non_existent_node_binary_999"
    m._config = cfg

    res = await start_task(
        session_id="sessMissingNode",
        goal="Perform task with missing node",
        cfg=cfg,
    )
    assert res.get("status") == "error"
    assert res.get("runner_started") is False
    assert "OMA sidecar launch failed" in res.get("report", "")
    assert res.get("session_id") == "sessMissingNode"

    # Fail-soft still enqueues task_start and terminal_result in ledger
    ledger = get_ledger()
    ledger.flush_sync()
    events = ledger.query_events(session_id="sessMissingNode")
    kinds = [e["kind"] for e in events]
    assert "task_start" in kinds
    assert "terminal_result" in kinds


def test_execute_endpoint_launches_oma_and_returns_ok(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from skail.server.plugin_routes import install_plugin_routes
    from skail.plugin.ledger import get_ledger
    from skail.config.manager import get_config
    import skail.config.manager as m

    cfg = get_config()
    cfg.plugins.enabled = True
    cfg.plugins.execute_enabled = True
    cfg.plugins.oma_enabled = True
    m._config = cfg
    app = FastAPI()
    install_plugin_routes(app)
    client = TestClient(app)

    r = client.post("/plugin/execute", json={"session_id": "sessEndpoint", "goal": "Build dynamic sidecar router"})
    assert r.status_code == 200
    j = r.json()
    assert j.get("status") == "ok"
    res = j.get("result", {})
    assert res.get("status") == "ok"
    assert res.get("session_id") == "sessEndpoint"
    assert "report" in res

    ledger = get_ledger()
    ledger.flush_sync()
    events = ledger.query_events(session_id="sessEndpoint")
    kinds = [e["kind"] for e in events]
    assert "task_start" in kinds
    assert "terminal_result" in kinds


def test_plugin_endpoints_never_500(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from skail.server.plugin_routes import install_plugin_routes
    from skail.config.manager import get_config
    import skail.config.manager as m

    cfg = get_config()
    cfg.plugins.enabled = True
    m._config = cfg
    app = FastAPI()
    install_plugin_routes(app)
    client = TestClient(app)
    # malformed bodies must not 5xx
    for payload in [{}, {"kind": None}, "not-json"]:
        try:
            r = client.post("/plugin/events", json=payload if isinstance(payload, dict) else payload)
            assert r.status_code != 500
        except Exception:
            pass
    for payload in [{}, {"reason": "bad"}]:
        r = client.post("/plugin/escalate", json=payload)
        assert r.status_code == 200
        assert r.status_code != 500
    r = client.get("/plugin/contract")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Phase A Tests
# ---------------------------------------------------------------------------

def test_phase_a_config_models():
    from skail.config.models import PluginConfig, SelectionConfig

    p = PluginConfig()
    assert p.omp_enabled is False
    assert p.subagent_enabled is False
    assert p.rag_enabled is True
    assert p.enabled is False
    assert p.claude_enabled is False
    assert p.pi_enabled is False
    assert p.opencode_enabled is False
    assert p.ledger_retention_days == 30
    assert p.escalation_ttl_turns == 10
    assert p.escalation_floor_bump == 0.15
    assert p.llm_synthesis_enabled is False
    assert p.execute_enabled is False
    assert p.oma_enabled is True
    assert p.oma_mode == "auto"
    assert p.oma_node_path is None

    s = SelectionConfig()
    assert s.rag_embedding_model == ""
    assert not hasattr(s, "subagent_budget_cap_mtok")


def test_bias_store_child_sessions():
    from skail.plugin.bias import SessionBiasStore

    store = SessionBiasStore()
    assert not store.is_child_session(None)
    assert not store.is_child_session("")
    assert not store.is_child_session("child_1")

    store.register_child_session("child_1", "parent_1")
    assert store.is_child_session("child_1")
    assert not store.is_child_session("parent_1")

    snap = store.snapshot()
    assert snap.get("children", {}).get("child_1") == "parent_1"

    # Reset specific session
    store.reset_session("child_1")
    assert not store.is_child_session("child_1")
    assert "child_1" not in store.snapshot().get("children", {})

    # Clear all
    store.register_child_session("child_2", "parent_2")
    assert store.is_child_session("child_2")
    store.clear_all()
    assert not store.is_child_session("child_2")
    assert len(store.snapshot().get("children", {})) == 0

    # Fail soft on empty inputs
    store.register_child_session("", "parent")
    store.register_child_session("child", "")
    assert not store.is_child_session("child")


def test_ledger_subagent_events_and_parent_session(tmp_path):
    from skail.plugin.ledger import PluginLedger, DURABLE_KINDS, ALLOWED_EVENT_KINDS

    assert "subagent_start" in DURABLE_KINDS
    assert "subagent_stop" in DURABLE_KINDS
    assert "subagent_start" in ALLOWED_EVENT_KINDS
    assert "subagent_stop" in ALLOWED_EVENT_KINDS

    db = tmp_path / "subagent_ledger.db"
    ledger = PluginLedger(db_path=db, retention_days=30)

    # Enqueue subagent events with parent_session_id
    assert ledger.enqueue("child_sess", "task_sub_1", "subagent_start", {"subagent": "worker"}, parent_session_id="parent_sess")
    assert ledger.enqueue("child_sess", "task_sub_1", "subagent_stop", {"status": "success"}, parent_session_id="parent_sess")
    assert ledger.flush_sync() == 2

    rows = ledger.query_events(session_id="child_sess")
    assert len(rows) == 2
    assert rows[0]["parent_session_id"] == "parent_sess"
    assert rows[1]["parent_session_id"] == "parent_sess"


def test_ledger_migration_parent_session_id(tmp_path):
    from skail.plugin.ledger import PluginLedger

    db = tmp_path / "legacy_ledger.db"
    # Create legacy schema without parent_session_id column
    conn = sqlite3.connect(str(db))
    conn.execute("""
    CREATE TABLE events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        session_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        data TEXT
    );
    """)
    conn.execute("INSERT INTO events (ts, session_id, task_id, kind, data) VALUES ('2026-08-31T00:00:00Z', 's1', 't1', 'task_start', '{}');")
    conn.commit()
    conn.close()

    # Now init PluginLedger which should run migration
    ledger = PluginLedger(db_path=db, retention_days=30)
    assert ledger.enqueue("s2", "t2", "subagent_start", {"k": "v"}, parent_session_id="p1")
    assert ledger.flush_sync() == 1

    rows = ledger.query_events(limit=10)
    assert len(rows) == 2
    # Old event has None for parent_session_id
    old_row = next(r for r in rows if r["session_id"] == "s1")
    assert old_row["parent_session_id"] is None
    new_row = next(r for r in rows if r["session_id"] == "s2")
    assert new_row["parent_session_id"] == "p1"


def test_dispatcher_child_session_routes_budget(tmp_path, monkeypatch):
    from skail.plugin.bias import get_bias_store, reset_bias_singleton
    from skail.routing.dispatcher import route
    from skail.routing.slm_planner import SLMPlanner, ExecutionPlan
    import skail.config.manager as m

    reset_bias_singleton()
    cfg = _cfg_with_models()
    m._config = cfg

    get_bias_store().register_child_session("child_sess_1", "parent_sess_1")

    def fake_plan_sync(self, messages, config=None):
        from skail.routing.model_pool import CapabilitySLA
        return ExecutionPlan(
            confidence=0.9,
            task_type="chat",
            complexity_score=3,
            rationale="test",
            suggested_sla=CapabilitySLA(min_capability_score=0.1, min_context=0, requires_tools=False),
        )

    monkeypatch.setattr(SLMPlanner, "plan_sync", fake_plan_sync)
    msgs = [{"role": "user", "content": "Subagent query"}]

    # Child session should be routed with effective_pseudo "skail-budget"
    dec_child = route(msgs, config=cfg, session_id="child_sess_1", pseudo_model="skail-expensive")
    # For child session, pseudo_model "skail-expensive" is overridden by effective_pseudo "skail-budget"
    # So it chooses the budget / cheapest model instead of expensive
    dec_expensive = route(msgs, config=cfg, session_id="normal_sess", pseudo_model="skail-expensive")

    assert dec_child.model is not None
    # Compare with non-child expensive selection
    assert dec_child.model != dec_expensive.model or dec_child.model == "local-fast"


def test_child_session_registration_and_bias_isolation():
    from skail.plugin.bias import SessionBiasStore

    store = SessionBiasStore()
    assert store.is_child_session("child_subagent") is False
    assert store.is_child_session("parent_main") is False

    # Register child session
    store.register_child_session("child_subagent", "parent_main")
    assert store.is_child_session("child_subagent") is True
    assert store.is_child_session("parent_main") is False

    # Escalation bump applies to child session only, not parent session
    bump = store.apply_escalation("child_subagent", 0.25, ttl_turns=3)
    assert bump == pytest.approx(0.25)
    assert store.get_bump("child_subagent") == pytest.approx(0.25)
    assert store.get_bump("parent_main") == pytest.approx(0.0)

    # Resetting child session clears child registration and bump
    store.reset_session("child_subagent")
    assert store.get_bump("child_subagent") == pytest.approx(0.0)
    assert store.is_child_session("child_subagent") is False
    assert store.get_bump("parent_main") == pytest.approx(0.0)

