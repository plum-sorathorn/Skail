from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from skail.config.persistence import save_user_provider_models, save_user_routing_model

pytestmark = pytest.mark.unit


def test_provider_model_update_preserves_nested_tables_and_array_of_tables(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[providers.openai]\n'
        'type = "openai-compatible"\n'
        'models = ["old-model"]\n'
        '\n[catalog]\n'
        'source = "cached"\n'
        '\n[[catalog.entries]]\n'
        'name = "model-a"\n'
        'tags = ["fast", "reasoning"]\n'
        '\n[catalog.entries.capability]\n'
        'context_window = 128000\n'
        '\n[[catalog.entries]]\n'
        'name = "model-b"\n'
        '\n[catalog.entries.capability]\n'
        'context_window = 64000\n',
        encoding="utf-8",
    )

    save_user_provider_models("openai", ["new-model"], config_path=config_path)

    with config_path.open("rb") as handle:
        data = tomllib.load(handle)
    assert data["providers"]["openai"]["models"] == ["new-model"]
    assert data["catalog"] == {
        "source": "cached",
        "entries": [
            {
                "name": "model-a",
                "tags": ["fast", "reasoning"],
                "capability": {"context_window": 128000},
            },
            {
                "name": "model-b",
                "capability": {"context_window": 64000},
            },
        ],
    }


def test_model_persistence_round_trips_toml_escaped_strings(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    model = 'provider:model "quoted" \\ path\nsecond line — 日本語'

    save_user_routing_model(model, config_path=config_path)

    with config_path.open("rb") as handle:
        data = tomllib.load(handle)
    assert data["routing"]["lead_model"] == model


def test_routing_model_write_preserves_unrelated_configuration(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[providers.llmgateway]\n'
        'type = "openai-compatible"\n'
        'models = ["old-model"]\n'
        '\n[routing]\n'
        'mode = "auto"\n'
        '\n[safety]\n'
        'write_policy = "ask"\n',
        encoding="utf-8",
    )

    save_user_routing_model("llmgateway:new-model", config_path=config_path)

    with config_path.open("rb") as handle:
        data = tomllib.load(handle)
    assert data == {
        "providers": {
            "llmgateway": {
                "type": "openai-compatible",
                "models": ["old-model"],
            }
        },
        "routing": {"mode": "auto", "lead_model": "llmgateway:new-model"},
        "safety": {"write_policy": "ask"},
    }


def test_serialization_failure_preserves_original_config(tmp_path: Path, monkeypatch) -> None:
    import tomli_w

    import skail.config.persistence as persistence

    config_path = tmp_path / "config.toml"
    original = '[routing]\nmode = "auto"\n'
    config_path.write_text(original, encoding="utf-8")

    def fail_serialization(data: object) -> str:
        raise TypeError("serializer failed")

    monkeypatch.setattr(tomli_w, "dumps", fail_serialization)
    with pytest.raises(TypeError, match="serializer failed"):
        persistence.save_user_routing_model("new-model", config_path=config_path)

    assert config_path.read_text(encoding="utf-8") == original


def test_replace_failure_preserves_original_config(tmp_path: Path, monkeypatch) -> None:
    import skail.config.persistence as persistence

    config_path = tmp_path / "config.toml"
    original = '[routing]\nmode = "auto"\n'
    config_path.write_text(original, encoding="utf-8")

    def fail_replace(source: str, destination: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(persistence.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        persistence.save_user_routing_model("new-model", config_path=config_path)

    assert config_path.read_text(encoding="utf-8") == original
