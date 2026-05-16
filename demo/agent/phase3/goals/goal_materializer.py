from __future__ import annotations

from typing import Any

from agent.phase3.domain.agent_models import Candidate, DecisionState
from agent.phase3.goals.action_templates import (
    clone_goal_order_candidate,
    reposition_candidate,
    wait_candidate,
)
from agent.phase3.goals.completion_checkers import is_at_point
from agent.phase3.goals.goal_schema import Goal, GoalProgress, GoalStep
from agent.phase3.domain.geo_utils import distance_to_minutes, haversine_km

DEFAULT_COST_PER_KM = 1.5
REPOSITION_SPEED_KM_PER_HOUR = 60.0


class GoalMaterializer:
    def materialize(
        self,
        *,
        goals: list[Goal],
        progress_by_goal: dict[str, GoalProgress],
        state: DecisionState,
        runtime: Any | None,
        base_candidates: list[Candidate],
    ) -> tuple[list[Candidate], list[dict[str, Any]]]:
        candidates: list[Candidate] = []
        diagnostics: list[dict[str, Any]] = []
        cargo_candidates = _cargo_candidates_by_id(base_candidates)
        best_visible_order_net = _best_visible_order_net(base_candidates)
        existing_ids: set[str] = set()

        for goal in goals:
            progress = progress_by_goal.get(goal.goal_id)
            if progress is None or progress.is_complete:
                continue
            if progress.current_step_index is None or progress.current_step_index >= len(goal.steps):
                continue
            step = goal.steps[progress.current_step_index]
            built, emitted = self._materialize_step(
                goal=goal,
                step=step,
                step_index=progress.current_step_index,
                progress=progress,
                state=state,
                runtime=runtime,
                cargo_candidates=cargo_candidates,
                best_visible_order_net=best_visible_order_net,
            )
            diagnostics.extend(emitted)
            for candidate in built:
                candidate_id = candidate.candidate_id
                if candidate_id in existing_ids:
                    continue
                existing_ids.add(candidate_id)
                candidates.append(candidate)
        return candidates, diagnostics

    def _materialize_step(
        self,
        *,
        goal: Goal,
        step: GoalStep,
        step_index: int,
        progress: GoalProgress,
        state: DecisionState,
        runtime: Any | None,
        cargo_candidates: dict[str, Candidate],
        best_visible_order_net: float,
    ) -> tuple[list[Candidate], list[dict[str, Any]]]:
        facts = self._goal_facts(
            goal,
            step,
            step_index,
            progress,
            state=state,
            runtime=runtime,
            best_visible_order_net=best_visible_order_net,
        )
        diagnostics: list[dict[str, Any]] = []

        if step.step_type == "take_specific_cargo":
            if not step.cargo_id:
                return [], [self._diagnostic(goal, step_index, "error", "missing_target_cargo_id")]
            base = cargo_candidates.get(str(step.cargo_id))
            if base is None:
                return [], [self._diagnostic(goal, step_index, "warning", "target_cargo_not_visible", cargo_id=step.cargo_id)]
            candidate = clone_goal_order_candidate(
                candidate_id=f"goal_{goal.goal_id}_step_{step_index}_take_order",
                base=base,
                facts={**facts, "materialization_reason": "target_cargo_visible_full_candidate"},
            )
            return [candidate], [self._diagnostic(goal, step_index, "info", "materialized", candidate_id=candidate.candidate_id)]

        if step.step_type in {"reach_location", "return_to_location"}:
            if step.point is None:
                return [], [self._diagnostic(goal, step_index, "error", "missing_target_point")]
            if is_at_point(state, step.point):
                return [], [self._diagnostic(goal, step_index, "info", "step_already_satisfied")]
            candidate = reposition_candidate(
                candidate_id=f"goal_{goal.goal_id}_step_{step_index}_reposition",
                point=step.point,
                facts={
                    **facts,
                    **_reposition_facts(state, step.point),
                    "deadline_minute": step.deadline_minute,
                    "penalty_if_missed": _penalty(goal),
                    "materialization_reason": "move_to_next_goal_location",
                },
            )
            return [candidate], [self._diagnostic(goal, step_index, "info", "materialized", candidate_id=candidate.candidate_id)]

        if step.step_type == "stay_at_location":
            if step.point is not None and not is_at_point(state, step.point):
                candidate = reposition_candidate(
                    candidate_id=f"goal_{goal.goal_id}_step_{step_index}_reach_before_stay",
                    point=step.point,
                    facts={
                        **facts,
                        **_reposition_facts(state, step.point),
                        "penalty_if_missed": _penalty(goal),
                        "materialization_reason": "cannot_stay_not_at_target_reach_first",
                    },
                )
                return [candidate], [self._diagnostic(goal, step_index, "info", "materialized", candidate_id=candidate.candidate_id)]
            remaining = max(1, step.required_minutes - progress.current_step_progress_minutes)
            candidate = wait_candidate(
                candidate_id=f"goal_{goal.goal_id}_step_{step_index}_stay_{min(60, remaining)}",
                duration_minutes=min(60, remaining),
                facts={
                    **facts,
                    "required_minutes": step.required_minutes,
                    "current_progress_minutes": progress.current_step_progress_minutes,
                    "remaining_minutes_after_wait": max(0, remaining - min(60, remaining)),
                    "actually_satisfies_after_this_wait": remaining <= 60,
                    "penalty_if_missed": _penalty(goal),
                    "materialization_reason": "continue_stay_step",
                },
            )
            return [candidate], [self._diagnostic(goal, step_index, "info", "materialized", candidate_id=candidate.candidate_id)]

        if step.step_type in {"wait_duration", "stay_until_time", "hold_location_until_time"}:
            if step.step_type == "stay_until_time" and step.point is not None and not is_at_point(state, step.point):
                candidate = reposition_candidate(
                    candidate_id=f"goal_{goal.goal_id}_step_{step_index}_reach_before_wait_until",
                    point=step.point,
                    facts={
                        **facts,
                        **_reposition_facts(state, step.point),
                        "deadline_minute": step.deadline_minute,
                        "penalty_if_missed": _penalty(goal),
                        "materialization_reason": "cannot_wait_until_not_at_target_reach_first",
                    },
                )
                return [candidate], [self._diagnostic(goal, step_index, "info", "materialized", candidate_id=candidate.candidate_id)]
            if step.step_type == "hold_location_until_time" and not _hold_is_actionable(step, state):
                return [], [self._diagnostic(
                    goal,
                    step_index,
                    "info",
                    "hold_not_urgent",
                    earliest_minute=step.earliest_minute,
                    deadline_minute=step.deadline_minute,
                )]
            if step.step_type == "hold_location_until_time" and step.point is not None and not is_at_point(state, step.point):
                candidate = reposition_candidate(
                    candidate_id=f"goal_{goal.goal_id}_step_{step_index}_reach_before_hold",
                    point=step.point,
                    facts={
                        **facts,
                        **_reposition_facts(state, step.point),
                        "deadline_minute": step.deadline_minute,
                        "penalty_if_missed": _penalty(goal),
                        "materialization_reason": "cannot_hold_not_at_target_reach_first",
                    },
                )
                return [candidate], [self._diagnostic(goal, step_index, "info", "materialized", candidate_id=candidate.candidate_id)]
            remaining = 60
            if step.step_type in {"stay_until_time", "hold_location_until_time"} and step.deadline_minute is not None:
                remaining = max(1, int(step.deadline_minute) - state.current_minute)
            elif step.required_minutes:
                remaining = max(1, step.required_minutes - progress.current_step_progress_minutes)
            reason = "hold_location_until_deadline" if step.step_type == "hold_location_until_time" else "continue_wait_step"
            candidate = wait_candidate(
                candidate_id=f"goal_{goal.goal_id}_step_{step_index}_wait_{min(60, remaining)}",
                duration_minutes=min(60, remaining),
                facts={
                    **facts,
                    "required_minutes": step.required_minutes,
                    "deadline_minute": step.deadline_minute,
                    "window_hold_preservation": step.step_type == "hold_location_until_time",
                    "hold_window_active": step.step_type == "hold_location_until_time" and _hold_is_active(step, state),
                    "hold_window_remaining_minutes": remaining if step.step_type == "hold_location_until_time" else None,
                    "remaining_minutes_after_wait": max(0, remaining - min(60, remaining)),
                    "actually_satisfies_after_this_wait": remaining <= 60,
                    "penalty_if_missed": _penalty(goal),
                    "materialization_reason": reason,
                },
            )
            return [candidate], [self._diagnostic(goal, step_index, "info", "materialized", candidate_id=candidate.candidate_id)]

        if step.step_type == "complete_rest":
            rest = getattr(runtime, "rest", None) if runtime is not None else None
            current_streak = int(getattr(rest, "current_rest_streak_minutes", 0) or 0)
            max_streak = int(getattr(rest, "max_rest_streak_today", 0) or 0)
            required = max(1, int(step.required_minutes or 480))
            remaining_now = max(0, required - max(current_streak, max_streak))
            latest_safe_start = _latest_safe_rest_start(state, required, current_streak)
            must_do_now = state.current_minute >= latest_safe_start
            penalty = _penalty(goal)
            should_continue = current_streak > 0 and (remaining_now <= 60 or best_visible_order_net <= penalty)
            if not must_do_now and not should_continue:
                return [], [self._diagnostic(
                    goal,
                    step_index,
                    "info",
                    "rest_not_urgent",
                    latest_safe_start_time=latest_safe_start,
                    best_visible_order_net=best_visible_order_net,
                    remaining_required_rest=remaining_now,
                )]
            duration = min(60, max(1, required - current_streak))
            streak_after = current_streak + duration
            max_after = max(max_streak, streak_after)
            remaining_after = max(0, required - max_after)
            completes = max_after >= required
            prefix = "continue_rest" if current_streak > 0 else "start_rest"
            candidate = wait_candidate(
                candidate_id=f"goal_{goal.goal_id}_{prefix}_{duration}",
                duration_minutes=duration,
                facts={
                    **facts,
                    "satisfies_constraint_type": "continuous_rest",
                    "satisfy_status": "complete" if completes else "progress",
                    "current_rest_streak_minutes": current_streak,
                    "max_rest_streak_today": max_streak,
                    "required_minutes": required,
                    "adds_rest_minutes": duration,
                    "rest_streak_after_wait": streak_after,
                    "remaining_rest_minutes_after_wait": remaining_after,
                    "actually_satisfies_after_this_wait": completes,
                    "avoids_estimated_penalty": penalty if completes else 0.0,
                    "penalty_if_rest_not_completed": penalty,
                    "latest_safe_start_time": latest_safe_start,
                    "must_do_now": must_do_now,
                    "urgency": _rest_urgency(state, latest_safe_start, remaining_now, completes),
                    "penalty_at_risk": penalty,
                    "opportunity_cost_hint": best_visible_order_net,
                    "materialization_reason": "continue_continuous_rest_streak",
                },
            )
            return [candidate], [self._diagnostic(goal, step_index, "info", "materialized", candidate_id=candidate.candidate_id)]

        if step.step_type == "wait_until_window_end":
            tw_state = getattr(runtime, "time_windows", None) if runtime is not None else None
            end_minute = getattr(tw_state, "next_window_end_minute", None) if tw_state is not None else None
            active = getattr(tw_state, "active_forbidden_windows", ()) if tw_state is not None else ()
            if not active or end_minute is None:
                return [], [self._diagnostic(goal, step_index, "info", "no_active_forbidden_window")]
            duration = max(1, min(60, int(end_minute) - state.current_minute))
            candidate = wait_candidate(
                candidate_id=f"goal_{goal.goal_id}_wait_until_window_end",
                duration_minutes=duration,
                facts={
                    **facts,
                    "satisfies_constraint_type": "forbid_action_in_time_window",
                    "window_end_minute": end_minute,
                    "avoids_estimated_penalty": _penalty(goal),
                    "materialization_reason": "active_forbidden_window_wait_until_end",
                },
            )
            return [candidate], [self._diagnostic(goal, step_index, "info", "materialized", candidate_id=candidate.candidate_id)]

        return [], [self._diagnostic(goal, step_index, "warning", "unsupported_step_type", step_type=step.step_type)]

    def _goal_facts(
        self,
        goal: Goal,
        step: GoalStep,
        step_index: int,
        progress: GoalProgress,
        *,
        state: DecisionState,
        runtime: Any | None,
        best_visible_order_net: float,
    ) -> dict[str, Any]:
        urgency, must_do_now, latest_safe_start = _goal_urgency(goal, step, state, runtime)
        return {
            "goal_id": goal.goal_id,
            "goal_type": goal.goal_type,
            "constraint_id": goal.constraint_id,
            "satisfies_constraint_type": goal.goal_type,
            "step_index": step_index,
            "step_type": step.step_type,
            "advances_goal": True,
            "completion_condition": _completion_condition(step),
            "completed_step_count": progress.completed_step_count,
            "total_step_count": len(goal.steps),
            "stuck_suspected": progress.stuck_suspected,
            "regression_suspected": progress.regression_suspected,
            "repeated_step_action_count": progress.repeated_step_action_count,
            "penalty_if_missed": _penalty(goal),
            "priority": goal.priority,
            "urgency": urgency,
            "must_do_now": must_do_now,
            "latest_safe_start_time": latest_safe_start,
            "penalty_at_risk": _penalty(goal),
            "opportunity_cost_hint": best_visible_order_net,
        }

    def _diagnostic(self, goal: Goal, step_index: int, level: str, reason: str, **extra: Any) -> dict[str, Any]:
        return {
            "goal_id": goal.goal_id,
            "goal_type": goal.goal_type,
            "constraint_id": goal.constraint_id,
            "step_index": step_index,
            "level": level,
            "reason": reason,
            **extra,
        }


