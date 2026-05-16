from __future__ import annotations

from typing import Any

from agent.phase3.domain.agent_models import DecisionState, GeoPoint
from agent.phase3.domain.geo_utils import haversine_km


def is_at_point(state: DecisionState, point: GeoPoint | None) -> bool:
    if point is None:
        return False
    return haversine_km(
        state.current_latitude,
        state.current_longitude,
        point.latitude,
        point.longitude,
    ) <= max(0.1, point.radius_km)


def history_completed_cargo(state: DecisionState, cargo_id: str | None) -> bool:
    if not cargo_id:
        return False
    for record in state.history_records:
        action = _action(record)
        if action.get("action") != "take_order":
            continue
        result = record.get("result") if isinstance(record.get("result"), dict) else {}
        if not result.get("accepted"):
            continue
        params = action.get("params") if isinstance(action.get("params"), dict) else {}
        if str(params.get("cargo_id") or "") == str(cargo_id):
            return True
    return False


def trailing_wait_minutes_at_point(state: DecisionState, point: GeoPoint | None) -> int:
    if point is None or not is_at_point(state, point):
        return 0
    total = 0
    for record in reversed(state.history_records):
        action = _action(record)
        if action.get("action") != "wait":
            break
        pos = _position_after(record)
        if pos is not None:
            lat, lng = pos
            if haversine_km(lat, lng, point.latitude, point.longitude) > max(0.1, point.radius_km):
                break
        total += _record_action_minutes(record)
    return total


def first_visit_minute_at_point(state: DecisionState, point: GeoPoint | None, after_minute: int = 0) -> int | None:
    if point is None:
        return None
    for minute, lat, lng in state.visited_positions:
        if int(minute) < int(after_minute):
            continue
        if haversine_km(lat, lng, point.latitude, point.longitude) <= max(0.1, point.radius_km):
            return int(minute)
    return None


def accumulated_wait_at_point_after(
    state: DecisionState,
    point: GeoPoint | None,
    after_minute: int = 0,
    required_minutes: int = 0,
) -> tuple[int, int | None]:
    if point is None:
        return 0, None
    total = 0
    for record in state.history_records:
        action = _action(record)
        if action.get("action") != "wait":
            continue
        _start_minute, action_start, action_end, end_minute = _record_timing(record)
        if action_end <= after_minute:
            continue
        pos = _position_after(record)
        if pos is None:
            continue
        if haversine_km(pos[0], pos[1], point.latitude, point.longitude) > max(0.1, point.radius_km):
            continue
        add = max(0, action_end - max(action_start, after_minute))
        total += add
        if required_minutes > 0 and total >= required_minutes:
            overshoot = total - required_minutes
            return total, max(after_minute, end_minute - overshoot)
    return total, None


def repeated_recent_step_actions(
    state: DecisionState,
    *,
    action_name: str,
    point: GeoPoint | None = None,
    cargo_id: str | None = None,
    lookback: int = 6,
) -> int:
    count = 0
    for record in reversed(state.history_records[-lookback:]):
        action = _action(record)
        if action.get("action") != action_name:
            continue
        params = action.get("params") if isinstance(action.get("params"), dict) else {}
        if cargo_id is not None and str(params.get("cargo_id") or "") != str(cargo_id):
            continue
        if point is not None:
            lat = _safe_float(params.get("latitude"))
            lng = _safe_float(params.get("longitude"))
            if haversine_km(lat, lng, point.latitude, point.longitude) > max(0.1, point.radius_km):
                continue
        count += 1
    return count


def _action(record: dict[str, Any]) -> dict[str, Any]:
    action = record.get("action") if isinstance(record.get("action"), dict) else {}
    return action


def _position_after(record: dict[str, Any]) -> tuple[float, float] | None:
    pos = record.get("position_after") if isinstance(record.get("position_after"), dict) else {}
    if "lat" not in pos or "lng" not in pos:
        return None
    return _safe_float(pos.get("lat")), _safe_float(pos.get("lng"))


def _record_action_minutes(record: dict[str, Any]) -> int:
    elapsed = int(record.get("step_elapsed_minutes") or 0)
    scan = int(record.get("query_scan_cost_minutes") or 0)
    action_cost = int(record.get("action_exec_cost_minutes") or max(0, elapsed - scan))
    return max(0, action_cost)


def _record_timing(record: dict[str, Any]) -> tuple[int, int, int, int]:
    result = record.get("result") if isinstance(record.get("result"), dict) else {}
    end_minute = int(result.get("simulation_progress_minutes") or 0)
    elapsed = int(record.get("step_elapsed_minutes") or 0)
    scan = int(record.get("query_scan_cost_minutes") or 0)
    action_cost = int(record.get("action_exec_cost_minutes") or max(0, elapsed - scan))
    start_minute = max(0, end_minute - elapsed)
    action_start = start_minute + scan
    action_end = action_start + action_cost
    if action_end <= action_start:
        action_end = end_minute
    return start_minute, action_start, action_end, end_minute


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
