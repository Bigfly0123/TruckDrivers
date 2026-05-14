from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FailurePattern:
    pattern_id: str
    driver_id: str
    day_index: int | None
    goal_id: str | None
    goal_type: str | None
    failure_type: str
    severity: str
    evidence: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    suggested_hint: str = ""
    confidence: float = 0.0


@dataclass(frozen=True)
class ReflectionHint:
    hint_id: str
    driver_id: str
    scope: str
    priority: str
    message: str
    applies_to_goal_type: str | None = None
    expires_after_day: int | None = None
    evidence_refs: tuple[str, ...] = ()
    failure_type: str = ""
    confidence: float = 0.0


@dataclass(frozen=True)
class DriverMemory:
    driver_id: str
    recent_failures: tuple[FailurePattern, ...] = ()
    active_hints: tuple[ReflectionHint, ...] = ()
    last_updated_day: int | None = None
