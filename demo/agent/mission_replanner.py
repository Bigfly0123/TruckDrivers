from __future__ import annotations

"""
LEGACY MODULE.

Not used by the default Phase 3 graph workflow. Kept for rollback,
comparison, and historical reference. Do not reintroduce it as a
decision-control component.
"""

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any

from agent.agent_models import DecisionState, GeoPoint
from agent.geo_utils import haversine_km, parse_wall_time_to_minute
from agent.mission_models import MissionPlan, MissionProgress, MissionStep

_SIMULATION_EPOCH = datetime(2026, 3, 1, 0, 0, 0)

_VALID_ACTION_TYPES = frozenset({
    "go_to_point", "wait_until", "wait_duration",
    "take_specific_cargo", "stay_within_radius", "avoid_actions",
})

_ACTION_TYPE_ALIASES: dict[str, str] = {
    "visit": "go_to_point",
    "go_to": "go_to_point",
    "move": "go_to_point",
    "move_to": "go_to_point",
    "be_at_point": "go_to_point",
    "wait": "wait_duration",
    "rest": "wait_duration",
    "rest_continuously": "wait_duration",
    "stay": "stay_within_radius",
    "avoid_action_until": "avoid_actions",
    "avoid_action": "avoid_actions",
}


def _normalize_action_type(raw: str) -> str | None:
    t = raw.strip().lower()
    if t in _VALID_ACTION_TYPES:
        return t
    return _ACTION_TYPE_ALIASES.get(t)


def _minute_to_wall_time(minute: int) -> str:
    dt = _SIMULATION_EPOCH + timedelta(minutes=int(minute))
    return dt.strftime("%Y-%m-%d %H:%M")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _point_from_dict(value: Any) -> GeoPoint | None:
    if not isinstance(value, dict):
        return None
    lat = value.get("lat")
    lng = value.get("lng")
    if lat is None or lng is None:
        return None
    radius = _safe_float(value.get("radius_km"), 1.0)
    return GeoPoint(_safe_float(lat), _safe_float(lng), radius or 1.0)


def _step_from_dict(step_id_prefix: str, index: int, raw: dict[str, Any]) -> MissionStep | None:
    if not isinstance(raw, dict):
        return None
    raw_action_type = str(raw.get("action_type") or "").strip()
    action_type = _normalize_action_type(raw_action_type)
    if action_type is None:
        return None
    step_id = str(raw.get("step_id") or f"{step_id_prefix}_step_{index}").strip()
    point = _point_from_dict(raw.get("point"))
    earliest = parse_wall_time_to_minute(raw.get("earliest")) if raw.get("earliest") else None
    deadline = parse_wall_time_to_minute(raw.get("deadline")) if raw.get("deadline") else None
    duration = _safe_int(raw.get("duration_minutes")) if raw.get("duration_minutes") is not None else None
    cargo_id = str(raw.get("cargo_id") or "").strip() or None
    forbidden = tuple(str(v).strip() for v in (raw.get("forbidden_actions") or []) if str(v).strip())
    return MissionStep(
        step_id=step_id,
        action_type=action_type,
        point=point,
        earliest_minute=earliest,
        deadline_minute=deadline,
        duration_minutes=duration if duration and duration > 0 else None,
        cargo_id=cargo_id,
        forbidden_actions=forbidden,
    )


