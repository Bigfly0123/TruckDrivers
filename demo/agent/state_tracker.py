from __future__ import annotations

from typing import Any

from agent.agent_models import DecisionState, GeoPoint
from agent.geo_utils import haversine_km, interval_overlap, longest_span
from agent.mission_models import MissionPlan, MissionProgress, MissionStep


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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


def _action_name(record: dict[str, Any]) -> str:
    action = record.get("action") if isinstance(record.get("action"), dict) else {}
    return str(action.get("action") or "").strip().lower()


def _accepted(record: dict[str, Any]) -> bool:
    result = record.get("result") if isinstance(record.get("result"), dict) else {}
    if _action_name(record) != "take_order":
        return False
    return bool(result.get("accepted", False))


def _position_after(record: dict[str, Any]) -> tuple[float, float] | None:
    pos = record.get("position_after") if isinstance(record.get("position_after"), dict) else {}
    if "lat" not in pos or "lng" not in pos:
        return None
    return _safe_float(pos.get("lat")), _safe_float(pos.get("lng"))


def _current_day_bounds(day: int) -> tuple[int, int]:
    return day * 1440, (day + 1) * 1440


def longest_wait_for_day(state: DecisionState, day: int) -> int:
    day_start, day_end = _current_day_bounds(day)
    intervals: list[tuple[int, int]] = []
    for start, end in state.wait_intervals:
        clipped_start = max(start, day_start)
        clipped_end = min(end, day_end)
        if clipped_end > clipped_start:
            intervals.append((clipped_start, clipped_end))
    return longest_span(intervals)


def active_minutes_for_day(state: DecisionState, day: int) -> int:
    day_start, day_end = _current_day_bounds(day)
    total = 0
    for start, end in state.active_intervals:
        if interval_overlap(start, end, day_start, day_end):
            total += min(end, day_end) - max(start, day_start)
    return max(0, total)


def completed_off_days(state: DecisionState) -> int:
    total = 0
    for day in range(min(state.current_day + 1, state.simulation_duration_days)):
        if active_minutes_for_day(state, day) == 0 and day < state.current_day:
            total += 1
    return total


