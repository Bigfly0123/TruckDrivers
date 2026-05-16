from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from agent.phase3.domain.agent_models import Candidate, DecisionState
from agent.phase3.domain.geo_utils import haversine_km
from agent.phase3.preferences.preference_constraints import ConstraintSpec


@dataclass(frozen=True)
class ConstraintImpact:
    constraint_id: str
    constraint_type: str
    status: str
    penalty: float
    detail: str = ""


@dataclass(frozen=True)
class EvaluationResult:
    hard_invalid_reasons: tuple[str, ...] = ()
    soft_risk_reasons: tuple[str, ...] = ()
    constraint_impacts: tuple[ConstraintImpact, ...] = ()
    estimated_penalty_exposure: float = 0.0
    satisfies_all_constraints: bool = True


class ConstraintEvaluator:
    def __init__(self) -> None:
        self._logger = logging.getLogger("agent.phase3.constraints.constraint_evaluator")

    def evaluate(
        self,
        candidate: Candidate,
        constraints: tuple[ConstraintSpec, ...],
        state: DecisionState,
        runtime: Any | None = None,
    ) -> EvaluationResult:
        hard: list[str] = []
        soft: list[str] = []
        impacts: list[ConstraintImpact] = []
        total_penalty = 0.0
        satisfies_all = True

        for c in constraints:
            impact = self._evaluate_one(candidate, c, state, runtime)
            if impact is not None:
                impacts.append(impact)
                if impact.status == "violation":
                    if c.priority == "hard":
                        hard.append(f"constraint_{c.constraint_type}")
                    else:
                        soft.append(f"constraint_{c.constraint_type}_risk")
                    total_penalty += impact.penalty
                    satisfies_all = False
                elif impact.status == "risk":
                    soft.append(f"constraint_{c.constraint_type}_risk")
                    total_penalty += impact.penalty
                    satisfies_all = False

        return EvaluationResult(
            hard_invalid_reasons=tuple(hard),
            soft_risk_reasons=tuple(soft),
            constraint_impacts=tuple(impacts),
            estimated_penalty_exposure=round(total_penalty, 2),
            satisfies_all_constraints=satisfies_all,
        )

    def _evaluate_one(
        self,
        candidate: Candidate,
        constraint: ConstraintSpec,
        state: DecisionState,
        runtime: Any | None = None,
    ) -> ConstraintImpact | None:
        handler = self._HANDLERS.get(constraint.constraint_type)
        if handler is None:
            return None
        if constraint.constraint_type == "continuous_rest":
            return handler(self, candidate, constraint, state, runtime)
        if constraint.actions and candidate.action not in constraint.actions:
            return None
        return handler(self, candidate, constraint, state)

    def _eval_forbid_cargo(
        self,
        candidate: Candidate,
        constraint: ConstraintSpec,
        state: DecisionState,
    ) -> ConstraintImpact | None:
        if candidate.action != "take_order":
            return None
        cargo_name = str(candidate.facts.get("cargo_name") or "")
        cargo_id = str(candidate.params.get("cargo_id") or "")
        if cargo_name in constraint.cargo_names or cargo_id in constraint.cargo_ids:
            penalty = _constraint_penalty(constraint, hard_default=500.0)
            return ConstraintImpact(
                constraint_id=constraint.constraint_id,
                constraint_type=constraint.constraint_type,
                status="violation",
                penalty=penalty,
                detail=f"cargo_name={cargo_name} matches forbidden",
            )
        return None

    def _eval_forbid_time_window(
        self,
        candidate: Candidate,
        constraint: ConstraintSpec,
        state: DecisionState,
    ) -> ConstraintImpact | None:
        if candidate.action not in {"take_order", "reposition"}:
            return None
        tw = constraint.time_window
        if tw is None:
            return None

        scope = str(constraint.metadata.get("time_window_scope") or "accept_only")
        pickup_minutes = int(candidate.facts.get("pickup_minutes", 0) or 0)
        duration = int(candidate.facts.get("estimated_duration_minutes", 0) or 0)
        action_start = state.current_minute
        if scope == "accept_only":
            action_end = action_start + 1
        elif scope == "accept_and_deadhead":
            if candidate.action == "take_order":
                action_end = action_start + max(1, pickup_minutes)
            else:
                action_end = self._candidate_finish_minute(candidate, state)
        else:
            action_end = action_start + pickup_minutes + duration if candidate.action == "take_order" else self._candidate_finish_minute(candidate, state)

        if _interval_overlaps_daily_window(action_start, action_end, tw):
            penalty = _constraint_penalty(constraint, hard_default=200.0)
            if _already_violated_time_window_today(state, constraint, action_start):
                return ConstraintImpact(
                    constraint_id=constraint.constraint_id,
                    constraint_type=constraint.constraint_type,
                    status="satisfies",
                    penalty=0.0,
                    detail=(
                        f"already_violated_today: scope={scope}, action_range=[{action_start},{action_end}] "
                        f"overlaps [{tw.start_minute_of_day},{tw.end_minute_of_day}]"
                    ),
                )
            return ConstraintImpact(
                constraint_id=constraint.constraint_id,
                constraint_type=constraint.constraint_type,
                status="violation" if constraint.priority == "hard" else "risk",
                penalty=penalty,
                detail=(
                    f"scope={scope}, action_range=[{action_start},{action_end}] "
                    f"overlaps [{tw.start_minute_of_day},{tw.end_minute_of_day}]"
                ),
            )
        return None

    def _eval_continuous_rest(
        self,
        candidate: Candidate,
        constraint: ConstraintSpec,
        state: DecisionState,
        runtime: Any | None = None,
    ) -> ConstraintImpact | None:
        required = constraint.required_minutes or 480
        current_streak = 0
        max_streak = 0

        if runtime is not None and hasattr(runtime, "rest"):
            rest_state = runtime.rest
            current_streak = rest_state.current_rest_streak_minutes
            max_streak = rest_state.max_rest_streak_today

        if candidate.action == "wait":
            wait_minutes = int(candidate.params.get("duration_minutes", 0) or 0)
            new_streak = current_streak + wait_minutes
            new_best_streak = max(max_streak, new_streak)
            new_remaining = max(0, required - new_best_streak)
            return ConstraintImpact(
                constraint_id=constraint.constraint_id,
                constraint_type=constraint.constraint_type,
                status="satisfies" if new_remaining == 0 else "progress",
                penalty=0.0,
                detail=f"rest_streak {current_streak} -> {new_streak}, max_streak={new_best_streak}, remaining={new_remaining}",
            )

        if candidate.action not in {"take_order", "reposition"}:
            return None

        achieved_streak = max(current_streak, max_streak)
        if achieved_streak >= required:
            return None

        finish_minute = self._candidate_finish_minute(candidate, state)
        day_end_minute = (state.current_day + 1) * 1440
        before_can_still_complete = _can_still_complete_rest(
            achieved_streak=achieved_streak,
            required=required,
            from_minute=state.current_minute,
            day_end_minute=day_end_minute,
        )
        after_can_still_complete = _can_still_complete_rest(
            achieved_streak=achieved_streak,
            required=required,
            from_minute=finish_minute,
            day_end_minute=day_end_minute,
        )
        if after_can_still_complete:
            return None

        if not before_can_still_complete:
            return ConstraintImpact(
                constraint_id=constraint.constraint_id,
                constraint_type=constraint.constraint_type,
                status="satisfies",
                penalty=0.0,
                detail=(
                    "continuous_rest_already_unrecoverable_today: "
                    f"action={candidate.action}, finish_minute={finish_minute}, "
                    f"day_end_minute={day_end_minute}, required={required}, "
                    f"achieved_streak={achieved_streak}"
                ),
            )

        penalty = _constraint_penalty(constraint, hard_default=100.0)
        return ConstraintImpact(
            constraint_id=constraint.constraint_id,
            constraint_type=constraint.constraint_type,
            status="risk",
            penalty=round(penalty, 2),
            detail=(
                f"action_creates_continuous_rest_risk: action={candidate.action}, "
                f"finish_minute={finish_minute}, day_end_minute={day_end_minute}, "
                f"required={required}, "
                f"achieved_streak={achieved_streak}"
            ),
        )

    def _candidate_finish_minute(self, candidate: Candidate, state: DecisionState) -> int:
        try:
            return int(candidate.facts.get("finish_minute"))
        except (TypeError, ValueError):
            pass

        if candidate.action == "take_order":
            pickup = int(candidate.facts.get("pickup_minutes", 0) or 0)
            duration = int(candidate.facts.get("estimated_duration_minutes", 0) or 0)
            return state.current_minute + pickup + duration

        if candidate.action == "reposition":
            duration = int(candidate.facts.get("estimated_duration_minutes", 0) or 0)
            return state.current_minute + duration

        return state.current_minute

    def _eval_operate_within_area(
        self,
        candidate: Candidate,
        constraint: ConstraintSpec,
        state: DecisionState,
    ) -> ConstraintImpact | None:
        if candidate.action not in {"take_order", "reposition"}:
            return None
        area = constraint.area_bounds
        if area is None:
            return None

        start, end = _candidate_route_points(candidate, state)
        violations: list[str] = []
        if isinstance(start, (tuple, list)) and len(start) == 2:
            if not (area.lat_min <= start[0] <= area.lat_max and area.lng_min <= start[1] <= area.lng_max):
                violations.append("pickup")
        if isinstance(end, (tuple, list)) and len(end) == 2:
            if not (area.lat_min <= end[0] <= area.lat_max and area.lng_min <= end[1] <= area.lng_max):
                violations.append("destination")

        if violations:
            penalty = _constraint_penalty(constraint, hard_default=500.0)
            if _current_outside_area(state, area) and constraint.penalty_cap is not None and float(constraint.penalty_cap) <= penalty:
                return ConstraintImpact(
                    constraint_id=constraint.constraint_id,
                    constraint_type=constraint.constraint_type,
                    status="satisfies",
                    penalty=0.0,
                    detail=f"outside_area_already_at_capped_risk: {','.join(violations)}",
                )
            return ConstraintImpact(
                constraint_id=constraint.constraint_id,
                constraint_type=constraint.constraint_type,
                status="violation" if constraint.priority == "hard" else "risk",
                penalty=penalty,
                detail=f"outside_area: {','.join(violations)}",
            )
        return None

    def _eval_avoid_zone(
        self,
        candidate: Candidate,
        constraint: ConstraintSpec,
        state: DecisionState,
    ) -> ConstraintImpact | None:
        if candidate.action not in {"take_order", "reposition"}:
            return None

        start, end = _candidate_route_points(candidate, state)
        if constraint.point is not None:
            pt = constraint.point
            for loc in [start, end]:
                if isinstance(loc, (tuple, list)) and len(loc) == 2:
                    if haversine_km(loc[0], loc[1], pt.latitude, pt.longitude) <= pt.radius_km:
                        penalty = _constraint_penalty(constraint, hard_default=500.0)
                        if _current_in_point_zone(state, pt) and constraint.penalty_cap is not None and float(constraint.penalty_cap) <= penalty:
                            return ConstraintImpact(
                                constraint_id=constraint.constraint_id,
                                constraint_type=constraint.constraint_type,
                                status="satisfies",
                                penalty=0.0,
                                detail=f"already_in_capped_avoid_zone: {pt.latitude},{pt.longitude}",
                            )
                        return ConstraintImpact(
                            constraint_id=constraint.constraint_id,
                            constraint_type=constraint.constraint_type,
                            status="violation" if constraint.priority == "hard" else "risk",
                            penalty=penalty,
                            detail=f"location in avoid zone: {pt.latitude},{pt.longitude}",
                        )

        if constraint.area_bounds is not None:
            area = constraint.area_bounds
            for loc in [start, end]:
                if isinstance(loc, (tuple, list)) and len(loc) == 2:
                    if area.lat_min <= loc[0] <= area.lat_max and area.lng_min <= loc[1] <= area.lng_max:
                        penalty = _constraint_penalty(constraint, hard_default=500.0)
                        if not _current_outside_area(state, area) and constraint.penalty_cap is not None and float(constraint.penalty_cap) <= penalty:
                            return ConstraintImpact(
                                constraint_id=constraint.constraint_id,
                                constraint_type=constraint.constraint_type,
                                status="satisfies",
                                penalty=0.0,
                                detail="already_in_capped_avoid_zone_area",
                            )
                        return ConstraintImpact(
                            constraint_id=constraint.constraint_id,
                            constraint_type=constraint.constraint_type,
                            status="violation" if constraint.priority == "hard" else "risk",
                            penalty=penalty,
                            detail="location in avoid zone area",
                        )
        return None

    def _eval_max_distance(
        self,
        candidate: Candidate,
        constraint: ConstraintSpec,
        state: DecisionState,
    ) -> ConstraintImpact | None:
        if candidate.action not in {"take_order", "reposition"}:
            return None
        limit = constraint.distance_limit_km
        if limit is None:
            return None
        scope = constraint.distance_scope or constraint.metadata.get("distance_scope") or "total_trip_distance"
        pickup_km = float(candidate.facts.get("pickup_deadhead_km", 0) or 0)
        haul_km = float(candidate.facts.get("haul_distance_km", 0) or 0)
        reposition_km = float(candidate.facts.get("reposition_distance_km", candidate.facts.get("estimated_distance_km", 0)) or 0)
        if candidate.action == "reposition":
            pickup_km = reposition_km
            haul_km = 0.0
        if scope == "pickup_deadhead":
            measured = pickup_km
            before_over = 0.0
        elif scope == "haul_distance":
            measured = haul_km
            before_over = 0.0
        elif scope == "monthly_deadhead":
            before = float(state.monthly_deadhead_km or 0.0)
            measured = before + pickup_km
            before_over = max(0.0, before - limit)
        else:
            measured = pickup_km + haul_km
            before_over = 0.0
        if measured > limit:
            over = measured - limit
            rate = _constraint_penalty(constraint, hard_default=100.0)
            penalty = _marginal_capped_penalty(constraint, before_over, over, rate)
            if penalty <= 0:
                return ConstraintImpact(
                    constraint_id=constraint.constraint_id,
                    constraint_type=constraint.constraint_type,
                    status="satisfies",
                    penalty=0.0,
                    detail=f"{scope}_already_over_cap: measured={round(measured,1)} > limit={limit}",
                )
            return ConstraintImpact(
                constraint_id=constraint.constraint_id,
                constraint_type=constraint.constraint_type,
                status="violation" if constraint.priority == "hard" else "risk",
                penalty=round(penalty, 2),
                detail=f"{scope}={round(measured,1)} > limit={limit}",
            )
        return None

    def _eval_specific_cargo(
        self,
        candidate: Candidate,
        constraint: ConstraintSpec,
        state: DecisionState,
    ) -> ConstraintImpact | None:
        if candidate.action == "take_order":
            cargo_id = str(candidate.params.get("cargo_id") or "")
            if cargo_id in constraint.cargo_ids:
                return ConstraintImpact(
                    constraint_id=constraint.constraint_id,
                    constraint_type=constraint.constraint_type,
                    status="satisfies",
                    penalty=0.0,
                    detail=f"matches specific cargo {cargo_id}",
                )
        return None

    def _eval_generic(
        self,
        candidate: Candidate,
        constraint: ConstraintSpec,
        state: DecisionState,
    ) -> ConstraintImpact | None:
        return None

    _HANDLERS: dict[str, Any] = {
        "forbid_cargo_category": _eval_forbid_cargo,
        "forbid_action_in_time_window": _eval_forbid_time_window,
        "continuous_rest": _eval_continuous_rest,
        "operate_within_area": _eval_operate_within_area,
        "avoid_zone": _eval_avoid_zone,
        "max_distance": _eval_max_distance,
        "specific_cargo": _eval_specific_cargo,
    }


