from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.phase3.domain.agent_models import GeoPoint


@dataclass(frozen=True)
class GoalStep:
    step_id: str
    step_type: str
    point: GeoPoint | None = None
    cargo_id: str | None = None
    deadline_minute: int | None = None
    earliest_minute: int | None = None
    required_minutes: int = 0
    label: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Goal:
    goal_id: str
    goal_type: str
    constraint_id: str
    priority: str
    penalty_amount: float = 0.0
    steps: tuple[GoalStep, ...] = ()
    raw_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GoalProgress:
    goal_id: str
    completed_step_ids: tuple[str, ...] = ()
    completed_step_count: int = 0
    current_step_index: int | None = None
    is_complete: bool = False
    current_step_progress_minutes: int = 0
    current_step_started_at: int | None = None
    step_completed_at: dict[str, int] = field(default_factory=dict)
    repeated_step_action_count: int = 0
    stuck_suspected: bool = False
    regression_suspected: bool = False
    diagnostics: tuple[dict[str, Any], ...] = ()

    @property
    def current_step_number(self) -> int | None:
        if self.current_step_index is None:
            return None
        return self.current_step_index + 1
