from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from skail.config import Config, ModelEntry
from skail.routing.benchmarks import BenchmarkRegistry, sync_openrouter_snapshot
from skail.routing.model_pool import CapabilitySLA, ModelPool


def _responses():
    as_of = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "benchmarks": {
            "data": [
                {"source": "artificial-analysis", "model_permaslug": "acme/ui", "coding_index": 80, "intelligence_index": 70, "agentic_index": 60},
                {"source": "artificial-analysis", "model_permaslug": "acme/code", "coding_index": 90, "intelligence_index": 60, "agentic_index": 80},
                {"source": "design-arena", "model_permaslug": "acme/ui", "arena": "builders", "category": "uicomponent", "elo": 1200, "win_rate": 0.70, "rank": 1},
                {"source": "design-arena", "model_permaslug": "acme/code", "arena": "builders", "category": "uicomponent", "elo": 1000, "win_rate": 0.50, "rank": 2},
                {"source": "openrouter", "model_permaslug": "acme/code", "benchmark_type": "gpqa_diamond", "accuracy": 0.8, "total_tasks": 100},
            ],
            "meta": {"as_of": as_of, "citation": "test", "version": "v1"},
        },
        "models": {
            "data": [
                {"id": "acme/ui", "canonical_slug": "acme/ui", "context_length": 100000, "top_provider": {"max_completion_tokens": 8000}, "supported_parameters": ["tools", "response_format"], "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]}, "pricing": {"prompt": "0.000001", "completion": "0.000002"}},
                {"id": "acme/code", "canonical_slug": "acme/code", "context_length": 200000, "top_provider": {"max_completion_tokens": 8000}, "supported_parameters": ["tools", "response_format"], "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}, "pricing": {"prompt": "0.000001", "completion": "0.000002"}},
            ]
        },
    }


def test_registry_normalizes_only_within_each_metric_cohort():
    registry = BenchmarkRegistry.from_responses(**_responses())

    assert registry.score("acme/ui", "design_arena.builders.uicomponent.elo") == 1.0
    assert registry.score("acme/code", "design_arena.builders.uicomponent.elo") == 0.0
    assert registry.score("acme/code", "aa.coding") == 1.0
    assert registry.score("acme/ui", "openrouter.gpqa_diamond.accuracy") is None


def test_sync_is_explicit_and_keeps_last_good_snapshot_on_bad_response(tmp_path):
    responses = _responses()
    calls = []

    def fetch(url, headers):
        calls.append(url)
        return responses["benchmarks" if url.endswith("benchmarks") else "models"]

    target = tmp_path / "benchmarks.json"
    registry = sync_openrouter_snapshot("key", target, fetch=fetch)
    assert target.exists()
    assert registry.available is True
    assert len(calls) == 2

    before = target.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        sync_openrouter_snapshot("key", target, fetch=lambda *_: {"data": []})
    assert target.read_text(encoding="utf-8") == before


def test_stale_snapshot_has_no_routing_coverage():
    registry = BenchmarkRegistry.from_responses(**_responses())
    registry.as_of = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    registry.max_age_hours = 24
    assert registry.is_fresh is False
    assert registry.profile_score("acme/ui", "frontend_design_planner") is None


def test_frontend_profile_prefers_ui_coverage_within_price_band():
    registry = BenchmarkRegistry.from_responses(**_responses())
    config = Config(models={
        "acme/ui": ModelEntry(id="acme/ui", provider="openrouter", cost_input=1, cost_output=1),
        "acme/code": ModelEntry(id="acme/code", provider="openrouter", cost_input=1, cost_output=1),
    })
    info = ModelPool(config, benchmarks=registry).select_by_sla_detailed(
        CapabilitySLA(domain="frontend", role="planner")
    )
    assert info.model == "acme/ui"
    assert info.benchmark_coverage_state == "covered"
    assert info.benchmark_profile == "frontend_design_planner"


def test_missing_domain_coverage_falls_back_to_static_selection():
    registry = BenchmarkRegistry.from_responses(**_responses())
    config = Config(models={"acme/ui": ModelEntry(id="acme/ui", cost_input=1, cost_output=1)})
    info = ModelPool(config, benchmarks=registry).select_by_sla_detailed(CapabilitySLA(domain="video", role="planner"))
    assert info.model == "acme/ui"
    assert info.benchmark_coverage_state == "unavailable"
    assert info.fallback_reason == "benchmark_coverage_unavailable"


def test_models_metadata_rejects_insufficient_actual_context():
    registry = BenchmarkRegistry.from_responses(**_responses())
    config = Config(models={
        "acme/ui": ModelEntry(id="acme/ui", cost_input=1, cost_output=1),
        "acme/code": ModelEntry(id="acme/code", cost_input=2, cost_output=2),
    })
    info = ModelPool(config, benchmarks=registry).select_by_sla_detailed(
        CapabilitySLA(input_tokens=96_000, min_output_tokens=8_000)
    )
    assert info.model == "acme/code"
    assert info.candidates_excluded_by["context"] == 1