def _overlaps_time_window(start: int, end: int, tw: Any) -> bool:
    s = int(tw.start_minute_of_day)
    e = int(tw.end_minute_of_day)
    if s < e:
        return start < e and s < end
    else:
        return start < e or s < end


def _interval_overlaps_daily_window(start_minute: int, end_minute: int, tw: Any) -> bool:
    start = int(start_minute)
    end = max(start + 1, int(end_minute))
    first_day = start // 1440
    last_day = (end - 1) // 1440
    for day in range(first_day, last_day + 1):
        day_start = day * 1440
        day_end = day_start + 1440
        local_start = max(start, day_start) - day_start
        local_end = min(end, day_end) - day_start
        if _overlaps_time_window(local_start, local_end, tw):
            return True
    return False


def _already_violated_time_window_today(state: DecisionState, constraint: ConstraintSpec, current_minute: int) -> bool:
    tw = constraint.time_window
    if tw is None:
        return False
    day_start = (int(current_minute) // 1440) * 1440
    day_end = day_start + 1440
    scope = str(constraint.metadata.get("time_window_scope") or "accept_only")
    actions = set(constraint.actions or ("take_order",))
    for record in state.history_records:
        action = record.get("action") if isinstance(record.get("action"), dict) else {}
        action_name = str(action.get("action") or "").strip().lower()
        if action_name not in {"take_order", "reposition"}:
            continue
        if actions and action_name not in actions:
            continue
        _start_minute, action_start, action_end, _end_minute = _record_timing(record)
        if action_end <= day_start or action_start >= day_end:
            continue
        if scope == "accept_only":
            interval_start = action_start
            interval_end = action_start + 1
        elif scope == "accept_and_deadhead" and action_name == "take_order":
            interval_start = action_start
            interval_end = max(action_start + 1, action_end)
        else:
            interval_start = action_start
            interval_end = max(action_start + 1, action_end)
        if _interval_overlaps_daily_window(interval_start, interval_end, tw):
            return True
    return False


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


def _can_still_complete_rest(
    *,
    achieved_streak: int,
    required: int,
    from_minute: int,
    day_end_minute: int,
) -> bool:
    remaining_required = max(0, int(required) - int(achieved_streak))
    remaining_day = max(0, int(day_end_minute) - int(from_minute))
    return remaining_day >= remaining_required


def _candidate_route_points(candidate: Candidate, state: DecisionState) -> tuple[Any, Any]:
    if candidate.action == "reposition":
        start = (state.current_latitude, state.current_longitude)
        lat = candidate.params.get("latitude")
        lng = candidate.params.get("longitude")
        if lat is None or lng is None:
            destination = candidate.facts.get("destination")
            if isinstance(destination, (tuple, list)) and len(destination) >= 2:
                return start, (destination[0], destination[1])
            return start, None
        return start, (float(lat), float(lng))
    return candidate.facts.get("start"), candidate.facts.get("end")


def _current_outside_area(state: DecisionState, area: Any) -> bool:
    return not (
        area.lat_min <= state.current_latitude <= area.lat_max
        and area.lng_min <= state.current_longitude <= area.lng_max
    )


def _current_in_point_zone(state: DecisionState, point: Any) -> bool:
    return haversine_km(
        state.current_latitude,
        state.current_longitude,
        point.latitude,
        point.longitude,
    ) <= point.radius_km


def _constraint_penalty(constraint: ConstraintSpec, *, hard_default: float) -> float:
    amount = float(constraint.penalty_amount or 0.0)
    if amount <= 0:
        amount = hard_default if constraint.priority == "hard" else 0.0

    if constraint.penalty_cap is not None:
        amount = min(amount, float(constraint.penalty_cap))

    return round(max(0.0, amount), 2)


def _cap_penalty(constraint: ConstraintSpec, amount: float) -> float:
    if constraint.penalty_cap is not None:
        amount = min(amount, float(constraint.penalty_cap))
    return round(max(0.0, amount), 2)


def _marginal_capped_penalty(
    constraint: ConstraintSpec,
    before_over: float,
    after_over: float,
    rate: float,
) -> float:
    before = max(0.0, float(before_over)) * float(rate)
    after = max(0.0, float(after_over)) * float(rate)
    if constraint.penalty_cap is not None:
        cap = float(constraint.penalty_cap)
        before = min(before, cap)
        after = min(after, cap)
    return round(max(0.0, after - before), 2)
