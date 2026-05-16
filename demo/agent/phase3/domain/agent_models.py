from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TimeWindow:
    start_minute_of_day: int
    end_minute_of_day: int

    @property
    def crosses_midnight(self) -> bool:
        return self.end_minute_of_day <= self.start_minute_of_day


@dataclass(frozen=True)
class GeoPoint:
    latitude: float
    longitude: float
    radius_km: float = 1.0


@dataclass(frozen=True)
class AreaBounds:
    lat_min: float
    lat_max: float
    lng_min: float
    lng_max: float


@dataclass(frozen=True)
class PreferenceRule:
    kind: str
    priority: str = "soft"
    penalty_amount: float = 0.0
    penalty_cap: float | None = None
    time_window: TimeWindow | None = None
    cargo_names: tuple[str, ...] = ()
    point: GeoPoint | None = None
    area_bounds: AreaBounds | None = None
    distance_limit_km: float | None = None
    required_minutes: int | None = None
    required_days: int | None = None
    deadline_minute: int | None = None
    active_start_minute: int | None = None
    active_end_minute: int | None = None
    raw_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionState:
    driver_id: str
    current_minute: int
    current_latitude: float
    current_longitude: float
    simulation_duration_days: int
    completed_order_count: int
    history_records: tuple[dict[str, Any], ...]
    wait_intervals: tuple[tuple[int, int], ...]
    active_intervals: tuple[tuple[int, int], ...]
    accepted_order_days: frozenset[int]
    visited_positions: tuple[tuple[int, float, float], ...]
    monthly_deadhead_km: float
    consecutive_empty_queries: int

    @property
    def current_day(self) -> int:
        return max(0, self.current_minute // 1440)

    @property
    def minute_of_day(self) -> int:
        return self.current_minute % 1440

    @property
    def remaining_minutes(self) -> int:
        return max(0, self.simulation_duration_days * 1440 - self.current_minute)


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    action: str
    params: dict[str, Any]
    source: str = ""
    facts: dict[str, Any] = field(default_factory=dict)
    hard_invalid_reasons: tuple[str, ...] = ()
    soft_risk_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskStep:
    action: str
    point: GeoPoint | None = None
    earliest_minute: int | None = None
    deadline_minute: int | None = None
    stay_minutes: int = 0
    label: str = ""
