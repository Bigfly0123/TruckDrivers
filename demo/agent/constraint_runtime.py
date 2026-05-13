from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RestRuntimeState:
    current_rest_streak_minutes: int = 0
    max_rest_streak_today: int = 0
    remaining_rest_minutes_by_constraint: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class TimeWindowRuntimeState:
    active_forbidden_windows: tuple[dict[str, Any], ...] = ()
    upcoming_forbidden_windows: tuple[dict[str, Any], ...] = ()
    next_window_end_minute: int | None = None


@dataclass(frozen=True)
class SpecificCargoRuntimeState:
    target_cargo_ids: tuple[str, ...] = ()
    visible_target_cargo_ids: tuple[str, ...] = ()
    missing_target_cargo_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class OrderedStepRuntimeState:
    current_step_index_by_constraint: dict[str, int] = field(default_factory=dict)
    step_status_by_constraint: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class ConstraintRuntimeState:
    rest: RestRuntimeState = field(default_factory=RestRuntimeState)
    time_windows: TimeWindowRuntimeState = field(default_factory=TimeWindowRuntimeState)
    specific_cargo: SpecificCargoRuntimeState = field(default_factory=SpecificCargoRuntimeState)
    ordered_steps: OrderedStepRuntimeState = field(default_factory=OrderedStepRuntimeState)
    debug: dict[str, Any] = field(default_factory=dict)


def compute_rest_runtime_state(
    history_records: tuple[dict[str, Any], ...],
    current_minute: int,
    constraints: tuple[Any, ...],
) -> RestRuntimeState:
    current_day = current_minute // 1440
    day_start = current_day * 1440

    current_streak = 0
    max_streak = 0
    last_wait_end = None

    for record in history_records:
        result = record.get("result") if isinstance(record.get("result"), dict) else {}
        end_minute = int(result.get("simulation_progress_minutes") or 0)
        elapsed = int(record.get("step_elapsed_minutes") or 0)
        action_cost = int(record.get("action_exec_cost_minutes") or max(0, elapsed - int(record.get("query_scan_cost_minutes") or 0)))
        start_minute = max(0, end_minute - elapsed)
        action_start = start_minute + int(record.get("query_scan_cost_minutes") or 0)
        action_end = action_start + action_cost

        action = record.get("action") if isinstance(record.get("action"), dict) else {}
        action_name = str(action.get("action") or "").strip().lower()

        if action_name == "wait" and end_minute >= day_start:
            wait_start = max(start_minute, day_start)
            wait_end = end_minute
            if last_wait_end is not None and wait_start <= last_wait_end + 1:
                current_streak += wait_end - wait_start
            else:
                current_streak = wait_end - wait_start
            max_streak = max(max_streak, current_streak)
            last_wait_end = wait_end
        elif action_name in {"take_order", "reposition"} and end_minute >= day_start:
            current_streak = 0
            last_wait_end = None

    remaining: dict[str, int] = {}
    for c in constraints:
        if hasattr(c, "constraint_type") and c.constraint_type == "continuous_rest":
            req = c.required_minutes or 480
            cid = c.constraint_id
            remaining[cid] = max(0, req - max_streak)

    return RestRuntimeState(
        current_rest_streak_minutes=current_streak,
        max_rest_streak_today=max_streak,
        remaining_rest_minutes_by_constraint=remaining,
    )


def compute_time_window_runtime_state(
    current_minute: int,
    constraints: tuple[Any, ...],
) -> TimeWindowRuntimeState:
    active: list[dict[str, Any]] = []
    upcoming: list[dict[str, Any]] = []
    next_end: int | None = None

    mod = current_minute % 1440

    for c in constraints:
        if not hasattr(c, "constraint_type") or c.constraint_type != "forbid_action_in_time_window":
            continue
        tw = c.time_window
        if tw is None:
            continue
        s = tw.start_minute_of_day
        e = tw.end_minute_of_day
        is_active = False
        if s < e:
            is_active = s <= mod < e
        else:
            is_active = mod >= s or mod < e

        window_info = {
            "constraint_id": c.constraint_id,
            "start_minute_of_day": s,
            "end_minute_of_day": e,
            "actions": list(c.actions) if c.actions else ["take_order"],
        }

        if is_active:
            active.append(window_info)
            if s < e:
                end_abs = current_minute - mod + e
            else:
                if mod >= s:
                    end_abs = current_minute - mod + e + 1440
                else:
                    end_abs = current_minute - mod + e
            if next_end is None or end_abs < next_end:
                next_end = end_abs
        else:
            if s < e:
                if mod < s:
                    start_abs = current_minute - mod + s
                else:
                    start_abs = current_minute - mod + s + 1440
            else:
                if s <= mod < 1440:
                    start_abs = current_minute - mod + s + 1440
                else:
                    start_abs = current_minute - mod + s
            upcoming.append({**window_info, "starts_in_minutes": start_abs - current_minute})

    return TimeWindowRuntimeState(
        active_forbidden_windows=tuple(active),
        upcoming_forbidden_windows=tuple(upcoming),
        next_window_end_minute=next_end,
    )


def compute_specific_cargo_runtime_state(
    constraints: tuple[Any, ...],
    visible_cargo_ids: set[str],
) -> SpecificCargoRuntimeState:
    targets: list[str] = []
    visible: list[str] = []
    missing: list[str] = []

    for c in constraints:
        if hasattr(c, "constraint_type") and c.constraint_type == "specific_cargo":
            for cid in (c.cargo_ids or ()):
                targets.append(cid)
                if cid in visible_cargo_ids:
                    visible.append(cid)
                else:
                    missing.append(cid)

    return SpecificCargoRuntimeState(
        target_cargo_ids=tuple(targets),
        visible_target_cargo_ids=tuple(visible),
        missing_target_cargo_ids=tuple(missing),
    )


def compute_constraint_runtime_state(
    history_records: tuple[dict[str, Any], ...],
    current_minute: int,
    constraints: tuple[Any, ...],
    visible_cargo_ids: set[str],
) -> ConstraintRuntimeState:
    return ConstraintRuntimeState(
        rest=compute_rest_runtime_state(history_records, current_minute, constraints),
        time_windows=compute_time_window_runtime_state(current_minute, constraints),
        specific_cargo=compute_specific_cargo_runtime_state(constraints, visible_cargo_ids),
    )
