from __future__ import annotations

import hashlib

from agent.phase3.memory.memory_schema import FailurePattern, ReflectionHint


class ReflectionAgent:
    """Deterministic reflection skeleton.

    It turns observed failure patterns into advisory hints only. It never
    creates candidate ids, cargo ids, order ids, final actions, or hard rules.
    """

    def generate_hints(self, patterns: list[FailurePattern]) -> list[ReflectionHint]:
        hints: list[ReflectionHint] = []
        for pattern in patterns:
            message = _sanitize_hint(pattern.suggested_hint)
            if not message:
                continue
            hints.append(ReflectionHint(
                hint_id=_hint_id(pattern),
                driver_id=pattern.driver_id,
                scope="advisor",
                priority=_priority(pattern),
                message=message,
                applies_to_goal_type=pattern.goal_type,
                expires_after_day=(pattern.day_index + 1) if pattern.day_index is not None else None,
                evidence_refs=(pattern.pattern_id,),
                failure_type=pattern.failure_type,
                confidence=pattern.confidence,
            ))
        return hints


def _priority(pattern: FailurePattern) -> str:
    if pattern.severity == "high" and pattern.confidence >= 0.75:
        return "high"
    if pattern.severity in {"high", "medium"}:
        return "medium"
    return "low"


def _hint_id(pattern: FailurePattern) -> str:
    raw = f"{pattern.driver_id}:{pattern.failure_type}:{pattern.goal_type or ''}:{pattern.day_index}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _sanitize_hint(text: str) -> str:
    cleaned = str(text or "").strip()
    blocked = ("candidate_id", "cargo_id", "order_id", "final_action")
    for token in blocked:
        cleaned = cleaned.replace(token, "runtime identifier")
    return cleaned[:240]