class MissionReplanner:
    def __init__(self, api: Any | None) -> None:
        self._api = api
        self._logger = logging.getLogger("agent.mission_replanner")

    def should_replan(
        self,
        mission: MissionPlan,
        progress: MissionProgress,
        state: DecisionState,
    ) -> bool:
        if not progress.active_step_id:
            return False
        active_step = None
        for step in mission.steps:
            if step.step_id == progress.active_step_id:
                active_step = step
                break
        if active_step is None:
            return False
        if active_step.action_type == "stay_within_radius":
            if active_step.deadline_minute is None:
                return True
        if active_step.deadline_minute is not None:
            remaining = active_step.deadline_minute - state.current_minute
            if remaining < 0:
                return True
            if active_step.point is not None:
                dist = haversine_km(
                    state.current_latitude, state.current_longitude,
                    active_step.point.latitude, active_step.point.longitude,
                )
                travel_minutes = max(30, int(dist / 60 * 60))
                if remaining < travel_minutes + 30:
                    return True
            elif remaining < 30:
                return True
        if active_step.action_type == "take_specific_cargo" and active_step.cargo_id:
            return True
        if progress.stuck_wait_count >= 20:
            return True
        return False

    def replan(
        self,
        mission: MissionPlan,
        progress: MissionProgress,
        state: DecisionState,
        visible_cargo: list[dict[str, Any]] | None = None,
    ) -> MissionPlan | None:
        if self._api is None:
            return None
        try:
            return self._call_llm(mission, progress, state, visible_cargo)
        except Exception as exc:
            self._logger.warning("LLM mission replanning failed: %s", exc)
            return None

    def _call_llm(
        self,
        mission: MissionPlan,
        progress: MissionProgress,
        state: DecisionState,
        visible_cargo: list[dict[str, Any]] | None,
    ) -> MissionPlan | None:
        schema_hint = {
            "mission_id": "string",
            "priority": 0,
            "steps": [
                {
                    "step_id": "string",
                    "action_type": "go_to_point|wait_until|wait_duration|take_specific_cargo|stay_within_radius|avoid_actions",
                    "point": {"lat": 0.0, "lng": 0.0, "radius_km": 1.0},
                    "earliest": "YYYY-MM-DD HH:MM or null",
                    "deadline": "YYYY-MM-DD HH:MM or null",
                    "duration_minutes": "int or null",
                    "cargo_id": "string or null",
                    "forbidden_actions": ["take_order", "reposition"],
                }
            ]
        }
        system_prompt = (
            "You are replanning a mission for a truck driver simulator.\n\n"
            "The current mission is failing or at risk. Analyze the situation and provide an updated plan.\n\n"
            "IMPORTANT RULES:\n"
            "1. Understand the SEMANTIC MEANING of the original mission.\n"
            "2. If a deadline is about to be missed, create a more urgent plan.\n"
            "3. If a cargo is not visible, suggest waiting or moving to pickup location.\n"
            "4. If multiple constraints conflict, prioritize the higher-priority mission.\n"
            "5. Be conservative: when in doubt, go to the target point and wait.\n\n"
            "Return strict JSON matching this shape: "
            + json.dumps(schema_hint, ensure_ascii=False)
        )
        active_step = None
        for step in mission.steps:
            if step.step_id == progress.active_step_id:
                active_step = step
                break
        user_payload = {
            "mission_id": mission.mission_id,
            "source_preference": mission.source_preference,
            "current_time": _minute_to_wall_time(state.current_minute),
            "current_location": {"lat": state.current_latitude, "lng": state.current_longitude},
            "active_step": {
                "step_id": active_step.step_id if active_step else None,
                "action_type": active_step.action_type if active_step else None,
                "point": {"lat": active_step.point.latitude, "lng": active_step.point.longitude, "radius_km": active_step.point.radius_km} if active_step and active_step.point else None,
                "deadline": _minute_to_wall_time(active_step.deadline_minute) if active_step and active_step.deadline_minute else None,
            } if active_step else None,
            "completed_steps": list(progress.completed_step_ids),
            "remaining_minutes": state.remaining_minutes,
        }
        if visible_cargo:
            user_payload["visible_cargo_summary"] = visible_cargo[:10]
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
        }
        response = self._api.model_chat_completion(payload)
        content = response.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        data = json.loads(self._extract_json(content))
        return self._parse_response(data, mission)

    def _extract_json(self, content: str) -> str:
        text = str(content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text).strip()
            text = re.sub(r"```$", "", text).strip()
        return text or "{}"

    def _parse_response(self, data: dict[str, Any], original_mission: MissionPlan) -> MissionPlan | None:
        mission_id = str(data.get("mission_id") or original_mission.mission_id).strip()
        priority = _safe_int(data.get("priority"), original_mission.priority)
        steps_raw = data.get("steps") if isinstance(data.get("steps"), list) else []
        steps: list[MissionStep] = []
        for j, step_raw in enumerate(steps_raw):
            step = _step_from_dict(mission_id, j, step_raw)
            if step is not None:
                if self._is_valid_step(step):
                    steps.append(step)
        if not steps:
            return None
        return MissionPlan(
            mission_id=mission_id,
            source_preference=original_mission.source_preference,
            priority=priority,
            steps=tuple(steps),
        )

    def _is_valid_step(self, step: MissionStep) -> bool:
        if step.action_type == "stay_within_radius":
            if step.deadline_minute is None:
                return False
            if step.earliest_minute is not None:
                duration = step.deadline_minute - step.earliest_minute
                if duration <= 0:
                    return False
        if step.action_type == "wait_duration":
            if step.duration_minutes is not None and step.duration_minutes > 480:
                return False
        return True