def _cargo_candidates_by_id(candidates: list[Candidate]) -> dict[str, Candidate]:
    result: dict[str, Candidate] = {}
    for candidate in candidates:
        if candidate.action != "take_order":
            continue
        cargo_id = str(candidate.params.get("cargo_id") or candidate.facts.get("cargo_id") or "").strip()
        if cargo_id and cargo_id not in result:
            result[cargo_id] = candidate
    return result


def _best_visible_order_net(candidates: list[Candidate]) -> float:
    values: list[float] = []
    for candidate in candidates:
        if candidate.action != "take_order":
            continue
        try:
            values.append(float(candidate.facts.get("estimated_net", 0) or 0))
        except (TypeError, ValueError):
            continue
    return max(values) if values else 0.0


def _completion_condition(step: GoalStep) -> str:
    if step.step_type == "take_specific_cargo":
        return "accepted_target_cargo"
    if step.step_type in {"reach_location", "return_to_location"}:
        return "current_location_within_radius"
    if step.step_type in {"stay_at_location", "wait_duration"}:
        return "continuous_wait_or_stay_minutes_reached"
    if step.step_type == "stay_until_time":
        return "time_reached_while_at_required_location"
    if step.step_type == "hold_location_until_time":
        return "remain_at_required_location_until_time"
    if step.step_type == "complete_rest":
        return "max_continuous_rest_streak_reaches_required_minutes"
    if step.step_type == "wait_until_window_end":
        return "forbidden_time_window_ended"
    return "unknown"


