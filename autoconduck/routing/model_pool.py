"""Dynamic multidimensional capability matching for model routing."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from autoconduck.config import Config
from autoconduck.config.resolver import resolve_orchestrator_model
from autoconduck.presets.model_presets import PRESETS

logger = logging.getLogger(__name__)
FILTER_STAGES = ("tools", "reasoning", "context", "capability_floor", "cost", "price_cap")
CAPABILITY_DIMS = ("reasoning", "tool_reliability", "code_quality", "latency_class")
TASK_TYPE_WEIGHTS: dict[str, dict[str, float]] = {
    "chat": {"reasoning": 0.5, "tool_reliability": 0.1, "code_quality": 0.2, "latency_class": 0.2},
    "explain": {"reasoning": 0.5, "tool_reliability": 0.1, "code_quality": 0.3, "latency_class": 0.1},
    "routine": {"reasoning": 0.1, "tool_reliability": 0.4, "code_quality": 0.2, "latency_class": 0.3},
    "debug": {"reasoning": 0.4, "tool_reliability": 0.3, "code_quality": 0.2, "latency_class": 0.1},
    "refactor": {"reasoning": 0.3, "tool_reliability": 0.2, "code_quality": 0.4, "latency_class": 0.1},
    "full_workflow": {"reasoning": 0.3, "tool_reliability": 0.4, "code_quality": 0.2, "latency_class": 0.1},
    "git_ops": {"reasoning": 0.1, "tool_reliability": 0.6, "code_quality": 0.1, "latency_class": 0.2},
    "single_edit": {"reasoning": 0.3, "tool_reliability": 0.2, "code_quality": 0.4, "latency_class": 0.1},
    "multi_edit": {"reasoning": 0.3, "tool_reliability": 0.2, "code_quality": 0.4, "latency_class": 0.1},
    "recon": {"reasoning": 0.4, "tool_reliability": 0.2, "code_quality": 0.2, "latency_class": 0.2},
    "read_answer": {"reasoning": 0.4, "tool_reliability": 0.2, "code_quality": 0.2, "latency_class": 0.2},
    "knowledge_query": {"reasoning": 0.4, "tool_reliability": 0.2, "code_quality": 0.2, "latency_class": 0.2},
    "research": {"reasoning": 0.5, "tool_reliability": 0.2, "code_quality": 0.2, "latency_class": 0.1},
}
DEFAULT_TASK_TYPE = "chat"


def capability_fit(vector: dict[str, float], weights: dict[str, float] | None = None) -> float:
    weights = weights or TASK_TYPE_WEIGHTS[DEFAULT_TASK_TYPE]
    dominant = [dim for dim, weight in weights.items() if weight > 0.25]
    dims = dominant or list(weights)
    min_val = min((float(vector.get(dim, 0.0)) for dim in dims), default=0.0)
    weighted_sum = sum(weight * float(vector.get(dim, 0.0)) for dim, weight in weights.items())
    return float(max(0.0, min(1.0, min_val + 0.1 * weighted_sum)))


def task_weights(task_type: str | None) -> dict[str, float]:
    return TASK_TYPE_WEIGHTS.get(task_type or "", TASK_TYPE_WEIGHTS[DEFAULT_TASK_TYPE])


@dataclass
class CapabilitySLA:
    """SLA with an optional per-selection advertised price cap in USD per 1M tokens."""
    min_context: int = 0
    min_output_tokens: int = 0
    requires_tools: bool = False
    requires_reasoning: bool = False
    min_capability_score: float = 0.0
    max_cost: float = float('inf')
    exclude_models: list[str] = field(default_factory=list)
    # Effective per-token price is input_price + 0.5 * output_price.
    max_price_usd_per_mtok: float | None = None
    task_type: str | None = None
    domain: str | None = None
    role: str | None = None
    requires_structured_output: bool = False
    requires_image_input: bool = False
    input_tokens: int = 0


@dataclass
class SelectionInfo:
    model: str | None = None
    candidates_considered: int = 0
    candidates_excluded_by: dict[str, int] = field(default_factory=dict)
    binding_constraint: str | None = None
    min_capability_score_applied: float = 0.0
    spend_cap_engaged: bool = False
    fallback_reason: str | None = None
    capability_fit_applied: float | None = None
    binding_capability_dim: str | None = None
    benchmark_profile: str | None = None
    benchmark_score: float | None = None
    benchmark_coverage_state: str = "not_requested"
    benchmark_snapshot_age_hours: float | None = None


@dataclass
class ModelEntry:
    id: str
    provider: str
    price_in: float
    price_out: float
    cost_input: float
    cost_output: float
    context_window: int
    supports_tools: bool
    enabled: bool = True
    is_reasoning: bool = False
    capability_score: float = 0.0
    max_usd_per_min: float | None = None
    capability_vector: dict[str, float] | None = None
    max_output_tokens: int | None = None
    supported_parameters: list[str] = field(default_factory=list)
    input_modalities: list[str] = field(default_factory=lambda: ["text"])


class ModelPool:
    """Manages dynamic model routing based on Capability SLAs."""

    def __init__(self, config: Config, benchmarks: Any = None) -> None:
        self.config = config
        if benchmarks is None:
            from autoconduck.routing.benchmarks import get_registry
            benchmarks = get_registry()
        self.benchmarks = benchmarks

    def _get_model_entries(self) -> list[ModelEntry]:
        """Fetch all configured models with their metadata."""
        pool = None
        if hasattr(self.config, "model_list") and self.config.model_list:
            pool = self.config.model_list
        elif hasattr(self.config, "get"):
            pool = self.config.get("models.pool") or self.config.get("model_list")
        if not pool and hasattr(self.config, "models") and self.config.models:
            if isinstance(self.config.models, dict):
                pool = list(self.config.models.values())
            elif getattr(self.config.models, "pool", None):
                pool = self.config.models.pool
            
        if not pool or not isinstance(pool, list):
            pool = [{"id": resolve_orchestrator_model(self.config)}]

        try:
            max_pool_size = max(1, int(getattr(getattr(self.config, "selection", None), "max_pool_size", 200)))
            pool = pool[:max_pool_size]
        except Exception:
            pass

        entries: list[ModelEntry] = []
        for item in pool:
            if isinstance(item, ModelEntry):
                if item.capability_vector is None and item.capability_score == 0.0:
                    self._seed_entry(item)
                entries.append(item)
                continue
            if hasattr(item, "model_dump"):
                item = item.model_dump()
            if isinstance(item, str):
                item = {"id": item}
            if isinstance(item, dict):
                model_id = item.get("id")
                if not model_id:
                    continue
                    
                # Get preset metadata if available
                preset = PRESETS.get(model_id, {})
                
                price_in = float(item.get("cost_input") or item.get("price_in") or preset.get("price_in", 0.0))
                price_out = float(item.get("cost_output") or item.get("price_out") or preset.get("price_out", 0.0))
                ctx = int(item.get("context_window") or preset.get("context_window", 128000))
                tools = bool(item.get("supports_tools", preset.get("supports_tools", True)))
                
                # Check if it's a reasoning model (by name or preset)
                is_reasoning = bool(item.get("is_reasoning", preset.get("is_reasoning", False)))
                if any(x in model_id.lower() for x in ["o1", "o3", "deepseek-r1", "reasoning"]):
                    is_reasoning = True
                    
                explicit_score = bool(item.get("capability_score")) or bool(preset.get("capability_score"))
                cap_score = float(item.get("capability_score") or preset.get("capability_score", 0.0))
                vector = item.get("capability_vector") or preset.get("capability_vector")
                
                if vector is None and not explicit_score:
                    vector, cap_score = self._seed_values(model_id, price_in, price_out, is_reasoning, tools)
                entries.append(
                    ModelEntry(
                        id=str(model_id),
                        provider=str(item.get("provider") or preset.get("provider", "openai")),
                        price_in=price_in,
                        price_out=price_out,
                        cost_input=price_in,
                        cost_output=price_out,
                        context_window=ctx,
                        supports_tools=tools,
                        enabled=item.get("enabled", True),
                        is_reasoning=is_reasoning,
                 capability_score=cap_score,
                        max_usd_per_min=item.get("max_usd_per_min"),
                        capability_vector=vector,
                        max_output_tokens=item.get("max_output_tokens"),
                        supported_parameters=list(item.get("supported_parameters") or []),
                        input_modalities=list(item.get("input_modalities") or ["text"]),
                 )
                )
        for entry in entries:
            metadata = self.benchmarks.metadata(entry.id) if self.benchmarks is not None else {}
            if metadata:
                entry.context_window = int(metadata.get("context_length") or entry.context_window)
                entry.max_output_tokens = metadata.get("max_output_tokens") or entry.max_output_tokens
                entry.supported_parameters = list(metadata.get("supported_parameters") or entry.supported_parameters)
                entry.input_modalities = list(metadata.get("input_modalities") or entry.input_modalities)
                entry.supports_tools = entry.supports_tools and ("tools" in entry.supported_parameters or not entry.supported_parameters)
        return entries

    @staticmethod
    def _seed_values(model_id: str, price_in: float, price_out: float, is_reasoning: bool, tools: bool) -> tuple[dict[str, float], float]:
        import re
        match = re.search(r'(\d+(?:\.\d+)?)[bx]', model_id.lower())
        if match:
            params = float(match.group(1))
            bucket = 0.5 if params >= 65 else 0.4 if params >= 25 else 0.3 if params >= 10 else 0.2
            latency = 0.3 if params >= 65 else 0.4 if params >= 25 else 0.6 if params >= 10 else 0.8
        else:
            blended = price_in + price_out * 0.5
            bucket = 0.5 if blended >= 2.0 else 0.4 if blended >= 0.5 else 0.2
            latency = 0.5
        vector = {
            "reasoning": min(1.0, (0.8 if is_reasoning else bucket) if is_reasoning else bucket),
            "tool_reliability": 0.6 if tools else 0.3,
            "code_quality": min(1.0, bucket + (0.1 if any(x in model_id.lower() for x in ("coder", "code", "instruct", "opus", "sonnet", "deepseek", "qwen")) else 0.0)),
            "latency_class": latency,
        }
        return vector, round(sum(vector.values()) / 4, 3)

    @classmethod
    def _seed_entry(cls, entry: ModelEntry) -> None:
        vector, score = cls._seed_values(entry.id, entry.price_in, entry.price_out, entry.is_reasoning, entry.supports_tools)
        entry.capability_vector = vector
        entry.capability_score = score

    def _entry_cost(self, entry: ModelEntry) -> float:
        """Return the effective price per 1M tokens for a ModelEntry."""
        c_in = entry.cost_input if entry.cost_input > 0 else entry.price_in
        c_out = entry.cost_output if entry.cost_output > 0 else entry.price_out
        if c_in > 0 or c_out > 0:
            return float(c_in + 0.5 * c_out if c_out > 0 else c_in)
        return 0.0

    def select_by_sla(
        self,
        sla: CapabilitySLA,
        pseudo_model: str = "autoconduck",
    ) -> str:
        """Select the absolute cheapest model that satisfies the Capability SLA."""
        return self._select(sla, pseudo_model)[0]

    def select_by_sla_detailed(
        self, sla: CapabilitySLA, pseudo_model: str = "autoconduck"
    ) -> SelectionInfo:
        return self._select(sla, pseudo_model)[1]

    def _select(self, sla: CapabilitySLA, pseudo_model: str) -> tuple[str, SelectionInfo]:
        """Select a model and collect explainability without changing the hot path shape."""
        info = SelectionInfo(min_capability_score_applied=sla.min_capability_score)
        entries = self._get_model_entries()
        if not entries:
            fallback = resolve_orchestrator_model(self.config)
            info.model = fallback
            info.fallback_reason = "empty_pool"
            return fallback, info

        # 1. Filter enabled & non-degraded & excluded
        from autoconduck.routing import pricing
        eligible = [
            e for e in entries
            if e.enabled and not pricing.is_degraded(e.id) and e.id not in sla.exclude_models
        ]
        info.candidates_considered = len(eligible)
        binding = None
        if not eligible:
            eligible = [e for e in entries if e.enabled and e.id not in sla.exclude_models] or entries

        # 2. Filter by tools
        if sla.requires_tools:
            tool_supported = [e for e in eligible if e.supports_tools]
            if tool_supported:
                if len(tool_supported) < len(eligible):
                    info.candidates_excluded_by["tools"] = len(eligible) - len(tool_supported)
                    binding = "tools"
                eligible = tool_supported
            else:
                info.candidates_excluded_by["tools"] = len(eligible)
                info.fallback_reason = "tools_filter_empty"

        # 3. Filter by reasoning
        if sla.requires_reasoning:
            reasoning_supported = [e for e in eligible if e.is_reasoning]
            if reasoning_supported:
                if len(reasoning_supported) < len(eligible):
                    info.candidates_excluded_by["reasoning"] = len(eligible) - len(reasoning_supported)
                    binding = "reasoning"
                eligible = reasoning_supported
            else:
                info.candidates_excluded_by["reasoning"] = len(eligible)
                info.fallback_reason = "reasoning_filter_empty"

        # 4. Filter by min_context_window
        required_context = max(sla.min_context, sla.input_tokens + sla.min_output_tokens)
        if required_context > 0:
            ctx_matches = [e for e in eligible if e.context_window >= required_context and (e.max_output_tokens is None or e.max_output_tokens >= sla.min_output_tokens)]
            if ctx_matches:
                if len(ctx_matches) < len(eligible):
                    info.candidates_excluded_by["context"] = len(eligible) - len(ctx_matches)
                    binding = "context"
                eligible = ctx_matches
            else:
                eligible = sorted(eligible, key=lambda e: -e.context_window)

        if sla.requires_structured_output:
            structured = [e for e in eligible if "response_format" in e.supported_parameters or "structured_outputs" in e.supported_parameters]
            if structured:
                if len(structured) < len(eligible):
                    info.candidates_excluded_by["structured_output"] = len(eligible) - len(structured)
                    binding = "structured_output"
                eligible = structured
            else:
                info.candidates_excluded_by["structured_output"] = len(eligible)
                info.fallback_reason = "structured_output_filter_empty"

        if sla.requires_image_input:
            visual = [e for e in eligible if "image" in e.input_modalities]
            if visual:
                if len(visual) < len(eligible):
                    info.candidates_excluded_by["image_input"] = len(eligible) - len(visual)
                    binding = "image_input"
                eligible = visual
            else:
                info.candidates_excluded_by["image_input"] = len(eligible)
                info.fallback_reason = "image_input_filter_empty"

        # 4.5 Filter by min_capability_score
        if sla.min_capability_score > 0.0:
            weights = task_weights(sla.task_type)
            def fit(entry: ModelEntry) -> float:
                vector = entry.capability_vector
                if vector is None and entry.capability_score is not None:
                    vector = {dim: float(entry.capability_score) for dim in CAPABILITY_DIMS}
                return capability_fit(vector, weights) if vector is not None else entry.capability_score
            cap_matches = [e for e in eligible if fit(e) >= sla.min_capability_score]
            if cap_matches:
                if len(cap_matches) < len(eligible):
                    info.candidates_excluded_by["capability_floor"] = len(eligible) - len(cap_matches)
                    binding = "capability_floor"
                eligible = cap_matches
            else:
                eligible = sorted(eligible, key=lambda e: -fit(e))
                binding = "capability_floor"

        # 4.75 Benchmark policy ranking.  Scores are only meaningful within the
        # source/category cohort normalized by BenchmarkRegistry; no raw source
        # metrics enter selection.  A missing/stale snapshot preserves static
        # capability routing rather than inventing a zero score.
        benchmark_scores: dict[str, float] = {}
        if sla.domain or sla.role:
            from autoconduck.routing.benchmarks import profile_for
            profile = profile_for(sla.domain, sla.role)
            info.benchmark_profile = profile
            registry = self.benchmarks
            if registry is not None and getattr(registry, "is_fresh", False):
                try:
                    snapshot_time = registry.as_of.replace("Z", "+00:00")
                    from datetime import datetime, timezone
                    info.benchmark_snapshot_age_hours = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(snapshot_time)).total_seconds() / 3600)
                except Exception:
                    pass
                benchmark_scores = {entry.id: score for entry in eligible if (score := registry.profile_score(entry.id, profile)) is not None}
            if benchmark_scores:
                info.benchmark_coverage_state = "covered"
            else:
                info.benchmark_coverage_state = "unavailable"
                info.fallback_reason = info.fallback_reason or "benchmark_coverage_unavailable"

        # 5. Filter by max_cost (only if there are eligible models below the ceiling)
        cost_matches = [e for e in eligible if self._entry_cost(e) <= sla.max_cost]
        if cost_matches:
            if len(cost_matches) < len(eligible):
                info.candidates_excluded_by["cost"] = len(eligible) - len(cost_matches)
                binding = "cost"
            eligible = cost_matches

        if not eligible:
            model = resolve_orchestrator_model(self.config) or entries[0].id
            info.model = model
            info.fallback_reason = "sla_emptied_pool"
            info.binding_constraint = binding
            return model, info

        pre_ceiling = eligible
        if sla.max_price_usd_per_mtok is not None:
            cap = float(sla.max_price_usd_per_mtok)
            ceiling_matches = [e for e in eligible if self._entry_cost(e) <= cap]
            removed = len(pre_ceiling) - len(ceiling_matches)
            if removed:
                info.candidates_excluded_by["price_cap"] = removed
                info.spend_cap_engaged = True
                binding = "price_cap"
            if ceiling_matches:
                eligible = ceiling_matches
            else:
                info.spend_cap_engaged = True
                info.fallback_reason = "price_cap_emptied_pool"
                eligible = pre_ceiling

        if len(eligible) == 1:
            info.model = eligible[0].id
            self._set_capability_info(info, eligible[0], sla)
            if eligible[0].id in benchmark_scores:
                info.benchmark_score = benchmark_scores[eligible[0].id]
            info.binding_constraint = binding
            return eligible[0].id, info

        weights = task_weights(sla.task_type)

        def fit(entry: ModelEntry) -> float:
            vector = entry.capability_vector
            if vector is None and entry.capability_score is not None:
                vector = {dim: float(entry.capability_score) for dim in CAPABILITY_DIMS}
            return capability_fit(vector, weights) if vector is not None else entry.capability_score

        # Sort remaining models strictly by absolute cost ascending, tiebreaking equal cost by capability
        sorted_models = sorted(
            eligible,
            key=lambda e: (self._entry_cost(e), -fit(e), -e.context_window, e.id),
        )

        if benchmark_scores:
            best_score = max(benchmark_scores.values())
            band_pct = float(getattr(getattr(self.config, "selection", None), "benchmark_quality_band_pct", 0.10))
            quality_band = [entry for entry in eligible if entry.id in benchmark_scores and benchmark_scores[entry.id] >= best_score - band_pct]
            if quality_band:
                sorted_models = sorted(quality_band, key=lambda e: (self._entry_cost(e), -benchmark_scores[e.id], e.id))

        # If the user invoked a high-end pseudo-model explicitly, we might bias towards the top of the eligible list
        if "expensive" in str(pseudo_model):
            info.model = sorted_models[-1].id
            self._set_capability_info(info, sorted_models[-1], sla)
            if sorted_models[-1].id in benchmark_scores:
                info.benchmark_score = benchmark_scores[sorted_models[-1].id]
            info.binding_constraint = binding
            return sorted_models[-1].id, info

        selected = sorted_models[0]
        band_pct = float(getattr(getattr(self.config, "selection", None), "capability_tiebreak_price_band_pct", 0.0))
        if band_pct > 0.0:
            cheapest_cost = self._entry_cost(sorted_models[0])
            band = [e for e in sorted_models if self._entry_cost(e) <= cheapest_cost * (1.0 + band_pct)]
            selected = min(band, key=lambda e: (-fit(e), self._entry_cost(e), e.id))

        info.model = selected.id
        self._set_capability_info(info, selected, sla)
        if selected.id in benchmark_scores:
            info.benchmark_score = benchmark_scores[selected.id]
        info.binding_constraint = binding
        return selected.id, info

    @staticmethod
    def _set_capability_info(info: SelectionInfo, entry: ModelEntry, sla: CapabilitySLA) -> None:
        vector = entry.capability_vector
        if vector is None and entry.capability_score is not None:
            vector = {dim: float(entry.capability_score) for dim in CAPABILITY_DIMS}
        if vector is not None:
            info.capability_fit_applied = capability_fit(vector, task_weights(sla.task_type))
            dominant = [dim for dim, weight in task_weights(sla.task_type).items() if weight > 0.25]
            dims = dominant or list(CAPABILITY_DIMS)
            info.binding_capability_dim = min(dims, key=lambda dim: vector.get(dim, 0.0))
