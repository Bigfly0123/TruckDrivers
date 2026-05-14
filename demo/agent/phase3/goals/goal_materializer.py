from __future__ import annotations

from typing import Any

from agent.agent_models import Candidate, DecisionState
from agent.phase3.goals.action_templates import (
    clone_goal_order_candidate,
    reposition_candidate,
    wait_candidate,
)
from agent.phase3.goals.completion_checkers import is_at_point
from agent.phase3.goals.goal_schema import Goal, GoalProgress, GoalStep


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
    ) -> tuple[list[Candidate], list[dict[str, Any]]]:
        facts = self._goal_facts(goal, step, step_index, progress)
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

        if step.step_type in {"wait_duration", "stay_until_time"}:
            if step.step_type == "stay_until_time" and step.point is not None and not is_at_point(state, step.point):
                candidate = reposition_candidate(
                    candidate_id=f"goal_{goal.goal_id}_step_{step_index}_reach_before_wait_until",
                    point=step.point,
                    facts={
                        **facts,
                        "deadline_minute": step.deadline_minute,
                        "penalty_if_missed": _penalty(goal),
                        "materialization_reason": "cannot_wait_until_not_at_target_reach_first",
                    },
                )
                return [candidate], [self._diagnostic(goal, step_index, "info", "materialized", candidate_id=candidate.candidate_id)]
            remaining = 60
            if step.step_type == "stay_until_time" and step.deadline_minute is not None:
                remaining = max(1, int(step.deadline_minute) - state.current_minute)
            elif step.required_minutes:
                remaining = max(1, step.required_minutes - progress.current_step_progress_minutes)
            candidate = wait_candidate(
                candidate_id=f"goal_{goal.goal_id}_step_{step_index}_wait_{min(60, remaining)}",
                duration_minutes=min(60, remaining),
                facts={
                    **facts,
                    "required_minutes": step.required_minutes,
                    "deadline_minute": step.deadline_minute,
                    "remaining_minutes_after_wait": max(0, remaining - min(60, remaining)),
                    "actually_satisfies_after_this_wait": remaining <= 60,
                    "penalty_if_missed": _penalty(goal),
                    "materialization_reason": "continue_wait_step",
                },
            )
            return [candidate], [self._diagnostic(goal, step_index, "info", "materialized", candidate_id=candidate.candidate_id)]

        if step.step_type == "complete_rest":
            rest = getattr(runtime, "rest", None) if runtime is not None else None
            current_streak = int(getattr(rest, "current_rest_streak_minutes", 0) or 0)
            max_streak = int(getattr(rest, "max_rest_streak_today", 0) or 0)
            required = max(1, int(step.required_minutes or 480))
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
                    "avoids_estimated_penalty": _penalty(goal) if completes else 0.0,
                    "penalty_if_rest_not_completed": _penalty(goal),
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

    def _goal_facts(self, goal: Goal, step: GoalStep, step_index: int, progress: GoalProgress) -> dict[str, Any]:
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
            "repeated_step_action_count": progress.repeated_step_action_count,
            "penalty_if_missed": _penalty(goal),
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


def _completion_condition(step: GoalStep) -> str:
    if step.step_type == "take_specific_cargo":
        return "accepted_target_cargo"
    if step.step_type in {"reach_location", "return_to_location"}:
        return "current_location_within_radius"
    if step.step_type in {"stay_at_location", "wait_duration"}:
        return "continuous_wait_or_stay_minutes_reached"
    if step.step_type == "stay_until_time":
        return "time_reached_while_at_required_location"
    if step.step_type == "complete_rest":
        return "max_continuous_rest_streak_reaches_required_minutes"
    if step.step_type == "wait_until_window_end":
        return "forbidden_time_window_ended"
    return "unknown"


def _penalty(goal: Goal) -> float:
    return max(float(goal.penalty_amount or 0.0), 100.0)
