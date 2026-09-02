"""Unit tests for autoconduck._compat fallback shims."""

import pytest
from pydantic import BaseModel
from autoconduck._compat import (
    is_onnx_available,
    is_onnx_genai_available,
    get_onnx_model,
    ONNXModelFallback,
    is_outlines_available,
    OutlinesFallback,
    generate_structured_json,
    is_lancedb_available,
    lancedb_connect,
    LanceDBFallbackConnection,
)


def test_onnx_fallback_interface():
    """Test ONNX fallback and mock completion generation."""
    model = get_onnx_model("mock-qwen.onnx")
    assert model is not None

    resp = model.create_completion(prompt="Hello world", max_tokens=32)
    assert "choices" in resp
    assert len(resp["choices"]) > 0
    assert "text" in resp["choices"][0]
    assert resp["usage"]["prompt_tokens"] == 2

    chat_resp = model.create_chat_completion(
        messages=[{"role": "user", "content": "How are you?"}]
    )
    assert "choices" in chat_resp
    assert chat_resp["choices"][0]["message"]["role"] == "assistant"


class SimpleTestSchema(BaseModel):
    name: str = "default_name"
    count: int = 1


def test_outlines_fallback_interface():
    """Test Outlines fallback schema validation and generation."""
    mock_model = ONNXModelFallback("mock.onnx")
    gen = OutlinesFallback(mock_model).build_json_generator(SimpleTestSchema)
    result = gen("Generate schema")
    assert isinstance(result, SimpleTestSchema)
    assert hasattr(result, "name")
    assert hasattr(result, "count")

    direct_result = generate_structured_json(mock_model, "test prompt", SimpleTestSchema)
    assert isinstance(direct_result, SimpleTestSchema)


def test_lancedb_fallback_interface():
    """Test LanceDB in-memory fallback connection, table creation, and vector search."""
    db = LanceDBFallbackConnection(":memory:")
    table = db.create_table(
        "test_docs",
        data=[
            {"id": "doc1", "text": "fast path router", "vector": [1.0, 0.0, 0.0]},
            {"id": "doc2", "text": "dynamic dag factory", "vector": [0.0, 1.0, 0.0]},
            {"id": "doc3", "text": "sqlite checkpointer", "vector": [0.0, 0.0, 1.0]},
        ],
    )
    assert "test_docs" in db.table_names()
    assert table.count_rows() == 3

    # Query closest to doc1 vector [1.0, 0.0, 0.0]
    results = table.search(query=[0.95, 0.05, 0.0]).limit(2).to_list()
    assert len(results) == 2
    assert results[0]["id"] == "doc1"
    assert results[0]["_distance"] < 0.1

    # Filter with where clause
    where_results = table.search(query=[0.0, 0.0, 1.0]).where("id == 'doc3'").to_list()
    assert len(where_results) == 1
    assert where_results[0]["id"] == "doc3"

    db.drop_table("test_docs")
    assert "test_docs" not in db.table_names()


def test_multi_slm_catalog_support():
    """Verify all supported SLM models in catalog are valid and have corresponding tokenizer/weights specs."""
    from autoconduck.routing.slm_downloader import SLM_MODELS_CATALOG, get_slm_model_info

    supported_ids = ["qwen2.5-coder-0.5b-instruct", "qwen2.5-coder-1.5b-instruct", "lfm2.5-1.2b-instruct"]
    for mid in supported_ids:
        info = get_slm_model_info(mid)
        assert info is not None, f"Model {mid} not found in catalog"
        assert info["filename"].endswith(".onnx")
        assert len(info["extra_files"]) >= 1
        # Tokenizer file must exist in extra_files
        has_tokenizer = any(ef["filename"].endswith(".tokenizer.json") or "tokenizer" in ef["filename"] for ef in info["extra_files"])
        assert has_tokenizer, f"Model {mid} missing tokenizer in extra_files"


def test_onnx_direct_model_chatml_and_fallback_template():
    """Verify ChatML and fallback role formatting behavior."""
    from autoconduck._compat.onnx_fallback import ONNXModelFallback
    model = ONNXModelFallback("test-model.onnx")
    messages = [
        {"role": "system", "content": "You are a classifier."},
        {"role": "user", "content": "Classify this."},
    ]
    res = model.create_chat_completion(messages)
    assert "choices" in res
    assert res["choices"][0]["message"]["role"] == "assistant"



