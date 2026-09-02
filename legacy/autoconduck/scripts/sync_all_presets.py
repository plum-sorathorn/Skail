"""Unified updater for all model presets and the catalog documentation."""

from __future__ import annotations

import json
import socket
import sys
import urllib.request
from pathlib import Path
from typing import Any

socket.setdefaulttimeout(3.0)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
UPSTREAM_LITELLM_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
DEVPASS_MODELS_URL = "https://devpass.llmgateway.io/models"
LLMGATEWAY_MODELS_URL = "https://api.llmgateway.io/v1/models"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "groq": "GROQ_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "together": "TOGETHER_API_KEY",
    "xai": "XAI_API_KEY",
    "devpass": "DEVPASS_API_KEY",
    "llmgateway": "LLMGATEWAY_API_KEY",
}


def fetch_upstream_litellm_costs() -> dict[str, dict[str, Any]]:
    """Fetch the latest upstream LiteLLM model database."""
    try:
        req = urllib.request.Request(
            UPSTREAM_LITELLM_URL, headers={"User-Agent": "autoconduck/1.0"}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            out = {}
            for k, v in data.items():
                if isinstance(v, dict) and "input_cost_per_token" in v:
                    out[k] = {
                        "price_in": float(v.get("input_cost_per_token", 0)) * 1_000_000,
                        "price_out": float(v.get("output_cost_per_token", 0))
                        * 1_000_000,
                        "provider": v.get("litellm_provider", "openai"),
                        "mode": v.get("mode", "chat"),
                    }
            return out
    except Exception as exc:
        print(
            f"Warning: could not fetch upstream LiteLLM database ({exc}); using installed package."
        )
        from autoconduck.model_presets import _ingest_litellm_costs

        return _ingest_litellm_costs()


def sort_gateway_models(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort gateway models alphabetically by model ID."""
    return sorted(entries, key=lambda entry: entry["id"].casefold())


def fetch_devpass_models(costs: dict[str, dict]) -> list[dict[str, Any]]:
    """Fetch models from DevPass endpoint or fallback."""
    try:
        from scripts.sync_devpass_presets import fetch_devpass_catalog

        return sort_gateway_models(fetch_devpass_catalog(costs))
    except Exception as exc:
        print(f"Warning: could not fetch DevPass models ({exc}); using fallback.")
        from autoconduck.presets.presets_fallback import FALLBACK_PRESETS

        entries = []
        for row in FALLBACK_PRESETS.get("llmgateway", []):
            copy_row = dict(row)
            copy_row["provider"] = "devpass"
            copy_row["api_key_env"] = "DEVPASS_API_KEY"
            entries.append(copy_row)
        return entries


def fetch_llmgateway_models(costs: dict[str, dict]) -> list[dict[str, Any]]:
    """Fetch models from LLMGateway or fallback."""
    try:
        req = urllib.request.Request(
            LLMGATEWAY_MODELS_URL, headers={"User-Agent": "autoconduck/1.0"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        entries = []
        from autoconduck.model_presets import normalize_model_id_for_provider

        for model in data.get("data", []):
            mid = normalize_model_id_for_provider(model["id"], "llmgateway")
            if any(
                x in mid.lower()
                for x in (
                    "embedding",
                    "image",
                    "video",
                    "tts",
                    "stt",
                    "transcribe",
                    "reranker",
                    "audio",
                )
            ):
                continue
            info = lookup_cost(costs, mid, "llmgateway") or lookup_cost(costs, model["id"], "llmgateway")
            p_in = info.get("price_in", 0.0)
            p_out = info.get("price_out", 0.0)
            tier = (
                "expensive"
                if p_out >= 20.0
                else "budget"
                if p_out < 3.0
                else "balanced"
            )
            entries.append(
                {
                    "id": mid,
                    "provider": "llmgateway",
                    "tier": tier,
                    "price_in": round(p_in, 4),
                    "price_out": round(p_out, 4),
                    "api_key_env": "LLMGATEWAY_API_KEY",
                    "base_url": "https://api.llmgateway.io",
                }
            )
        if entries:
            return sort_gateway_models(entries)
    except Exception as exc:
        print(f"Warning: could not fetch LLMGateway models ({exc}); using fallback.")
    from autoconduck.presets.presets_fallback import FALLBACK_PRESETS

    return list(FALLBACK_PRESETS.get("llmgateway", []))


def fetch_openrouter_models() -> list[dict[str, Any]]:
    """Fetch all text-output models from OpenRouter's public catalog."""
    try:
        req = urllib.request.Request(
            OPENROUTER_MODELS_URL, headers={"User-Agent": "autoconduck/1.0"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        entries = []
        for model in data.get("data", []):
            if not isinstance(model, dict) or not model.get("id"):
                continue
            architecture = model.get("architecture") or {}
            if "text" not in (architecture.get("output_modalities") or []):
                continue
            pricing = model.get("pricing") or {}
            price_in = float(pricing.get("prompt") or 0) * 1_000_000
            price_out = float(pricing.get("completion") or 0) * 1_000_000
            supported = set(model.get("supported_parameters") or [])
            entries.append(
                {
                    "id": str(model["id"]),
                    "provider": "openrouter",
                    "tier": (
                        "expensive"
                        if price_out >= 20.0
                        else "budget"
                        if price_out < 3.0
                        else "balanced"
                    ),
                    "price_in": round(price_in, 4),
                    "price_out": round(price_out, 4),
                    "context_window": int(model.get("context_length") or 128000),
                    "supports_tools": "tools" in supported,
                    "is_reasoning": bool(model.get("reasoning")) or "reasoning" in supported,
                    "api_key_env": "OPENROUTER_API_KEY",
                }
            )
        return sorted(entries, key=lambda entry: entry["id"].lower())
    except Exception as exc:
        print(f"Warning: could not fetch OpenRouter models ({exc}); using LiteLLM presets.")
        return []


def lookup_cost(costs: dict[str, dict[str, Any]], mid: str, provider: str = "") -> dict[str, Any]:
    """Find pricing entry matching mid or prefixed/unprefixed variants."""
    if mid in costs:
        return costs[mid]
    if f"{provider}/{mid}" in costs:
        return costs[f"{provider}/{mid}"]
    clean_mid = mid.split("/")[-1].lower()
    for k, v in costs.items():
        clean_k = k.split("/")[-1].lower()
        if clean_k == clean_mid or clean_k.startswith(f"{clean_mid}-20") or clean_k.startswith(f"{clean_mid}:"):
            return v
    return {}


NON_CHAT_KEYWORDS = (
    "embedding",
    "embed",
    "image",
    "video",
    "tts",
    "stt",
    "transcribe",
    "rerank",
    "reranker",
    "audio",
    "whisper",
    "dall-e",
    "moderation",
    "davinci-002",
    "babbage-002",
)

PROVIDER_LITELLM_MAP = {
    "openai": ["openai"],
    "anthropic": ["anthropic"],
    "google": ["google", "gemini", "vertex_ai"],
    "mistral": ["mistral", "mistralai"],
    "deepseek": ["deepseek"],
    "groq": ["groq"],
    "openrouter": ["openrouter"],
    "together": ["together", "together_ai"],
    "xai": ["xai"],
}


def build_provider_presets(
    costs: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Curate top models and dynamically discover all active chat models per provider."""
    # Preferred curated model shortlist per provider (prioritized at top of lists)
    provider_curations = {
        "anthropic": [
            "claude-3-7-sonnet",
            "claude-3-5-sonnet",
            "claude-3-5-haiku",
            "claude-3-opus",
            "claude-sonnet-4-6",
            "claude-sonnet-5",
            "claude-opus-5",
            "claude-haiku-4-5",
        ],
        "openai": [
            "gpt-4.5-preview",
            "gpt-4o",
            "gpt-4o-mini",
            "o1",
            "o3-mini",
            "o4-mini",
            "gpt-5.6",
            "gpt-5.2",
            "gpt-5-mini",
            "gpt-5.1-codex",
            "gpt-4.1",
        ],
        "google": [
            "gemini-3.7-flash",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.1-pro-preview",
        ],
        "mistral": [
            "codestral-2508",
            "devstral-2512",
            "mistral-large-latest",
            "mistral-small-latest",
            "ministral-8b-latest",
        ],
        "deepseek": [
            "deepseek-chat",
            "deepseek-reasoner",
            "deepseek-v3.2",
            "deepseek-v4-flash",
            "deepseek-v4-pro",
        ],
        "groq": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
            "deepseek-r1-distill-llama-70b",
        ],
        "openrouter": [
            "openrouter/auto",
            "anthropic/claude-3.5-sonnet",
            "openai/gpt-4o",
            "deepseek/deepseek-r1",
            "google/gemini-2.5-flash",
        ],
        "together": [
            "togethercomputer/llama-3.3-70b-instruct",
            "meta-llama/Llama-3.3-70B-Instruct-Turbo",
            "deepseek-ai/DeepSeek-R1",
            "deepseek-ai/DeepSeek-V3",
        ],
        "xai": [
            "grok-2-latest",
            "grok-2-vision-latest",
            "grok-beta",
            "grok-4.5",
            "grok-4-6",
        ],
    }

    presets: dict[str, list[dict[str, Any]]] = {}
    seen_ids: dict[str, set[str]] = {p: set() for p in provider_curations}

    # 1. Curated top models first
    for provider, candidates in provider_curations.items():
        rows = []
        for mid in candidates:
            info = lookup_cost(costs, mid, provider)
            p_in = info.get("price_in", 0.0)
            p_out = info.get("price_out", 0.0)
            tier = (
                "expensive"
                if p_out >= 20.0
                else "budget"
                if p_out < 3.0
                else "balanced"
            )
            rows.append(
                {
                    "id": mid,
                    "provider": provider,
                    "tier": tier,
                    "price_in": round(p_in, 4),
                    "price_out": round(p_out, 4),
                    "api_key_env": ENV_KEYS.get(
                        provider, f"{provider.upper()}_API_KEY"
                    ),
                }
            )
            seen_ids[provider].add(mid.lower())
        presets[provider] = rows

    # 2. Dynamically discover additional chat models from LiteLLM registry
    from autoconduck.presets.presets_ingest import clean_model_id

    for model_id, info in costs.items():
        raw_provider = info.get("provider", "").lower()
        mode = info.get("mode", "chat")
        if mode not in ("chat", "completion", "instruct") and mode != "chat":
            continue

        clean_id = clean_model_id(model_id)
        if any(kw in clean_id.lower() for kw in NON_CHAT_KEYWORDS):
            continue

        # Match to supported provider
        matched_provider = None
        for target_p, aliases in PROVIDER_LITELLM_MAP.items():
            if raw_provider in aliases:
                matched_provider = target_p
                break
            if "/" in model_id:
                prefix = model_id.split("/")[0].lower()
                if prefix in aliases:
                    matched_provider = target_p
                    break

        if not matched_provider or clean_id.lower() in seen_ids.get(matched_provider, set()):
            continue

        # Exclude random synthetic benchmark or preview IDs with @ or internal tags
        if "@" in clean_id or ":" in clean_id:
            continue

        p_in = info.get("price_in", 0.0)
        p_out = info.get("price_out", 0.0)
        tier = (
            "expensive"
            if p_out >= 20.0
            else "budget"
            if p_out < 3.0
            else "balanced"
        )
        presets.setdefault(matched_provider, []).append(
            {
                "id": clean_id,
                "provider": matched_provider,
                "tier": tier,
                "price_in": round(p_in, 4),
                "price_out": round(p_out, 4),
                "api_key_env": ENV_KEYS.get(
                    matched_provider, f"{matched_provider.upper()}_API_KEY"
                ),
            }
        )
        seen_ids.setdefault(matched_provider, set()).add(clean_id.lower())

    return {
        provider: sorted(rows, key=lambda row: row["id"].casefold())
        for provider, rows in sorted(presets.items(), key=lambda item: item[0].casefold())
    }


def sync_all() -> dict[str, list[dict[str, Any]]]:
    print("1. Fetching upstream LiteLLM model & pricing database...")
    costs = fetch_upstream_litellm_costs()
    print(f"   Fetched pricing for {len(costs)} models.")

    print(
        "2. Building curated presets for Anthropic, OpenAI, Google, Mistral, DeepSeek..."
    )
    presets = build_provider_presets(costs)

    print("3. Fetching OpenRouter models from https://openrouter.ai/api/v1/models...")
    openrouter_models = fetch_openrouter_models()
    if openrouter_models:
        presets["openrouter"] = openrouter_models
    print(f"   Synced {len(presets.get('openrouter', []))} OpenRouter models.")

    print("4. Fetching DevPass models from https://devpass.llmgateway.io/models...")
    devpass_models = fetch_devpass_models(costs)
    presets["devpass"] = devpass_models
    print(f"   Synced {len(devpass_models)} DevPass models.")

    print("5. Fetching LLMGateway models from https://api.llmgateway.io/v1/models...")
    llmgateway_models = fetch_llmgateway_models(costs)
    presets["llmgateway"] = llmgateway_models
    print(f"   Synced {len(llmgateway_models)} LLMGateway models.")

    return presets


def merge_with_existing(new_presets: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """Merge newly fetched presets with existing preset metadata (preserving custom scores/vectors)."""
    try:
        from autoconduck.presets.presets_data import PRESETS as existing_presets
    except Exception:
        existing_presets = {}

    merged: dict[str, list[dict[str, Any]]] = {}
    for provider, new_rows in new_presets.items():
        existing_rows_map = {row["id"]: row for row in existing_presets.get(provider, [])}
        merged_rows = []
        for new_row in new_rows:
            mid = new_row["id"]
            if mid in existing_rows_map:
                row_copy = dict(existing_rows_map[mid])
                row_copy.update(new_row)
                merged_rows.append(row_copy)
            else:
                merged_rows.append(new_row)
        merged[provider] = merged_rows

    for provider, existing_rows in existing_presets.items():
        if provider not in merged and provider not in ("ollama", "lmstudio", "vllm"):
            merged[provider] = list(existing_rows)

    return merged


def format_python_presets(presets: dict[str, list[dict[str, Any]]]) -> str:
    """Format presets dictionary as valid python source code for presets_data.py."""
    lines = [
        "from __future__ import annotations",
        "",
        "from pathlib import Path",
        "from typing import Any",
        "",
        'FALLBACK_PATH = Path(__file__).parent / "pricing_fallback.json"',
        "",
        "CATALOG_SHORTLIST = (",
        '    "gpt-4o",',
        '    "gpt-4o-mini",',
        '    "o1-mini",',
        '    "claude-3-5-sonnet-20241022",',
        '    "claude-3-5-haiku-20241022",',
        '    "claude-3-opus-20240229",',
        '    "gemini-1.5-pro",',
        '    "gemini-1.5-flash",',
        '    "mistral-large-latest",',
        '    "llama-3.1-70b-instruct",',
        ")",
        "",
        "# Preset groups",
        "",
        "from .presets_fallback import FALLBACK_PRESETS",
        "PRESETS: dict[str, list[dict[str, Any]]] = {",
    ]

    for provider, rows in sorted(presets.items(), key=lambda item: item[0].casefold()):
        if provider in ("ollama", "lmstudio", "vllm"):
            continue
        lines.append(f'    "{provider}": [')
        for row in sorted(rows, key=lambda item: item["id"].casefold()):
            lines.append("        {")
            for k, v in row.items():
                if isinstance(v, str):
                    lines.append(f'            "{k}": "{v}",')
                elif isinstance(v, (int, float, bool)):
                    lines.append(f'            "{k}": {v},')
                elif isinstance(v, (dict, list)):
                    lines.append(f'            "{k}": {repr(v)},')
            lines.append("        },")
        lines.append("    ],")

    lines.extend([
        "}",
        "# Fill in local offline defaults (e.g. ollama) only if not already configured in PRESETS",
        "for _p, _models in FALLBACK_PRESETS.items():",
        "    if _p not in PRESETS:",
        "        PRESETS[_p] = _models",
        "",
        "PRESETS = {",
        '    _provider: sorted(_models, key=lambda row: str(row["id"]).casefold())',
        '    for _provider, _models in sorted(PRESETS.items(), key=lambda item: item[0].casefold())',
        "}",
        "",
        'PRESET_ORDER = sorted(["custom", *PRESETS], key=str.casefold)',
        "",
        "# Compatibility exports from the original ``model_presets`` module.  Keep",
        "# these derived from PRESETS so the catalog cannot silently drift from the",
        "# preset data when a provider adds or removes a model.",
        'DEFAULT_MODELS = [row["id"] for rows in PRESETS.values() for row in rows]',
        "MODEL_IDS = list(DEFAULT_MODELS)",
        "",
    ])

    return "\n".join(lines)


def write_fallback_presets(presets: dict[str, list[dict[str, Any]]]) -> Path:
    """Atomically write formatted fallback presets into presets_fallback.py."""
    import os
    import tempfile

    target = ROOT / "autoconduck" / "presets" / "presets_fallback.py"
    target.parent.mkdir(parents=True, exist_ok=True)

    fallback_data = {
        "devpass": presets.get("devpass", []),
        "llmgateway": presets.get("llmgateway", []),
    }

    lines = [
        "from __future__ import annotations",
        "",
        "# Large provider-specific fallback preset literals.",
        "FALLBACK_PRESETS = {",
    ]
    for provider, rows in fallback_data.items():
        lines.append(f'    "{provider}": [')
        for row in rows:
            lines.append(f"        {repr(row)},")
        lines.append("    ],")
    lines.append("}")
    lines.append("")

    content = "\n".join(lines)
    fd, temporary = tempfile.mkstemp(prefix=".presets_fallback.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return target


def write_presets_data(presets: dict[str, list[dict[str, Any]]]) -> Path:
    """Atomically write formatted presets into autoconduck/presets/presets_data.py."""
    import os
    import tempfile

    target = ROOT / "autoconduck" / "presets" / "presets_data.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    content = format_python_presets(presets)
    fd, temporary = tempfile.mkstemp(prefix=".presets_data.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return target


def write_catalog_docs() -> Path:
    """Atomically regenerate docs/model_catalog.md snapshot."""
    import importlib
    import os
    import tempfile

    try:
        # Reload preset modules so they pick up newly written presets_data.py
        for mod_name in list(sys.modules.keys()):
            if "preset" in mod_name or "catalog" in mod_name:
                try:
                    importlib.reload(sys.modules[mod_name])
                except Exception:
                    pass

        from scripts.refresh_catalog import render_catalog, curated_model_catalog

        destination = ROOT / "docs" / "model_catalog.md"
        destination.parent.mkdir(parents=True, exist_ok=True)
        generated = render_catalog(curated_model_catalog())
        fd, temporary = tempfile.mkstemp(prefix=".model_catalog.", suffix=".tmp", dir=destination.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(generated)
            os.replace(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return destination
    except Exception as exc:
        print(f"Warning: could not refresh docs/model_catalog.md ({exc})")
        return ROOT / "docs" / "model_catalog.md"


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Synchronize model presets and catalog documentation from upstream LiteLLM and gateway endpoints."
    )
    parser.add_argument(
        "--write",
        action="store_true",
        default=True,
        help="Write updated presets directly to autoconduck/presets/presets_data.py (default: True)",
    )
    parser.add_argument(
        "--no-write",
        "--dry-run",
        dest="write",
        action="store_false",
        help="Dry run: print synced presets without writing to files",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check whether presets_data.py matches upstream without modifying it",
    )
    parser.add_argument(
        "--no-docs",
        action="store_true",
        help="Skip updating docs/model_catalog.md",
    )
    args = parser.parse_args()

    presets = sync_all()
    merged = merge_with_existing(presets)

    print("\nSummary of synced presets:")
    total_models = 0
    for k, v in merged.items():
        print(f"  - {k}: {len(v)} models")
        total_models += len(v)
    print(f"Total: {total_models} models across {len(merged)} providers.")

    if args.check:
        target = ROOT / "autoconduck" / "presets" / "presets_data.py"
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        generated = format_python_presets(merged)
        if existing == generated:
            print("\n[OK] presets_data.py is up to date.")
            return 0
        else:
            print("\n[STALE] presets_data.py differs from upstream.")
            return 1

    if args.write:
        target_path = write_presets_data(merged)
        print(f"\n[SUCCESS] Wrote updated presets to {target_path}")

        fallback_path = write_fallback_presets(merged)
        print(f"[SUCCESS] Wrote updated fallback presets to {fallback_path}")

        if not args.no_docs:
            doc_path = write_catalog_docs()
            print(f"[SUCCESS] Refreshed catalog documentation at {doc_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
