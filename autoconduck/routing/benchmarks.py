"""Local, source-preserving OpenRouter benchmark snapshots.

Network synchronization is explicit.  Selection only consults an already-loaded
registry, so it cannot add network I/O to the routing hot path.
"""
from __future__ import annotations

import json
import os
import tempfile
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


OPENROUTER_URL = "https://openrouter.ai/api/v1"
SNAPSHOT_VERSION = 1
_registry = None

PROFILE_METRICS: dict[str, tuple[tuple[str, float], ...]] = {
    "frontend_design_planner": (
        ("design_arena.builders.uicomponent.elo", 0.60),
        ("design_arena.models.website.elo", 0.20), ("aa.intelligence", 0.12), ("aa.coding", 0.08),
    ),
    "frontend_implementer": (
        ("aa.coding", 0.55), ("aa.agentic", 0.20),
        ("design_arena.models.codecategories.elo", 0.20), ("design_arena.builders.uicomponent.elo", 0.05),
    ),
    "general_software_engineering": (
        ("aa.coding", 0.55), ("aa.agentic", 0.25), ("aa.intelligence", 0.15),
        ("design_arena.models.codecategories.elo", 0.05),
    ),
    "research_planner": (("aa.intelligence", 0.75), ("openrouter.gpqa_diamond.accuracy", 0.25)),
    "tool_agent_implementer": (
        ("aa.agentic", 0.65), ("openrouter.tau_bench_verified_airline.accuracy", 0.20),
        ("design_arena.agents.default.elo", 0.15),
    ),
    "verifier": (("aa.coding", 0.60), ("aa.intelligence", 0.30), ("aa.agentic", 0.10)),
}


def profile_for(domain: str | None, role: str | None) -> str:
    domain, role = (domain or "").lower(), (role or "").lower()
    if domain == "frontend":
        return "frontend_design_planner" if role == "planner" else "frontend_implementer"
    if domain == "research":
        return "research_planner"
    if domain in {"tool_agent", "oma"}:
        return "tool_agent_implementer"
    if domain in {"gamedev", "data_visualization", "svg", "3d", "image", "video"}:
        # Specialized profiles are intentionally inert until their corresponding
        # Design Arena category is explicitly added to PROFILE_METRICS.
        return f"specialized_{domain}"
    if role == "verifier":
        return "verifier"
    return "general_software_engineering"


@dataclass
class BenchmarkRegistry:
    """Immutable-in-practice registry built by the maintenance path."""
    as_of: str | None = None
    citation: str | None = None
    api_version: str | None = None
    models: dict[str, dict[str, Any]] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    scores: dict[str, dict[str, float]] = field(default_factory=dict)
    raw_results: list[dict[str, Any]] = field(default_factory=list)
    max_age_hours: int = 168

    @property
    def available(self) -> bool:
        return bool(self.as_of and self.models and self.raw_results)

    @property
    def is_fresh(self) -> bool:
        if not self.available:
            return False
        try:
            value = self.as_of.replace("Z", "+00:00") if self.as_of else ""
            return (datetime.now(timezone.utc) - datetime.fromisoformat(value)).total_seconds() <= self.max_age_hours * 3600
        except ValueError:
            return False

    def canonical_id(self, model_id: str) -> str:
        return self.aliases.get(model_id, model_id)

    def score(self, model_id: str, metric: str) -> float | None:
        if not self.is_fresh:
            return None
        return self.scores.get(self.canonical_id(model_id), {}).get(metric)

    def profile_score(self, model_id: str, profile: str) -> float | None:
        values = [(self.score(model_id, metric), weight) for metric, weight in PROFILE_METRICS.get(profile, ())]
        covered = [(score, weight) for score, weight in values if score is not None]
        if not covered:
            return None
        total = sum(weight for _, weight in covered)
        return sum(score * weight for score, weight in covered) / total

    def metadata(self, model_id: str) -> dict[str, Any]:
        return self.models.get(self.canonical_id(model_id), {})

    def to_dict(self) -> dict[str, Any]:
        return {"snapshot_version": SNAPSHOT_VERSION, "as_of": self.as_of, "citation": self.citation,
                "api_version": self.api_version, "models": self.models, "aliases": self.aliases,
                "scores": self.scores, "raw_results": self.raw_results}

    @classmethod
    def from_dict(cls, value: dict[str, Any], *, max_age_hours: int = 168) -> "BenchmarkRegistry":
        if value.get("snapshot_version") != SNAPSHOT_VERSION or not isinstance(value.get("raw_results"), list):
            raise ValueError("unsupported or malformed benchmark snapshot")
        result = cls(as_of=value.get("as_of"), citation=value.get("citation"), api_version=value.get("api_version"),
                     models=value.get("models") or {}, aliases=value.get("aliases") or {}, scores=value.get("scores") or {},
                     raw_results=value["raw_results"], max_age_hours=max_age_hours)
        if not result.available:
            raise ValueError("benchmark snapshot has no usable models or results")
        return result

    @classmethod
    def from_responses(cls, benchmarks: dict[str, Any], models: dict[str, Any], *, max_age_hours: int = 168) -> "BenchmarkRegistry":
        items, model_items = benchmarks.get("data"), models.get("data")
        meta = benchmarks.get("meta") or {}
        if not isinstance(items, list) or not isinstance(model_items, list) or not isinstance(meta.get("as_of"), str):
            raise ValueError("OpenRouter response is missing data or meta.as_of")
        registry = cls(as_of=meta["as_of"], citation=meta.get("citation"), api_version=meta.get("version"), max_age_hours=max_age_hours)
        for model in model_items:
            if not isinstance(model, dict) or not isinstance(model.get("id"), str):
                continue
            canonical = str(model.get("canonical_slug") or model["id"])
            architecture, provider = model.get("architecture") or {}, model.get("top_provider") or {}
            registry.models[canonical] = {
                "context_length": model.get("context_length"), "max_output_tokens": provider.get("max_completion_tokens"),
                "supported_parameters": model.get("supported_parameters") or [],
                "input_modalities": architecture.get("input_modalities") or [],
                "output_modalities": architecture.get("output_modalities") or [], "pricing": model.get("pricing") or {},
            }
            registry.aliases[str(model["id"])] = canonical
            for alias in model.get("aliases") or []:
                if isinstance(alias, str):
                    registry.aliases[alias] = canonical
        grouped: dict[str, list[tuple[str, float]]] = {}
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("model_permaslug"), str):
                continue
            source, model_id = item.get("source"), registry.canonical_id(item["model_permaslug"])
            registry.aliases[item["model_permaslug"]] = model_id
            registry.raw_results.append({"source": source, "model_permaslug": model_id, "raw": item,
                                         "meta": {"as_of": registry.as_of, "citation": registry.citation, "version": registry.api_version}})
            for metric, raw in _metrics(item):
                if isinstance(raw, (int, float)):
                    # Lower Design Arena rank is better; all other documented
                    # score fields are higher-is-better within their own cohort.
                    grouped.setdefault(metric, []).append((model_id, -float(raw) if metric.endswith(".rank") else float(raw)))
        for metric, values in grouped.items():
            low, high = min(score for _, score in values), max(score for _, score in values)
            for model_id, raw in values:
                normalized = 1.0 if high == low else (raw - low) / (high - low)
                registry.scores.setdefault(model_id, {})[metric] = normalized
        if not registry.available:
            raise ValueError("OpenRouter response contained no usable benchmark results")
        return registry


