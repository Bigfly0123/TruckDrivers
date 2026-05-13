from __future__ import annotations

import dataclasses
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