def _reposition_facts(state: DecisionState, point: Any) -> dict[str, Any]:
    distance = haversine_km(state.current_latitude, state.current_longitude, point.latitude, point.longitude)
    duration = distance_to_minutes(distance, REPOSITION_SPEED_KM_PER_HOUR)
    cost = round(distance * DEFAULT_COST_PER_KM, 2)
    return {
        "estimated_distance_km": round(distance, 2),
        "reposition_distance_km": round(distance, 2),
        "estimated_duration_minutes": duration,
        "estimated_cost": cost,
        "estimated_net": -cost,
        "destination": (point.latitude, point.longitude),
    }


def _penalty(goal: Goal) -> float:
    return max(float(goal.penalty_amount or 0.0), 100.0)


def _goal_urgency(goal: Goal, step: GoalStep, state: DecisionState, runtime: Any | None) -> tuple[str, bool, int | None]:
    penalty = _penalty(goal)
    if step.step_type == "complete_rest":
        required = max(1, int(step.required_minutes or 480))
        rest = getattr(runtime, "rest", None) if runtime is not None else None
        current_streak = int(getattr(rest, "current_rest_streak_minutes", 0) or 0)
        latest = _latest_safe_rest_start(state, required, current_streak)
        return _rest_urgency(state, latest, max(0, required - current_streak), False), state.current_minute >= latest, latest
    if step.step_type == "wait_until_window_end":
        return "low", False, state.current_minute
    if step.deadline_minute is not None:
        remaining = int(step.deadline_minute) - state.current_minute
        if step.step_type == "hold_location_until_time" and _hold_is_active(step, state):
            return "critical", True, int(step.deadline_minute)
        latest_safe_start = _latest_safe_goal_start(step, state)
        if latest_safe_start is not None and state.current_minute >= latest_safe_start:
            return "critical", True, latest_safe_start
        if latest_safe_start is not None and latest_safe_start - state.current_minute <= 120:
            return "high", False, latest_safe_start
        if remaining <= 0:
            return "critical", True, int(step.deadline_minute)
        if remaining <= 60:
            return "critical", True, int(step.deadline_minute)
        if remaining <= 180:
            return "high", False, int(step.deadline_minute)
        if penalty >= 1000 and remaining <= 360:
            return "medium", False, int(step.deadline_minute)
        return "medium", False, int(step.deadline_minute)
    if goal.goal_type in {"specific_cargo", "ordered_steps"} and penalty >= 1000:
        return "high", False, None
    return "medium", False, None


