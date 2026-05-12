from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from agent.agent_models import GeoPoint


@dataclass(frozen=True)
class MissionStep:
    step_id: str
    action_type: str  # go_to_point / wait_until / wait_duration / take_specific_cargo / stay_within_radius / avoid_actions
    point: GeoPoint | None = None
    earliest_minute: int | None = None
    deadline_minute: int | None = None
    duration_minutes: int | None = None
    cargo_id: str | None = None
    forbidden_actions: tuple[str, ...] = ()
    completion_policy: str = "auto"  # auto / manual
    lock_mode: str = "none"  # hard_stay / periodic_home / deadline_target / none


@dataclass(frozen=True)
class MissionPlan:
    mission_id: str
    source_preference: str
    priority: int = 0
    status: str = "active"  # pending / active / locked / completed / expired / failed / suppressed
    steps: tuple[MissionStep, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    mission_group_key: str = ""
    source_preference_hash: str = ""

    def __post_init__(self) -> None:
        if not self.mission_group_key:
            object.__setattr__(self, "mission_group_key", _infer_group_key(self.mission_id, self.steps))
        if not self.source_preference_hash:
            object.__setattr__(self, "source_preference_hash", hashlib.md5(self.source_preference.encode()).hexdigest()[:12])


def mission_is_complex(mission: MissionPlan) -> bool:
    if len(mission.steps) >= 2:
        return True
    return any(
        s.action_type in ("take_specific_cargo",)
        or (s.lock_mode in ("hard_stay", "deadline_target") and s.deadline_minute is not None)
        for s in mission.steps
    )


def mission_in_countdown(mission: MissionPlan, current_minute: int, buffer_minutes: int = 720) -> bool:
    if not mission_is_complex(mission) and mission.priority < 50:
        return False
    for step in mission.steps:
        if step.deadline_minute is not None:
            remaining = step.deadline_minute - current_minute
            if 0 < remaining <= buffer_minutes:
                return True
    return False


def _infer_group_key(mission_id: str, steps: tuple[MissionStep, ...]) -> str:
    if not steps:
        return mission_id or "empty"
    parts: list[str] = []
    for step in steps:
        point_key = "point" if step.point is not None else "nopoint"
        deadline_key = "deadline" if step.deadline_minute is not None else "nodeadline"
        cargo_key = "cargo" if step.cargo_id else "nocargo"
        parts.append(f"{step.action_type}:{step.lock_mode}:{point_key}:{deadline_key}:{cargo_key}")
    digest = hashlib.md5("|".join(parts).encode()).hexdigest()[:8]
    return f"steps:{digest}"


@dataclass(frozen=True)
class MissionProgress:
    mission_id: str
    completed_step_ids: frozenset[str] = frozenset()
    active_step_id: str | None = None
    arrived_points: tuple[tuple[int, float, float], ...] = ()
    violated_steps: frozenset[str] = frozenset()
    stuck_wait_count: int = 0
    total_steps: int = 0

    @property
    def is_completed(self) -> bool:
        return self.active_step_id is None and len(self.completed_step_ids) > 0

    @property
    def progress_fraction(self) -> float:
        if self.total_steps <= 0:
            return 0.0
        return len(self.completed_step_ids) / self.total_steps
