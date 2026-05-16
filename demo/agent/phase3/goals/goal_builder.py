from __future__ import annotations

from dataclasses import replace
from datetime import datetime
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
        arrival_deadline = _terminal_arrival_deadline(constraint)
        if arrival_deadline is not None:
            _apply_sequence_deadline(steps, arrival_deadline)
        terminal_hold = _terminal_hold_step(goal_id, constraint, steps)
        if terminal_hold is not None:
            steps.append(terminal_hold)
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


def _terminal_hold_step(goal_id: str, constraint: Any, steps: list[GoalStep]) -> GoalStep | None:
    metadata = getattr(constraint, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        return None
    raw_text = str(getattr(constraint, "raw_text", "") or "")
    active_end = metadata.get("active_end_minute")
    if active_end is None:
        return None
    if not _needs_terminal_stay(raw_text):
        return None
    point = _last_step_point(steps)
    if point is None:
        return None
    if steps and steps[-1].step_type == "hold_location_until_time" and steps[-1].deadline_minute == active_end:
        return None
    return GoalStep(
        step_id=f"{goal_id}_step_{len(steps)}_terminal_hold",
        step_type="hold_location_until_time",
        point=point,
        earliest_minute=metadata.get("active_start_minute"),
        deadline_minute=int(active_end),
        label="terminal_hold_until_active_end",
        metadata={"generated_terminal_hold": True, "source": "raw_text_hold_until_active_end"},
    )


def _terminal_arrival_deadline(constraint: Any) -> int | None:
    metadata = getattr(constraint, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        return None
    raw_text = str(getattr(constraint, "raw_text", "") or "")
    if not _needs_terminal_stay(raw_text):
        return None
    active_start = _safe_int_or_none(metadata.get("active_start_minute"))
    active_end = _safe_int_or_none(metadata.get("active_end_minute"))
    if active_start is None:
        return None
    candidates = [
        minute for minute in _absolute_minutes_in_text(raw_text)
        if minute > active_start and (active_end is None or minute < active_end)
    ]
    if candidates:
        return min(candidates)
    return None


def _apply_sequence_deadline(steps: list[GoalStep], deadline_minute: int) -> None:
    for index in range(len(steps)):
        step = steps[index]
        if step.point is None:
            continue
        if step.step_type not in {"reach_location", "return_to_location", "stay_until_time", "stay_at_location"}:
            continue
        if step.deadline_minute is not None and int(step.deadline_minute) <= deadline_minute:
            continue
        steps[index] = replace(step, deadline_minute=int(deadline_minute))


def _absolute_minutes_in_text(raw_text: str) -> list[int]:
    result: list[int] = []
    pattern = re.compile(r"(20\d{2})\D{0,8}(\d{1,2})\D{0,8}(\d{1,2})\D{0,12}(\d{1,2}):(\d{2})")
    for match in pattern.finditer(str(raw_text or "")):
        year, month, day, hour, minute = (int(part) for part in match.groups())
        try:
            dt = datetime(year, month, day, hour, minute)
        except ValueError:
            continue
        epoch = datetime(2026, 3, 1, 0, 0, 0)
        result.append(int((dt - epoch).total_seconds() // 60))
    return result


def _safe_int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _needs_terminal_stay(raw_text: str) -> bool:
    text = str(raw_text or "")
    stay_tokens = ("静止", "待到", "待至", "至少待", "留在", "不得离开", "不可离开", "方可再出车", "解决方可再出车")
    home_tokens = ("到家后", "回家", "老家", "家中", "原处")
    mojibake_stay_tokens = ("é™æ­¢", "å¾…åˆ°", "å¾…è‡³", "è‡³å°‘å¾…", "ç•™åœ¨", "ä¸å¾—ç¦»å¼€", "æ–¹å¯å†å‡ºè½¦")
    mojibake_home_tokens = ("åˆ°å®¶åŽ", "å›žå®¶", "è€å®¶", "å®¶ä¸­", "åŽŸå¤„")
    return (
        any(token in text for token in stay_tokens) and any(token in text for token in home_tokens)
    ) or (
        any(token in text for token in mojibake_stay_tokens) and any(token in text for token in mojibake_home_tokens)
    )


def _last_step_point(steps: list[GoalStep]) -> Any | None:
    for step in reversed(steps):
        if step.point is not None:
            return step.point
    return None


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
