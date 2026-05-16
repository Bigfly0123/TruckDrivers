from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.phase3.domain.agent_models import AreaBounds, GeoPoint, PreferenceRule, TimeWindow


@dataclass(frozen=True)
class ConstraintSpec:
    constraint_id: str
    constraint_type: str
    priority: str
    penalty_amount: float = 0.0
    penalty_cap: float | None = None
    actions: tuple[str, ...] = ()
    cargo_names: tuple[str, ...] = ()
    cargo_ids: tuple[str, ...] = ()
    time_window: TimeWindow | None = None
    point: GeoPoint | None = None
    area_bounds: AreaBounds | None = None
    distance_limit_km: float | None = None
    distance_scope: str = ""
    required_minutes: int | None = None
    deadline_minute: int | None = None
    raw_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def compile_constraints(rules: tuple[PreferenceRule, ...]) -> tuple[ConstraintSpec, ...]:
    constraints: list[ConstraintSpec] = []
    for idx, rule in enumerate(rules):
        converted = _convert_rule(rule, idx)
        if converted is not None:
            constraints.append(converted)
    return tuple(constraints)


_KIND_MAP: dict[str, str] = {
    "daily_rest": "continuous_rest",
    "weekday_rest": "continuous_rest",
    "quiet_hours": "forbid_action_in_time_window",
    "home_nightly": "be_at_location_by_deadline",
    "forbidden_cargo": "forbid_cargo_category",
    "off_days": "off_days",
    "visit_point": "be_at_location_by_deadline",
    "multi_step_task": "ordered_steps",
    "special_cargo": "specific_cargo",
    "area_bounds": "operate_within_area",
    "forbidden_zone": "avoid_zone",
    "max_pickup_deadhead": "max_distance",
    "max_haul_distance": "max_distance",
    "max_monthly_deadhead": "max_distance",
    "first_order_deadline": "be_at_location_by_deadline",
    "max_daily_orders": "max_daily_orders",
}


def _convert_rule(rule: PreferenceRule, idx: int) -> ConstraintSpec | None:
    constraint_type = _KIND_MAP.get(rule.kind)
    if constraint_type is None:
        if rule.kind == "unknown":
            return None
        constraint_type = "unknown"

    actions: tuple[str, ...] = ()
    cargo_names = rule.cargo_names
    cargo_ids: tuple[str, ...] = ()
    time_window = rule.time_window
    point = rule.point
    area_bounds = rule.area_bounds
    distance_limit_km = rule.distance_limit_km
    required_minutes = rule.required_minutes
    deadline_minute = rule.deadline_minute

    if constraint_type == "forbid_action_in_time_window":
        scope = _time_window_scope(rule.raw_text)
        actions = ("take_order", "reposition") if scope in {"accept_and_deadhead", "full_operation"} else ("take_order",)
        if time_window is None:
            if rule.active_start_minute is not None and rule.active_end_minute is not None:
                time_window = TimeWindow(
                    start_minute_of_day=rule.active_start_minute % 1440,
                    end_minute_of_day=rule.active_end_minute % 1440,
                )
            else:
                return None

    elif constraint_type == "continuous_rest":
        if required_minutes is None:
            required_minutes = 480
        actions = ("take_order",)

    elif constraint_type == "forbid_cargo_category":
        if not cargo_names:
            return None

    elif constraint_type == "operate_within_area":
        if area_bounds is None:
            return None

    elif constraint_type == "avoid_zone":
        if point is None and area_bounds is None:
            return None

    elif constraint_type == "max_distance":
        if distance_limit_km is None:
            return None
        metadata = dict(rule.metadata)
        metadata["original_kind"] = rule.kind
        if rule.active_start_minute is not None:
            metadata["active_start_minute"] = rule.active_start_minute
        if rule.active_end_minute is not None:
            metadata["active_end_minute"] = rule.active_end_minute
        distance_scope = _distance_scope(rule.kind)
        return ConstraintSpec(
            constraint_id=f"constraint_{idx}_{rule.kind}",
            constraint_type=constraint_type,
            priority=rule.priority,
            penalty_amount=rule.penalty_amount,
            penalty_cap=rule.penalty_cap,
            actions=actions,
            cargo_names=cargo_names,
            cargo_ids=cargo_ids,
            time_window=time_window,
            point=point,
            area_bounds=area_bounds,
            distance_limit_km=distance_limit_km,
            distance_scope=distance_scope,
            required_minutes=required_minutes,
            deadline_minute=deadline_minute,
            raw_text=rule.raw_text,
            metadata=metadata,
        )

    elif constraint_type == "be_at_location_by_deadline":
        if deadline_minute is None and point is None:
            return None

    elif constraint_type == "specific_cargo":
        target_id = rule.metadata.get("target_cargo_id")
        if target_id:
            cargo_ids = (str(target_id),)
        else:
            return None

    elif constraint_type == "off_days":
        if rule.required_days is None:
            return None

    elif constraint_type == "ordered_steps":
        if not rule.metadata.get("steps"):
            return None

    metadata: dict[str, Any] = dict(rule.metadata)
    metadata["original_kind"] = rule.kind
    if rule.active_start_minute is not None:
        metadata["active_start_minute"] = rule.active_start_minute
    if rule.active_end_minute is not None:
        metadata["active_end_minute"] = rule.active_end_minute
    if constraint_type == "forbid_action_in_time_window":
        metadata["time_window_scope"] = _time_window_scope(rule.raw_text)

    return ConstraintSpec(
        constraint_id=f"constraint_{idx}_{rule.kind}",
        constraint_type=constraint_type,
        priority=rule.priority,
        penalty_amount=rule.penalty_amount,
        penalty_cap=rule.penalty_cap,
        actions=actions,
        cargo_names=cargo_names,
        cargo_ids=cargo_ids,
        time_window=time_window,
        point=point,
        area_bounds=area_bounds,
        distance_limit_km=distance_limit_km,
        distance_scope="",
        required_minutes=required_minutes,
        deadline_minute=deadline_minute,
        raw_text=rule.raw_text,
        metadata=metadata,
    )


def _distance_scope(kind: str) -> str:
    if kind == "max_pickup_deadhead":
        return "pickup_deadhead"
    if kind == "max_haul_distance":
        return "haul_distance"
    if kind == "max_monthly_deadhead":
        return "monthly_deadhead"
    return "total_trip_distance"


def _time_window_scope(raw_text: str) -> str:
    text = str(raw_text or "")
    if any(token in text for token in ("跑车", "运营", "运输", "行驶", "开车", "空车", "空跑", "空驶", "赶路", "去接单", "发车")):
        return "full_operation"
    return "accept_only"