def _latest_safe_goal_start(step: GoalStep, state: DecisionState) -> int | None:
    if step.deadline_minute is None or step.point is None:
        return None
    if step.step_type not in {"reach_location", "return_to_location", "stay_at_location", "stay_until_time", "hold_location_until_time"}:
        return None
    distance = haversine_km(state.current_latitude, state.current_longitude, step.point.latitude, step.point.longitude)
    travel_minutes = distance_to_minutes(distance, REPOSITION_SPEED_KM_PER_HOUR)
    buffer_minutes = 15 if step.step_type in {"reach_location", "return_to_location"} else 30
    return int(step.deadline_minute) - travel_minutes - buffer_minutes


def _latest_safe_rest_start(state: DecisionState, required: int, current_streak: int) -> int:
    day_end = (state.current_day + 1) * 1440
    remaining = max(0, int(required) - int(current_streak))
    return day_end - remaining


def _hold_is_actionable(step: GoalStep, state: DecisionState) -> bool:
    if step.deadline_minute is None:
        return False
    remaining = int(step.deadline_minute) - state.current_minute
    if remaining <= 0:
        return True
    if _hold_is_active(step, state):
        return True
    return remaining <= 180


def _hold_is_active(step: GoalStep, state: DecisionState) -> bool:
    if step.earliest_minute is None or step.deadline_minute is None:
        return False
    return int(step.earliest_minute) <= state.current_minute < int(step.deadline_minute)


def _rest_urgency(state: DecisionState, latest_safe_start: int, remaining_now: int, completes: bool) -> str:
    if state.current_minute >= latest_safe_start:
        return "critical" if remaining_now > 60 and not completes else "high"
    if latest_safe_start - state.current_minute <= 120:
        return "medium"
    return "low"
