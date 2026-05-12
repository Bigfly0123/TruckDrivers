from __future__ import annotations

import logging
import hashlib

from agent.agent_models import DecisionState, PreferenceRule, TaskStep
from agent.mission_models import MissionPlan, MissionStep


def _mission_suffix(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:8]


def build_missions_from_rules(
    rules: tuple[PreferenceRule, ...],
    state: DecisionState,
) -> tuple[MissionPlan, ...]:
    logger = logging.getLogger("agent.task_graph_builder")
    missions: list[MissionPlan] = []
    for rule in rules:
        if not _is_high_priority_rule(rule):
            continue
        mission = _build_mission_from_rule(rule, state)
        if mission is not None:
            missions.append(mission)
            logger.info(
                "fallback mission from rule: kind=%s mission_id=%s steps=%d penalty=%.0f",
                rule.kind, mission.mission_id, len(mission.steps), rule.penalty_amount,
            )
        else:
            logger.warning(
                "cannot build mission from rule: kind=%s point=%s deadline=%s cargo_id=%s raw=%s",
                rule.kind,
                rule.point is not None,
                rule.deadline_minute is not None,
                rule.metadata.get("target_cargo_id"),
                rule.raw_text[:80],
            )
    return tuple(missions)


def _is_high_priority_rule(rule: PreferenceRule) -> bool:
    if rule.penalty_amount >= 1000:
        return True
    if rule.metadata.get("steps") or rule.metadata.get("target_cargo_id"):
        return True
    if rule.point is not None and (rule.deadline_minute is not None or rule.time_window is not None):
        return True
    return False


def _build_mission_from_rule(
    rule: PreferenceRule,
    state: DecisionState,
) -> MissionPlan | None:
    if rule.metadata.get("steps"):
        return _build_steps_mission(rule, state)
    if rule.metadata.get("target_cargo_id"):
        return _build_specific_cargo_mission(rule, state)
    if rule.point is not None and rule.time_window is not None:
        return _build_periodic_point_mission(rule, state)
    if rule.point is not None and rule.deadline_minute is not None:
        return _build_deadline_point_mission(rule, state)
    if rule.point is not None and rule.penalty_amount >= 1000:
        return _build_point_visit_mission(rule, state)
    return None


def _compute_priority(rule: PreferenceRule) -> int:
    return int(max(10, rule.penalty_amount / 100))


def _build_multi_step_mission(rule: PreferenceRule, state: DecisionState) -> MissionPlan | None:
    steps_data = rule.metadata.get("steps", ())
    if steps_data:
        mission_steps: list[MissionStep] = []
        for i, step_data in enumerate(steps_data):
            if not isinstance(step_data, TaskStep):
                continue
            ms = _task_step_to_mission_step(step_data, f"mstep_{i}", lock_mode="hard_stay")
            if ms is not None:
                mission_steps.append(ms)
        if mission_steps and not any(s.action_type == "stay_within_radius" for s in mission_steps):
            final_point = mission_steps[-1].point
            stay_deadline = rule.active_end_minute or rule.deadline_minute
            if final_point is not None and stay_deadline is not None:
                mission_steps.append(MissionStep(
                    step_id="mstep_stay_final",
                    action_type="stay_within_radius",
                    point=final_point,
                    earliest_minute=rule.active_start_minute,
                    deadline_minute=stay_deadline,
                    forbidden_actions=("take_order", "reposition"),
                    lock_mode="hard_stay",
                ))
        if mission_steps:
            return MissionPlan(
                mission_id=f"mission_steps_{_mission_suffix(rule.raw_text)}",
                source_preference=rule.raw_text,
                priority=_compute_priority(rule),
                steps=tuple(mission_steps),
            )
    if rule.point is not None and rule.deadline_minute is not None:
        return _build_deadline_point_mission(rule, state)
    return None


def _build_specific_cargo_mission(rule: PreferenceRule, state: DecisionState) -> MissionPlan | None:
    cargo_id = rule.metadata.get("target_cargo_id")
    if not cargo_id:
        return None
    steps: list[MissionStep] = []
    if rule.point is not None:
        steps.append(MissionStep(
            step_id="go_pickup",
            action_type="go_to_point",
            point=rule.point,
            deadline_minute=rule.deadline_minute,
        ))
    if rule.active_start_minute is not None or rule.deadline_minute is not None:
        wait_deadline = rule.active_start_minute or rule.deadline_minute
        if wait_deadline is not None:
            steps.append(MissionStep(
                step_id="wait_available",
                action_type="wait_until",
                deadline_minute=wait_deadline,
            ))
    steps.append(MissionStep(
        step_id="take_cargo",
        action_type="take_specific_cargo",
        cargo_id=cargo_id,
        point=rule.point,
        deadline_minute=rule.active_end_minute or rule.deadline_minute,
        lock_mode="deadline_target",
    ))
    return MissionPlan(
        mission_id=f"mission_cargo_{cargo_id}",
        source_preference=rule.raw_text,
        priority=_compute_priority(rule),
        steps=tuple(steps),
    )


