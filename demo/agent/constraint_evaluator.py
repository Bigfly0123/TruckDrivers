from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from agent.agent_models import Candidate, DecisionState
from agent.geo_utils import haversine_km
from agent.preference_constraints import ConstraintSpec


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
        self._logger = logging.getLogger("agent.constraint_evaluator")

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
        if constraint.actions and candidate.action not in constraint.actions:
            return None

        handler = self._HANDLERS.get(constraint.constraint_type)
        if handler is None:
            return None
        if constraint.constraint_type == "continuous_rest":
            return handler(self, candidate, constraint, state, runtime)
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
            penalty = max(constraint.penalty_amount, 500.0)
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
        if candidate.action != "take_order":
            return None
        tw = constraint.time_window
        if tw is None:
            return None

        pickup_minutes = int(candidate.facts.get("pickup_minutes", 0) or 0)
        duration = int(candidate.facts.get("estimated_duration_minutes", 0) or 0)
        action_start = state.current_minute
        action_end = state.current_minute + pickup_minutes + duration

        start_day = action_start % 1440
        end_day = (action_end - action_start) + start_day

        if _overlaps_time_window(start_day, min(end_day, start_day + duration + pickup_minutes), tw):
            penalty = max(constraint.penalty_amount, 200.0)
            return ConstraintImpact(
                constraint_id=constraint.constraint_id,
                constraint_type=constraint.constraint_type,
                status="violation" if constraint.priority == "hard" else "risk",
                penalty=penalty,
                detail=f"action_day_range=[{start_day},{end_day}] overlaps [{tw.start_minute_of_day},{tw.end_minute_of_day}]",
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

        if max_streak >= required:
            return None

        finish_minute = self._candidate_finish_minute(candidate, state)
        day_end_minute = (state.current_day + 1) * 1440
        remaining_day_minutes = max(0, day_end_minute - finish_minute)
        if remaining_day_minutes >= required:
            return None

        penalty = max(constraint.penalty_amount, 100.0)
        return ConstraintImpact(
            constraint_id=constraint.constraint_id,
            constraint_type=constraint.constraint_type,
            status="risk",
            penalty=round(penalty, 2),
            detail=(
                f"may_fail_continuous_rest_today: action={candidate.action}, "
                f"finish_minute={finish_minute}, day_end_minute={day_end_minute}, "
                f"remaining_day_minutes={remaining_day_minutes}, required={required}, "
                f"max_streak={max_streak}"
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
        if candidate.action != "take_order":
            return None
        area = constraint.area_bounds
        if area is None:
            return None

        start = candidate.facts.get("start")
        end = candidate.facts.get("end")
        violations: list[str] = []
        if isinstance(start, (tuple, list)) and len(start) == 2:
            if not (area.lat_min <= start[0] <= area.lat_max and area.lng_min <= start[1] <= area.lng_max):
                violations.append("pickup")
        if isinstance(end, (tuple, list)) and len(end) == 2:
            if not (area.lat_min <= end[0] <= area.lat_max and area.lng_min <= end[1] <= area.lng_max):
                violations.append("destination")

        if violations:
            penalty = max(constraint.penalty_amount, 500.0) * len(violations)
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
        if candidate.action != "take_order":
            return None

        start = candidate.facts.get("start")
        end = candidate.facts.get("end")
        if constraint.point is not None:
            pt = constraint.point
            for loc in [start, end]:
                if isinstance(loc, (tuple, list)) and len(loc) == 2:
                    if haversine_km(loc[0], loc[1], pt.latitude, pt.longitude) <= pt.radius_km:
                        penalty = max(constraint.penalty_amount, 500.0)
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
                        penalty = max(constraint.penalty_amount, 500.0)
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
        if candidate.action != "take_order":
            return None
        limit = constraint.distance_limit_km
        if limit is None:
            return None
        pickup_km = float(candidate.facts.get("pickup_deadhead_km", 0) or 0)
        haul_km = float(candidate.facts.get("haul_distance_km", 0) or 0)
        total = pickup_km + haul_km
        if total > limit:
            over = total - limit
            penalty = over * max(constraint.penalty_amount, 100.0)
            return ConstraintImpact(
                constraint_id=constraint.constraint_id,
                constraint_type=constraint.constraint_type,
                status="violation" if constraint.priority == "hard" else "risk",
                penalty=round(penalty, 2),
                detail=f"total_km={round(total,1)} > limit={limit}",
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
