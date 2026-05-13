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

from agent.agent_models import GeoPoint
from agent.geo_utils import parse_wall_time_to_minute
from agent.mission_models import MissionPlan, MissionStep

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


class LlmMissionPlanner:
    def __init__(self, api: Any | None) -> None:
        self._api = api
        self._logger = logging.getLogger("agent.llm_mission_planner")

    def plan(
        self,
        preferences: list[dict[str, Any]],
        current_minute: int,
        current_lat: float,
        current_lng: float,
        history_summary: dict[str, Any] | None = None,
        visible_cargo_summary: list[dict[str, Any]] | None = None,
    ) -> tuple[MissionPlan, ...]:
        if not preferences:
            return ()
        if self._api is None:
            return ()
        try:
            missions = self._call_llm(preferences, current_minute, current_lat, current_lng, history_summary, visible_cargo_summary)
            self._logger.info("LLM mission planning returned %d missions", len(missions))
            for m in missions:
                self._logger.info("  mission=%s priority=%d steps=%d", m.mission_id, m.priority, len(m.steps))
            return missions
        except Exception as exc:
            self._logger.warning("LLM mission planning failed: %s", exc)
            return ()

    def _entry_text(self, entry: Any) -> str:
        if isinstance(entry, str):
            return entry.strip()
        if isinstance(entry, dict):
            return str(entry.get("content") or entry.get("text") or "").strip()
        return ""

    def _call_llm(
        self,
        prefs: list[dict[str, Any]],
        current_minute: int,
        current_lat: float,
        current_lng: float,
        history_summary: dict[str, Any] | None,
        visible_cargo_summary: list[dict[str, Any]] | None,
    ) -> tuple[MissionPlan, ...]:
        schema_hint = {
            "missions": [
                {
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
                    ],
                }
            ]
        }
        system_prompt = (
            "You convert Chinese truck-driver preference rules into structured mission plans for a simulator.\n\n"
            "CRITICAL RULES - READ CAREFULLY:\n"
            "1. Create missions for HIGH-PENALTY, TIME-SENSITIVE, or LOCATION-SENSITIVE tasks:\n"
            "   - Special cargo with specific cargo_id and deadline\n"
            "   - Multi-step tasks (pick up someone, return home, stay until event ends)\n"
            "   - Tasks with explicit deadline AND specific location (must go somewhere by a time)\n"
            "   - When a preference describes a sequence of movements or time-bound stays, you MUST generate a mission\n"
            "   - When a preference has a high penalty_amount (>= 1000), strongly consider creating a mission\n"
            "2. DO NOT create missions for SIMPLE preferences (handled by other system):\n"
            "   - Daily rest requirements (e.g., 'rest 8 hours daily')\n"
            "   - Quiet hours (e.g., 'no orders 23:00-06:00')\n"
            "   - Forbidden cargo types (e.g., 'no chemicals')\n"
            "   - Area restrictions without specific time constraints (e.g., 'stay in Shenzhen')\n"
            "   - Simple visit point counts without deadline (e.g., 'visit location 5 days per month')\n"
            "3. stay_within_radius RULES:\n"
            "   - MUST have a deadline\n"
            "   - earliest is optional (defaults to arrival time if not set)\n"
            "   - Can cover multi-day stays (e.g., stay home for several days until a date)\n"
            "4. ADVANCE POSITIONING for future tasks:\n"
            "   - When a task has a specific time in the future, create a go_to_point step with deadline\n"
            "   - Example: '须在3月10日22:00前到家' -> go_to_point with deadline='2026-03-10 22:00'\n"
            "5. COORDINATE ACCURACY:\n"
            "   - Copy coordinates EXACTLY from the preference text. Do NOT round or approximate.\n"
            "6. Return EMPTY missions array if no complex tasks found: {\"missions\": []}\n\n"
            "ACTION TYPES:\n"
            "- go_to_point: move to a location (point required, deadline optional)\n"
            "- wait_until: wait until a specific time (deadline required)\n"
            "- wait_duration: wait for a duration at a point (point + duration_minutes required)\n"
            "- take_specific_cargo: take a specific cargo (cargo_id required)\n"
            "- stay_within_radius: stay within radius (point + deadline required, earliest optional, forbidden_actions optional)\n"
            "- avoid_actions: avoid certain actions in a time window (earliest + deadline + forbidden_actions required)\n\n"
            "EXAMPLES OF CORRECT MISSIONS:\n"
            "Input: '指定熟货源编号CARGO_ID，装货地（LAT，LNG），上架时间YYYY-MM-DD HH:MM:SS'\n"
            "Output: {\"missions\": [{\"mission_id\": \"cargo_CARGO_ID\", \"priority\": 100, \"steps\": [{\"step_id\": \"go_pickup\", \"action_type\": \"go_to_point\", \"point\": {\"lat\": LAT, \"lng\": LNG}, \"deadline\": \"YYYY-MM-DD HH:MM\"}, {\"step_id\": \"wait_available\", \"action_type\": \"wait_until\", \"deadline\": \"YYYY-MM-DD HH:MM\"}, {\"step_id\": \"take_cargo\", \"action_type\": \"take_specific_cargo\", \"cargo_id\": \"CARGO_ID\"}]}]}\n\n"
            "Input: '须先到（LAT1，LNG1）接上配偶（原地停留不少于10分钟），再返回老家（LAT2，LNG2），须在YYYY-MM-DD HH:MM前进家门，到家后须在原处静止，至少待到YYYY-MM-DD HH:MM'\n"
            "Output: {\"missions\": [{\"mission_id\": \"family_emergency\", \"priority\": 100, \"steps\": [{\"step_id\": \"go_spouse\", \"action_type\": \"go_to_point\", \"point\": {\"lat\": LAT1, \"lng\": LNG1}, \"deadline\": \"YYYY-MM-DD HH:MM\"}, {\"step_id\": \"wait_spouse\", \"action_type\": \"wait_duration\", \"point\": {\"lat\": LAT1, \"lng\": LNG1}, \"duration_minutes\": 10}, {\"step_id\": \"go_home\", \"action_type\": \"go_to_point\", \"point\": {\"lat\": LAT2, \"lng\": LNG2}, \"deadline\": \"YYYY-MM-DD HH:MM\"}, {\"step_id\": \"stay_home\", \"action_type\": \"stay_within_radius\", \"point\": {\"lat\": LAT2, \"lng\": LNG2}, \"earliest\": \"YYYY-MM-DD HH:MM\", \"deadline\": \"YYYY-MM-DD HH:MM\", \"forbidden_actions\": [\"take_order\", \"reposition\"]}]}]}\n\n"
            "EXAMPLES OF WHAT NOT TO CREATE MISSIONS FOR:\n"
            "Input: '每天至少连续停车休息满8小时' -> Output: {\"missions\": []}\n"
            "Input: '不接化工塑料' -> Output: {\"missions\": []}\n"
            "Input: '每天凌晨2点至5点不接单' -> Output: {\"missions\": []}\n\n"
            "Return strict JSON matching this shape: "
            + json.dumps(schema_hint, ensure_ascii=False)
        )
        user_payload = {
            "preferences": [self._entry_text(p) for p in prefs],
            "current_time": _minute_to_wall_time(current_minute),
            "current_location": {"lat": current_lat, "lng": current_lng},
        }
        if history_summary:
            user_payload["history_summary"] = history_summary
        if visible_cargo_summary:
            user_payload["visible_cargo_summary"] = visible_cargo_summary[:10]
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
        return self._parse_response(data, prefs)

    def _extract_json(self, content: str) -> str:
        text = str(content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text).strip()
            text = re.sub(r"```$", "", text).strip()
        return text or "{}"

    def _parse_response(self, data: dict[str, Any], prefs: list[dict[str, Any]]) -> tuple[MissionPlan, ...]:
        raw_missions = data.get("missions") if isinstance(data.get("missions"), list) else []
        missions: list[MissionPlan] = []
        skipped_steps = 0
        for i, raw in enumerate(raw_missions):
            if not isinstance(raw, dict):
                continue
            mission_id = str(raw.get("mission_id") or f"mission_{i}").strip()
            priority = _safe_int(raw.get("priority"), 100)
            steps_raw = raw.get("steps") if isinstance(raw.get("steps"), list) else []
            steps: list[MissionStep] = []
            for j, step_raw in enumerate(steps_raw):
                step = _step_from_dict(mission_id, j, step_raw)
                if step is None:
                    raw_at = str(step_raw.get("action_type") or "") if isinstance(step_raw, dict) else "non-dict"
                    self._logger.warning("step skipped: mission=%s index=%d action_type=%s", mission_id, j, raw_at)
                    skipped_steps += 1
                    continue
                if self._is_valid_step(step):
                    steps.append(step)
                else:
                    self._logger.warning("step invalid: mission=%s index=%d action_type=%s", mission_id, j, step.action_type)
                    skipped_steps += 1
            if not steps:
                self._logger.warning("mission %s has 0 valid steps (total raw=%d, skipped=%d)", mission_id, len(steps_raw), skipped_steps)
                continue
            source = self._entry_text(prefs[i]) if i < len(prefs) else ""
            missions.append(MissionPlan(
                mission_id=mission_id,
                source_preference=source,
                priority=priority,
                steps=tuple(steps),
            ))
        if skipped_steps > 0:
            self._logger.warning("total skipped steps=%d across all missions", skipped_steps)
        return tuple(missions)

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
