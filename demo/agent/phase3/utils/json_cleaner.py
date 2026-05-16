from __future__ import annotations

import dataclasses
import json
import re
from typing import Any


def clean_for_json(value: Any, max_str_len: int = 1000) -> Any:
    if dataclasses.is_dataclass(value):
        return clean_for_json(dataclasses.asdict(value), max_str_len=max_str_len)
    if isinstance(value, str):
        text = " ".join(value.split())
        return text[:max_str_len]
    if isinstance(value, dict):
        return {str(k): clean_for_json(v, max_str_len=max_str_len) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [clean_for_json(v, max_str_len=max_str_len) for v in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:max_str_len]


def loads_json_object(content: Any) -> dict[str, Any]:
    """Load a model JSON object while tolerating common wrapper noise."""

    text = extract_json_object_text(content)
    data = json.loads(text)
    if isinstance(data, dict):
        return data
    raise ValueError(f"expected JSON object, got {type(data).__name__}")


def extract_json_object_text(content: Any) -> str:
    text = str(content or "").strip()
    if not text:
        return "{}"
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    if text.startswith("{") and text.endswith("}"):
        return _remove_trailing_commas(text)

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return _remove_trailing_commas(text[start:end + 1])
    return "{}"


def _remove_trailing_commas(text: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", text)
