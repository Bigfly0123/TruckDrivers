from __future__ import annotations

import re
from typing import Any

from agent.phase3.goals.goal_schema import Goal, GoalStep


class GoalBuilder:
    """Builds deterministic goals from compiled constraints only."""

    def build(self, constraints: tuple[Any, ...]) -> list[Goal]:
        goals: list[Goal] = []
        for constraint in constraints:
            constraint_type = str(getattr(constraint, "constraint_type", "") or "")
            if constraint_type == "specific_cargo":
                goals.extend(self._specific_cargo_goals(constraint))
            elif constraint_type == "ordered_steps":
                goal = self._ordered_steps_goal(constraint)
                if goal is not None:
                    goals.append(goal)
            elif constraint_type == "be_at_location_by_deadline":
                goal = self._location_deadline_goal(constraint)
                if goal is not None:
                    goals.append(goal)
            elif constraint_type == "continuous_rest":
                goal = self._rest_goal(constraint)
                if goal is not None:
                    goals.append(goal)
            elif constraint_type == "forbid_action_in_time_window":
                goal = self._time_window_goal(constraint)
                if goal is not None:
                    goals.append(goal)
        return goals

    def _specific_cargo_goals(self, constraint: Any) -> list[Goal]:
        result: list[Goal] = []
        for cargo_id in tuple(getattr(constraint, "cargo_ids", ()) or ()):
            cargo_text = str(cargo_id).strip()
            if not cargo_text:
                continue
            goal_id = _goal_id(constraint, "specific_cargo", cargo_text)
            result.append(Goal(
                goal_id=goal_id,
                goal_type="specific_cargo",
                constraint_id=str(getattr(constraint, "constraint_id", "")),
                priority=str(getattr(constraint, "priority", "medium") or "medium"),
                penalty_amount=float(getattr(constraint, "penalty_amount", 0.0) or 0.0),
                raw_text=str(getattr(constraint, "raw_text", "") or ""),
                steps=(GoalStep(
                    step_id=f"{goal_id}_take",
                    step_type="take_specific_cargo",
                    cargo_id=cargo_text,
                    deadline_minute=getattr(constraint, "deadline_minute", None),
                ),),
            ))
        return result

    def _ordered_steps_goal(self, constraint: Any) -> Goal | None:
        metadata = getattr(constraint, "metadata", {}) or {}
        raw_steps = metadata.get("steps") if isinstance(metadata, dict) else None
        if not isinstance(raw_steps, (tuple, list)) or not raw_steps:
            return None
        goal_id = _goal_id(constraint, "ordered_steps")
        steps: list[GoalStep] = []
        for index, raw_step in enumerate(raw_steps):
            point = getattr(raw_step, "point", None)
            action = str(getattr(raw_step, "action", "") or "").strip().lower()
            stay_minutes = int(getattr(raw_step, "stay_minutes", 0) or 0)
            deadline_minute = getattr(raw_step, "deadline_minute", None)
            step_type = _ordered_step_type(action, point, stay_minutes, deadline_minute)
            step_id = f"{goal_id}_step_{len(steps)}"
            steps.append(GoalStep(
                step_id=step_id,
                step_type=step_type,
                point=point,
                earliest_minute=getattr(raw_step, "earliest_minute", None),
                deadline_minute=deadline_minute,
                required_minutes=stay_minutes,
                label=str(getattr(raw_step, "label", "") or ""),
                metadata={"source_action": action, "source_index": index},
            ))
            if _needs_followup_hold(index, raw_steps, point, stay_minutes, deadline_minute):
                steps.append(GoalStep(
                    step_id=f"{goal_id}_step_{len(steps)}",
                    step_type="hold_location_until_time",
                    point=point,
                    earliest_minute=getattr(raw_step, "earliest_minute", None),
                    deadline_minute=deadline_minute,
                    label=str(getattr(raw_step, "label", "") or ""),
                    metadata={"source_action": action, "source_index": index, "generated_hold": True},
                ))
        return Goal(
            goal_id=goal_id,
            goal_type="ordered_steps",
            constraint_id=str(getattr(constraint, "constraint_id", "")),
            priority=str(getattr(constraint, "priority", "medium") or "medium"),
            penalty_amount=float(getattr(constraint, "penalty_amount", 0.0) or 0.0),
            raw_text=str(getattr(constraint, "raw_text", "") or ""),
            steps=tuple(steps),
        )

    def _location_deadline_goal(self, constraint: Any) -> Goal | None:
        point = getattr(constraint, "point", None)
        if point is None:
            return None
        goal_id = _goal_id(constraint, "location_deadline")
        return Goal(
            goal_id=goal_id,
            goal_type="location_deadline",
            constraint_id=str(getattr(constraint, "constraint_id", "")),
            priority=str(getattr(constraint, "priority", "medium") or "medium"),
            penalty_amount=float(getattr(constraint, "penalty_amount", 0.0) or 0.0),
            raw_text=str(getattr(constraint, "raw_text", "") or ""),
            steps=_location_steps(goal_id, constraint, point),
        )

    def _rest_goal(self, constraint: Any) -> Goal | None:
        required = int(getattr(constraint, "required_minutes", None) or 480)
        goal_id = _goal_id(constraint, "continuous_rest")
        return Goal(
            goal_id=goal_id,
            goal_type="continuous_rest",
            constraint_id=str(getattr(constraint, "constraint_id", "")),
            priority=str(getattr(constraint, "priority", "medium") or "medium"),
            penalty_amount=float(getattr(constraint, "penalty_amount", 0.0) or 0.0),
            raw_text=str(getattr(constraint, "raw_text", "") or ""),
            steps=(GoalStep(
                step_id=f"{goal_id}_rest",
                step_type="complete_rest",
                required_minutes=required,
            ),),
        )

    def _time_window_goal(self, constraint: Any) -> Goal | None:
        goal_id = _goal_id(constraint, "forbid_action_window")
        return Goal(
            goal_id=goal_id,
            goal_type="forbid_action_in_time_window",
            constraint_id=str(getattr(constraint, "constraint_id", "")),
            priority=str(getattr(constraint, "priority", "medium") or "medium"),
            penalty_amount=float(getattr(constraint, "penalty_amount", 0.0) or 0.0),
            raw_text=str(getattr(constraint, "raw_text", "") or ""),
            steps=(GoalStep(
                step_id=f"{goal_id}_wait_window",
                step_type="wait_until_window_end",
                metadata={"actions": list(getattr(constraint, "actions", ()) or ())},
            ),),
        )


