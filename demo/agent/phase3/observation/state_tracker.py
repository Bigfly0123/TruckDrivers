from __future__ import annotations

from typing import Any

from agent.phase3.domain.agent_models import DecisionState


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
            start_minute, action_start, action_end, end_minute = _record_timing(record)
            action_name = _action_name(record)
            result = record.get("result") if isinstance(record.get("result"), dict) else {}
            if action_name == "wait":
                wait_intervals.append((start_minute, end_minute))
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