def _build_periodic_point_mission(rule: PreferenceRule, state: DecisionState) -> MissionPlan | None:
    if rule.point is None or rule.time_window is None:
        return None
    deadline = rule.deadline_minute
    if deadline is None and rule.active_end_minute is not None:
        deadline = rule.active_end_minute
    steps: list[MissionStep] = [
        MissionStep(
            step_id="go_home",
            action_type="go_to_point",
            point=rule.point,
            deadline_minute=rule.time_window.start_minute_of_day if deadline is None else None,
        ),
    ]
    if deadline is not None:
        steps.append(MissionStep(
            step_id="stay_home",
            action_type="stay_within_radius",
            point=rule.point,
            deadline_minute=deadline,
            forbidden_actions=("take_order", "reposition"),
            lock_mode="periodic_home",
        ))
    return MissionPlan(
        mission_id=f"mission_periodic_point_{_mission_suffix(rule.raw_text)}",
        source_preference=rule.raw_text,
        priority=_compute_priority(rule),
        steps=tuple(steps),
        metadata={
            "window_start_minute_of_day": rule.time_window.start_minute_of_day,
            "window_end_minute_of_day": rule.time_window.end_minute_of_day,
        },
    )


def _build_point_visit_mission(rule: PreferenceRule, state: DecisionState) -> MissionPlan | None:
    if rule.point is None:
        return None
    return MissionPlan(
        mission_id=f"mission_point_{_mission_suffix(rule.raw_text)}",
        source_preference=rule.raw_text,
        priority=int(max(5, rule.penalty_amount / 200)),
        steps=(
            MissionStep(
                step_id="go_visit",
                action_type="go_to_point",
                point=rule.point,
                duration_minutes=60,
            ),
        ),
    )


def _build_deadline_point_mission(rule: PreferenceRule, state: DecisionState) -> MissionPlan | None:
    if rule.point is None or rule.deadline_minute is None:
        return None
    steps: list[MissionStep] = [
        MissionStep(
            step_id="go_to_point",
            action_type="go_to_point",
            point=rule.point,
            deadline_minute=rule.deadline_minute,
        ),
    ]
    if rule.required_minutes and rule.required_minutes > 0:
        steps.append(MissionStep(
            step_id="stay",
            action_type="wait_duration",
            point=rule.point,
            duration_minutes=min(rule.required_minutes, 480),
        ))
    return MissionPlan(
        mission_id=f"mission_deadline_point_{_mission_suffix(rule.raw_text)}",
        source_preference=rule.raw_text,
        priority=_compute_priority(rule),
        steps=tuple(steps),
    )


def _build_steps_mission(rule: PreferenceRule, state: DecisionState) -> MissionPlan | None:
    steps_data = rule.metadata.get("steps", ())
    if not steps_data:
        return None
    mission_steps: list[MissionStep] = []
    for i, step_data in enumerate(steps_data):
        if not isinstance(step_data, TaskStep):
            continue
        ms = _task_step_to_mission_step(step_data, f"step_{i}")
        if ms is not None:
            mission_steps.append(ms)
    if not mission_steps:
        return None
    return MissionPlan(
        mission_id=f"mission_steps_{_mission_suffix(rule.raw_text)}",
        source_preference=rule.raw_text,
        priority=_compute_priority(rule),
        steps=tuple(mission_steps),
    )


def _task_step_to_mission_step(ts: TaskStep, step_id: str, *, lock_mode: str = "none") -> MissionStep | None:
    action_map = {
        "visit": "go_to_point",
        "go_to_point": "go_to_point",
        "wait": "wait_duration",
        "wait_duration": "wait_duration",
        "wait_until": "wait_until",
        "stay": "stay_within_radius",
        "stay_within_radius": "stay_within_radius",
    }
    action_type = action_map.get(ts.action)
    if action_type is None:
        if ts.point is not None:
            action_type = "go_to_point"
        else:
            return None
    resolved_lock = lock_mode
    if action_type == "stay_within_radius" and lock_mode == "none":
        resolved_lock = "hard_stay"
    return MissionStep(
        step_id=step_id,
        action_type=action_type,
        point=ts.point,
        earliest_minute=ts.earliest_minute,
        deadline_minute=ts.deadline_minute,
        duration_minutes=ts.stay_minutes if ts.stay_minutes > 0 else None,
        lock_mode=resolved_lock,
    )
