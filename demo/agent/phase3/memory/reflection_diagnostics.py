from __future__ import annotations

from collections import Counter
from typing import Any

from agent.phase3.memory.memory_schema import FailurePattern, ReflectionHint


def reflection_summary(
    *,
    active_hints: list[ReflectionHint],
    new_failures: list[FailurePattern] | None = None,
    new_hints: list[ReflectionHint] | None = None,
    filtered_illegal_fields: int = 0,
) -> dict[str, Any]:
    failures = new_failures or []
    hints = new_hints or []
    return {
        "active_reflection_hint_count": len(active_hints),
        "reflection_hints_used": len(active_hints),
        "reflection_hint_priorities": dict(Counter(h.priority for h in active_hints)),
        "reflection_failure_types": dict(Counter(h.failure_type for h in active_hints if h.failure_type)),
        "new_failure_count": len(failures),
        "new_hint_count": len(hints),
        "new_failure_types": dict(Counter(p.failure_type for p in failures)),
        "reflection_filtered_illegal_fields": filtered_illegal_fields,
    }
