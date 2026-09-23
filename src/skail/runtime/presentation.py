from __future__ import annotations

import json
from typing import Any

_ANSWER_FIELDS = (
    "answer",
    "final_answer",
    "response",
    "message",
    "reply",
    "content",
    "text",
    "output",
    "result",
    "final",
    "summary",
)
_EVIDENCE_FIELDS = frozenset(
    {"verification", "success_criteria", "execution_decision", "route", "route_snapshot"}
)
_NO_USER_ANSWER = "The model returned structured evidence without a user-facing answer."


def _unfence(text: str) -> str:
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        return "\n".join(lines[1:-1]).strip()
    return text


def _contains_evidence_fields(value: Any) -> bool:
    if isinstance(value, dict):
        if any(str(key).casefold() in _EVIDENCE_FIELDS for key in value):
            return True
        return any(_contains_evidence_fields(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_evidence_fields(item) for item in value)
    return False


def present_lead_answer(output: str) -> str:
    """Render a user-facing answer while keeping structured run evidence intact."""

    text = output.strip()
    if not text:
        return ""
    candidate = _unfence(text)
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return candidate
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, dict):
        for field in _ANSWER_FIELDS:
            value = payload.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False, indent=2)
        if _contains_evidence_fields(payload):
            return _NO_USER_ANSWER
    return json.dumps(payload, ensure_ascii=False, indent=2)


def model_content_to_text(content: Any) -> str:
    """Convert message content without exposing Python container representations."""

    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, list):
        text_blocks: list[str] = []
        for item in content:
            if isinstance(item, str):
                text_blocks.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                text_blocks.append(item["text"])
        if text_blocks:
            return "\n".join(text_blocks)
    if isinstance(content, (dict, list)):
        return json.dumps(content, ensure_ascii=False)
    if isinstance(content, (bool, int, float)):
        return str(content)
    return "The model returned unsupported structured content."


def structured_output_for_jsonl(output: Any) -> Any:
    """Keep valid structured final output as JSON data in the completion event."""

    if not isinstance(output, str):
        return output
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return output
