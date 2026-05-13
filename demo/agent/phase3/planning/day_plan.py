from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class DayPlan:
    driver_id: str
    day: int
    strategy_summary: str
    primary_goal: str
    secondary_goals: list[str] = field(default_factory=list)
    risk_focus: list[str] = field(default_factory=list)
    constraint_priorities: list[str] = field(default_factory=list)
    rest_strategy: str | None = None
    work_window_strategy: str | None = None
    location_strategy: str | None = None
    cargo_strategy: str | None = None
    avoid_behaviors: list[str] = field(default_factory=list)
    advisor_guidance: list[str] = field(default_factory=list)
    confidence: float | None = None
    reason: str | None = None
    raw_response: dict[str, Any] | None = None
    fallback_used: bool = False

    def to_advisor_context(self) -> dict[str, Any]:
        return {
            "strategy_summary": self.strategy_summary,
            "primary_goal": self.primary_goal,
            "risk_focus": list(self.risk_focus),
            "constraint_priorities": list(self.constraint_priorities),
            "rest_strategy": self.rest_strategy,
            "work_window_strategy": self.work_window_strategy,
            "location_strategy": self.location_strategy,
            "cargo_strategy": self.cargo_strategy,
            "avoid_behaviors": list(self.avoid_behaviors),
            "advisor_guidance": list(self.advisor_guidance),
            "confidence": self.confidence,
            "reason": self.reason,
        }

    def to_summary(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("raw_response", None)
        return data