def visited_days_near(state: DecisionState, point: GeoPoint) -> set[int]:
    days: set[int] = set()
    for minute, lat, lng in state.visited_positions:
        if haversine_km(lat, lng, point.latitude, point.longitude) <= point.radius_km:
            days.add(minute // 1440)
    if haversine_km(state.current_latitude, state.current_longitude, point.latitude, point.longitude) <= point.radius_km:
        days.add(state.current_day)
    return days


class StateTracker:
    def build(
        self,
        driver_id: str,
        status: dict[str, Any],
        history_payload: dict[str, Any],
        *,
        scan_cost_minutes: int,
        simulation_duration_days: int = 31,
        empty_query: bool = False,
    ) -> DecisionState:
        records_raw = history_payload.get("records") if isinstance(history_payload, dict) else []
        records = tuple(record for record in records_raw or [] if isinstance(record, dict))
        wait_intervals: list[tuple[int, int]] = []
        active_intervals: list[tuple[int, int]] = []
        visited: list[tuple[int, float, float]] = []
        order_days: set[int] = set()
        monthly_deadhead = 0.0
        empty_query_streak = 0

        for record in records:
            _, action_start, action_end, end_minute = _record_timing(record)
            action_name = _action_name(record)
            result = record.get("result") if isinstance(record.get("result"), dict) else {}
            if action_name == "wait":
                wait_intervals.append((action_start, action_end))
            elif action_name in {"take_order", "reposition"}:
                active_intervals.append((action_start, action_end))
            if action_name == "reposition":
                monthly_deadhead += _safe_float(result.get("distance_km"))
            if action_name == "take_order":
                monthly_deadhead += _safe_float(result.get("pickup_deadhead_km"))
                if _accepted(record):
                    order_days.add(end_minute // 1440)
            pos = _position_after(record)
            if pos is not None:
                visited.append((end_minute, pos[0], pos[1]))

            if action_name == "wait" and int(record.get("query_scan_cost_minutes") or 0) == 0:
                empty_query_streak += 1
            elif action_name != "wait":
                empty_query_streak = 0

        current_minute = int(status.get("simulation_progress_minutes") or 0) + max(0, int(scan_cost_minutes))
        current_lat = _safe_float(status.get("current_lat"))
        current_lng = _safe_float(status.get("current_lng"))
        visited.append((current_minute, current_lat, current_lng))
        if empty_query:
            empty_query_streak += 1

        return DecisionState(
            driver_id=driver_id,
            current_minute=current_minute,
            current_latitude=current_lat,
            current_longitude=current_lng,
            simulation_duration_days=simulation_duration_days,
            completed_order_count=int(status.get("completed_order_count") or 0),
            history_records=records,
            wait_intervals=tuple(wait_intervals),
            active_intervals=tuple(active_intervals),
            accepted_order_days=frozenset(order_days),
            visited_positions=tuple(visited),
            monthly_deadhead_km=monthly_deadhead,
            consecutive_empty_queries=empty_query_streak,
        )


def history_action_name(record: dict[str, Any]) -> str:
    action = record.get("action") if isinstance(record.get("action"), dict) else {}
    return str(action.get("action") or action.get("name") or "").strip().lower()


def _action_name_from_record(record: dict[str, Any]) -> str:
    return history_action_name(record)


def _accepted_cargo_id(record: dict[str, Any]) -> str | None:
    if _action_name_from_record(record) != "take_order":
        return None
    result = record.get("result") if isinstance(record.get("result"), dict) else {}
    if not result.get("accepted"):
        return None
    action = record.get("action") if isinstance(record.get("action"), dict) else {}
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    cargo_id = str(params.get("cargo_id") or "").strip()
    return cargo_id or None


def _positions_from_history(state: DecisionState) -> list[tuple[int, float, float]]:
    return list(state.visited_positions)


def _wait_intervals_in_window(state: DecisionState, start: int, end: int) -> list[tuple[int, int]]:
    intervals: list[tuple[int, int]] = []
    for ws, we in state.wait_intervals:
        clipped_start = max(ws, start)
        clipped_end = min(we, end)
        if clipped_end > clipped_start:
            intervals.append((clipped_start, clipped_end))
    return intervals


def _longest_wait_in_window(state: DecisionState, start: int, end: int) -> int:
    intervals = _wait_intervals_in_window(state, start, end)
    if not intervals:
        return 0
    return max(e - s for s, e in intervals)


def _arrived_at_point(state: DecisionState, point: GeoPoint, after_minute: int = 0) -> tuple[int, float, float] | None:
    for minute, lat, lng in state.visited_positions:
        if minute < after_minute:
            continue
        if haversine_km(lat, lng, point.latitude, point.longitude) <= point.radius_km:
            return (minute, lat, lng)
    return None


def _actions_in_window(state: DecisionState, start: int, end: int) -> list[str]:
    actions: list[str] = []
    for record in state.history_records:
        result = record.get("result") if isinstance(record.get("result"), dict) else {}
        end_minute = int(result.get("simulation_progress_minutes") or 0)
        if start <= end_minute < end:
            actions.append(_action_name_from_record(record))
    return actions


def is_step_completed(
    step: MissionStep,
    state: DecisionState,
    mission: MissionPlan,
) -> bool:
    if step.action_type == "go_to_point":
        if step.point is None:
            return False
        after = step.earliest_minute or 0
        arrival = _arrived_at_point(state, step.point, after)
        if arrival is None:
            return False
        if step.duration_minutes and step.duration_minutes > 0:
            return _longest_wait_in_window(state, arrival[0], arrival[0] + step.duration_minutes) >= step.duration_minutes
        return True

    if step.action_type == "wait_until":
        if step.deadline_minute is None:
            return False
        return state.current_minute >= step.deadline_minute

    if step.action_type == "wait_duration":
        if step.point is None or step.duration_minutes is None:
            return False
        arrival = _arrived_at_point(state, step.point, step.earliest_minute or 0)
        if arrival is None:
            return False
        return _longest_wait_in_window(state, arrival[0], state.current_minute) >= step.duration_minutes

    if step.action_type == "take_specific_cargo":
        if step.cargo_id is None:
            return False
        for record in state.history_records:
            if _accepted_cargo_id(record) == step.cargo_id:
                return True
        return False

    if step.action_type == "stay_within_radius":
        if step.point is None:
            return False
        if step.deadline_minute is not None and state.current_minute < step.deadline_minute:
            return False
        start = step.earliest_minute or 0
        end = step.deadline_minute or state.current_minute
        if end <= start:
            return False
        actual_end = min(end, state.current_minute)
        if actual_end <= start:
            return True
        for record in state.history_records:
            result = record.get("result") if isinstance(record.get("result"), dict) else {}
            end_minute = int(result.get("simulation_progress_minutes") or 0)
            if end_minute < start or end_minute >= actual_end:
                continue
            pos = _position_after_record(record)
            if pos is None:
                continue
            if haversine_km(pos[0], pos[1], step.point.latitude, step.point.longitude) > step.point.radius_km:
                return False
            action = _action_name_from_record(record)
            if step.forbidden_actions and action in step.forbidden_actions:
                return False
        return True

    if step.action_type == "avoid_actions":
        start = step.earliest_minute or 0
        end = step.deadline_minute or state.current_minute
        actions = _actions_in_window(state, start, end)
        return not any(a in step.forbidden_actions for a in actions)

    return False


def _position_after_record(record: dict[str, Any]) -> tuple[float, float] | None:
    pos = record.get("position_after") if isinstance(record.get("position_after"), dict) else {}
    if "lat" not in pos or "lng" not in pos:
        return None
    return _safe_float(pos.get("lat")), _safe_float(pos.get("lng"))


def build_mission_progress(
    missions: tuple[MissionPlan, ...],
    state: DecisionState,
) -> tuple[MissionProgress, ...]:
    progresses: list[MissionProgress] = []
    for mission in missions:
        if mission.status != "active":
            continue
        completed_ids: list[str] = []
        active_id: str | None = None
        violated: list[str] = []
        for step in mission.steps:
            if is_step_completed(step, state, mission):
                completed_ids.append(step.step_id)
            else:
                if active_id is None:
                    active_id = step.step_id
                if step.deadline_minute is not None and state.current_minute > step.deadline_minute:
                    violated.append(step.step_id)
                break
        progresses.append(MissionProgress(
            mission_id=mission.mission_id,
            completed_step_ids=frozenset(completed_ids),
            active_step_id=active_id,
            violated_steps=frozenset(violated),
            total_steps=len(mission.steps),
        ))
    return tuple(progresses)
