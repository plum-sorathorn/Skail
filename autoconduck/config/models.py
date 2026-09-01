"""Configuration data models and schemas."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field, field_validator


class ModelEntry(BaseModel):
    id: str
    provider: str = "openai"
    api_key_env: str = "OPENAI_API_KEY"
    api_key: str | None = None
    base_url: str | None = None
    anthropic_base_url: str | None = None
    api_base: str | None = None
    price_in: float = 0.0
    price_out: float = 0.0
    cost_input: float = 0.0
    cost_output: float = 0.0
    context_window: int = 128000
    supports_tools: bool = True
    is_reasoning: bool = False
    enabled: bool = True
    max_usd_per_min: float | None = None
    capability_score: float = 0.0
    capability_vector: dict[str, float] | None = None
    max_output_tokens: int | None = None
    supported_parameters: list[str] = Field(default_factory=list)
    input_modalities: list[str] = Field(default_factory=lambda: ["text"])
    output_modalities: list[str] = Field(default_factory=lambda: ["text"])


class SelectionConfig(BaseModel):
    phase_role_cards: bool = True
    dump_prompts: bool = False
    progress_verbosity: str = "verbose"
    """Selection controls; pool entries may set quality_score and max_usd_per_min."""

    # 0.3.0 SLM Architecture & Dynamic DAG Tunables
    slm_model_path: str = "models/qwen2.5-coder-0.5b-instruct-q4.onnx"
    slm_circuit_breaker_timeout_ms: int = 2000
    session_guard_compaction_ratio: float = 0.80
    rag_max_tokens: int = 250
    rag_db_path: str = "~/.autoconduck/rag_db"
    rag_embedding_model: str = ""

    closeness_epsilon: float = 0.02
    expose_value_in_stats: bool = True
    quality_min_success_rate: float = 0.5
    path_price_cap_usd_per_mtok: dict[str, float] = Field(
        default_factory=dict
    )
    confidence_floor_k: float = 0.15
    confidence_floor_max: float = 0.6
    capability_tiebreak_price_band_pct: float = 0.0
    """Optional capability tiebreak band; 0.0 disables it (current behavior)."""
    max_pool_size: int = 200
    benchmark_snapshot_max_age_hours: int = 168
    benchmark_quality_band_pct: float = 0.10
    enable_fast_path_graph: bool = True
    executor_enable_tools: bool = True
    executor_max_tool_rounds: int = 10
    executor_tool_time_budget_s: float = 180.0
    executor_max_read_bytes: int = 200_000
    executor_enable_bash: bool = False

    @field_validator("progress_verbosity", mode="before")
    @classmethod
    def _valid_progress_verbosity(cls, value):
        return value if value in {"off", "terse", "verbose"} else "terse"


class PluginConfig(BaseModel):
    enabled: bool = False
    claude_enabled: bool = False
    omp_enabled: bool = False
    subagent_enabled: bool = False
    rag_enabled: bool = True
    pi_enabled: bool = False
    opencode_enabled: bool = False
    ledger_retention_days: int = 30
    escalation_ttl_turns: int = 10
    escalation_floor_bump: float = 0.15
    llm_synthesis_enabled: bool = False
    execute_enabled: bool = False
    oma_enabled: bool = True
    oma_mode: str = "auto"
    oma_node_path: str | None = None


class ClaudeCodeSettings(BaseModel):
    allowed_tools: list[str] = [
        "Task",
        "Skill",
        "Git",
        "Read",
        "Write",
        "Edit",
        "WebFetch",
    ]
    default_mode: str | None = None
    enable_all_project_mcp_servers: bool = False


class PiSettings(BaseModel):
    """Pi coding-agent integration settings."""

    enabled: bool = True
    model: str | None = None
    provider: str = "autoconduck"
    api_key_env: str = "PI_API_KEY"
    api_key: str | None = None
    base_url: str | None = None
    context_window: int = 1000000
    model_entries: list[ModelEntry] = Field(default_factory=list)


class Config(BaseModel):
    host: str = "127.0.0.1"
    port: int = 11434
    log_level: str = "INFO"
    stack_trace_boost: float = 0.25
    ema_alpha: float = 0.1
    degraded_error_rate: float = 0.20
    degraded_window_s: int = 300
    fast_path_digest_enabled: bool = True
    fast_path_digest_max_files: int = 4
    fast_path_digest_max_bytes: int = 8192
    fast_path_digest_max_lines: int = 40
    fast_path_digest_timeout_ms: int = 150
    fast_path_digest_max_total_bytes: int = 12000
    fast_path_digest_min_files: int = 2
    pseudo_model: str = "autoconduck"
    models: dict[str, ModelEntry] = Field(default_factory=dict)
    model_list: list[dict] = Field(default_factory=list)
    routing_log: bool = True
    selected_presets: list[str] = Field(default_factory=list)
    custom_models: list[dict] = Field(default_factory=list)
    preset_overrides: dict[str, list[dict]] = Field(default_factory=dict)
    shims: dict[str, str] = Field(default_factory=dict)
    managed_server: bool = False
    launch_in_new_terminal: bool = False
    selection: SelectionConfig = Field(default_factory=SelectionConfig)
    plugins: PluginConfig = Field(default_factory=PluginConfig)
    claude_code: ClaudeCodeSettings = Field(default_factory=ClaudeCodeSettings)
    pi: PiSettings = Field(default_factory=PiSettings)
