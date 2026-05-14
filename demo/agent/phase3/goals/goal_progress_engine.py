from __future__ import annotations

from typing import Any

from agent.agent_models import DecisionState
from agent.phase3.goals.completion_checkers import (
    history_completed_cargo,
    is_at_point,
    repeated_recent_step_actions,
    trailing_wait_minutes_at_point,
)
from agent.phase3.goals.goal_schema import Goal, GoalProgress, GoalStep


class GoalProgressEngine:
    def evaluate(
        self,
        goals: list[Goal],
        state: DecisionState,
        runtime: Any | None,
    ) -> dict[str, GoalProgress]:
        return {goal.goal_id: self._evaluate_goal(goal, state, runtime) for goal in goals}

    def _evaluate_goal(self, goal: Goal, state: DecisionState, runtime: Any | None) -> GoalProgress:
        completed = 0
        diagnostics: list[dict[str, Any]] = []
        progress_minutes = 0

        for index, step in enumerate(goal.steps):
            completed_step, progress_minutes = self._step_completed(step, state, runtime)
            if completed_step:
                completed += 1
                diagnostics.append({
                    "goal_id": goal.goal_id,
                    "step_index": index,
                    "status": "completed",
                    "step_type": step.step_type,
                })
                continue
            repeated = self._repeated_count(step, state)
            stuck = repeated >= 3
            if stuck:
                diagnostics.append({
                    "goal_id": goal.goal_id,
                    "step_index": index,
                    "status": "stuck_suspected",
                    "step_type": step.step_type,
                    "repeated_step_action_count": repeated,
                })
            return GoalProgress(
                goal_id=goal.goal_id,
                completed_step_count=completed,
                current_step_index=index,
                is_complete=False,
                current_step_progress_minutes=progress_minutes,
                repeated_step_action_count=repeated,
                stuck_suspected=stuck,
                diagnostics=tuple(diagnostics),
            )

        return GoalProgress(
            goal_id=goal.goal_id,
            completed_step_count=completed,
            current_step_index=None,
            is_complete=True,
            diagnostics=tuple(diagnostics),
        )

    def _step_completed(
        self,
        step: GoalStep,
        state: DecisionState,
        runtime: Any | None,
    ) -> tuple[bool, int]:
        if step.step_type in {"reach_location", "return_to_location"}:
            return is_at_point(state, step.point), 0
        if step.step_type == "stay_at_location":
            if not is_at_point(state, step.point):
                return False, 0
            stayed = trailing_wait_minutes_at_point(state, step.point)
            return stayed >= max(1, step.required_minutes), stayed
        if step.step_type == "wait_duration":
            stayed = _trailing_wait_minutes(state)
            return stayed >= max(1, step.required_minutes), stayed
        if step.step_type == "stay_until_time":
            if step.point is not None and not is_at_point(state, step.point):
                return False, 0
            if step.deadline_minute is None:
                return False, 0
            return state.current_minute >= int(step.deadline_minute), 0
        if step.step_type == "take_specific_cargo":
            return history_completed_cargo(state, step.cargo_id), 0
        if step.step_type == "complete_rest":
            max_streak = 0
            if runtime is not None and getattr(runtime, "rest", None) is not None:
                max_streak = int(getattr(runtime.rest, "max_rest_streak_today", 0) or 0)
            return max_streak >= max(1, step.required_minutes), max_streak
        if step.step_type == "wait_until_window_end":
            next_end = None
            if runtime is not None and getattr(runtime, "time_windows", None) is not None:
                next_end = getattr(runtime.time_windows, "next_window_end_minute", None)
            return next_end is None, 0
        return False, 0

    def _repeated_count(self, step: GoalStep, state: DecisionState) -> int:
        if step.step_type in {"reach_location", "return_to_location"}:
            return repeated_recent_step_actions(state, action_name="reposition", point=step.point)
        if step.step_type == "take_specific_cargo":
            return repeated_recent_step_actions(state, action_name="take_order", cargo_id=step.cargo_id)
        if step.step_type in {"stay_at_location", "wait_duration", "stay_until_time", "complete_rest", "wait_until_window_end"}:
            return repeated_recent_step_actions(state, action_name="wait")
        return 0


def _trailing_wait_minutes(state: DecisionState) -> int:
    total = 0
    for record in reversed(state.history_records):
        action = record.get("action") if isinstance(record.get("action"), dict) else {}
        if action.get("action") != "wait":
            break
        elapsed = int(record.get("step_elapsed_minutes") or 0)
        scan = int(record.get("query_scan_cost_minutes") or 0)
        total += max(0, int(record.get("action_exec_cost_minutes") or max(0, elapsed - scan)))
    return total