def _ordered_step_type(action: str, point: Any, stay_minutes: int, deadline_minute: Any) -> str:
    if action in {"wait_until", "stay_within_radius"} and deadline_minute is not None:
        return "stay_until_time"
    if action in {"wait", "stay", "wait_duration", "stay_within_radius"} or stay_minutes > 0:
        return "stay_at_location" if point is not None else "wait_duration"
    if action in {"take_specific_cargo"}:
        return "take_specific_cargo"
    return "reach_location"


def _needs_followup_hold(index: int, raw_steps: Any, point: Any, stay_minutes: int, deadline_minute: Any) -> bool:
    if point is None or deadline_minute is None:
        return False
    if stay_minutes > 0:
        return False
    return index == len(raw_steps) - 1


def _location_steps(goal_id: str, constraint: Any, point: Any) -> tuple[GoalStep, ...]:
    deadline = getattr(constraint, "deadline_minute", None)
    metadata = getattr(constraint, "metadata", {}) or {}
    original_kind = metadata.get("original_kind") if isinstance(metadata, dict) else None
    if original_kind == "home_nightly" and deadline is not None:
        return (
            GoalStep(
                step_id=f"{goal_id}_reach",
                step_type="reach_location",
                point=point,
                deadline_minute=deadline,
            ),
            GoalStep(
                step_id=f"{goal_id}_hold",
                step_type="hold_location_until_time",
                point=point,
                deadline_minute=deadline,
                metadata={"generated_hold": True, "original_kind": original_kind},
            ),
        )
    return (GoalStep(
        step_id=f"{goal_id}_reach",
        step_type="reach_location",
        point=point,
        deadline_minute=deadline,
    ),)


def _goal_id(constraint: Any, goal_type: str, suffix: str | None = None) -> str:
    raw = str(getattr(constraint, "constraint_id", "") or goal_type)
    text = f"{goal_type}_{raw}"
    if suffix:
        text = f"{text}_{suffix}"
    return re.sub(r"[^a-zA-Z0-9_]+", "_", text).strip("_")[:120]