def _metrics(item: dict[str, Any]) -> list[tuple[str, Any]]:
    source = item.get("source")
    if source == "artificial-analysis":
        return [(f"aa.{name}", item.get(f"{name}_index")) for name in ("coding", "intelligence", "agentic")]
    if source == "design-arena":
        arena, category = str(item.get("arena") or "models"), str(item.get("category") or "default")
        return [(f"design_arena.{arena}.{category}.{name}", item.get(name)) for name in ("elo", "win_rate", "rank")]
    if source == "openrouter":
        kind = item.get("benchmark_type")
        if isinstance(kind, str):
            return [(f"openrouter.{kind}.{name}", item.get(name)) for name in ("accuracy", "accuracy_stddev", "total_tasks", "avg_cost_per_task", "last_run_timestamp")]
    return []


def _http_fetch(url: str, headers: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:  # nosec B310: fixed HTTPS endpoint
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("OpenRouter returned a non-object response")
    return payload


def sync_openrouter_snapshot(api_key: str, path: Path, *, fetch: Callable[[str, dict[str, str]], dict[str, Any]] = _http_fetch,
                             max_age_hours: int = 168) -> BenchmarkRegistry:
    """Fetch both OpenRouter endpoints and atomically replace a valid local snapshot."""
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is required for benchmark synchronization")
    headers = {"Authorization": f"Bearer {api_key}"}
    benchmarks = fetch(f"{OPENROUTER_URL}/benchmarks", headers)
    models = fetch(f"{OPENROUTER_URL}/models", headers)
    registry = BenchmarkRegistry.from_responses(benchmarks, models, max_age_hours=max_age_hours)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="benchmarks-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(registry.to_dict(), handle, separators=(",", ":"), sort_keys=True)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    install_registry(registry)
    return registry


def sync_openrouter_from_env() -> BenchmarkRegistry:
    """Explicit maintenance helper used by the TUI; never called by routing."""
    from autoconduck.config.paths import run_dir

    return sync_openrouter_snapshot(os.environ.get("OPENROUTER_API_KEY", ""), run_dir() / "benchmarks.json")


def install_registry(registry: BenchmarkRegistry) -> None:
    """Install a registry during startup or explicit maintenance, never on a request."""
    global _registry
    _registry = registry


def get_registry() -> BenchmarkRegistry | None:
    return _registry


def clear_registry() -> None:
    """Clear process-local state when startup finds no usable snapshot."""
    global _registry
    _registry = None


def snapshot_status() -> dict[str, Any]:
    registry = get_registry()
    if registry is None:
        return {"available": False, "fresh": False, "coverage_models": 0}
    age = None
    try:
        age = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(registry.as_of.replace("Z", "+00:00"))).total_seconds() / 3600)
    except Exception:
        pass
    return {"available": registry.available, "fresh": registry.is_fresh, "as_of": registry.as_of,
            "age_hours": age, "coverage_models": len(registry.scores), "api_version": registry.api_version}


def load_snapshot(path: Path, *, max_age_hours: int = 168) -> BenchmarkRegistry:
    """Load and install a previously synchronized snapshot during process startup."""
    registry = BenchmarkRegistry.from_dict(json.loads(path.read_text(encoding="utf-8")), max_age_hours=max_age_hours)
    install_registry(registry)
    return registry
