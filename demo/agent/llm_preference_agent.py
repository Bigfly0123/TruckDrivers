from __future__ import annotations

import json
import logging
import re
from typing import Any

from agent.agent_models import AreaBounds, GeoPoint, PreferenceRule, TaskStep, TimeWindow
from agent.geo_utils import parse_wall_time_to_minute


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
    if value.get("lat") is None or value.get("lng") is None:
        return None
    radius = _safe_float(value.get("radius_km"), 1.0)
    return GeoPoint(_safe_float(value.get("lat")), _safe_float(value.get("lng")), radius or 1.0)


def _window_from_dict(value: Any) -> TimeWindow | None:
    if not isinstance(value, dict):
        return None
    start = value.get("start_minute_of_day")
    end = value.get("end_minute_of_day")
    if start is None or end is None:
        start_hour = value.get("start_hour")
        end_hour = value.get("end_hour")
        if start_hour is None or end_hour is None:
            return None
        return TimeWindow(_safe_int(start_hour) * 60, _safe_int(end_hour) * 60)
    return TimeWindow(_safe_int(start), _safe_int(end))


def _area_from_dict(value: Any) -> AreaBounds | None:
    if not isinstance(value, dict):
        return None
    keys = ("lat_min", "lat_max", "lng_min", "lng_max")
    if any(value.get(key) is None for key in keys):
        return None
    return AreaBounds(
        _safe_float(value.get("lat_min")),
        _safe_float(value.get("lat_max")),
        _safe_float(value.get("lng_min")),
        _safe_float(value.get("lng_max")),
    )


def _step_from_dict(value: Any) -> TaskStep | None:
    if not isinstance(value, dict):
        return None
    action = str(value.get("action") or "visit").strip() or "visit"
    point = _point_from_dict(value.get("point"))
    earliest = parse_wall_time_to_minute(value.get("earliest_time")) if value.get("earliest_time") else None
    deadline = parse_wall_time_to_minute(value.get("deadline")) if value.get("deadline") else None
    return TaskStep(
        action=action,
        point=point,
        earliest_minute=earliest,
        deadline_minute=deadline,
        stay_minutes=max(0, _safe_int(value.get("stay_minutes"), 0)),
        label=str(value.get("label") or ""),
    )


class LlmPreferenceAgent:
    def __init__(self, api: Any | None) -> None:
        self._api = api
        self._logger = logging.getLogger("agent.llm_preference_agent")

    def parse(self, entry: Any) -> list[PreferenceRule]:
        if self._api is None:
            return []
        try:
            payload = self._build_payload(entry)
            response = self._api.model_chat_completion(payload)
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "{}")
            data = json.loads(self._extract_json(content))
        except Exception as exc:
            self._logger.info("llm preference parse failed: %s", exc)
            return []
        return self._rules_from_payload(entry, data)

    def _build_payload(self, entry: Any) -> dict[str, Any]:
        schema_hint = {
            "rules": [
                {
                    "kind": "daily_rest|weekday_rest|quiet_hours|home_nightly|forbidden_cargo|soft_forbidden_cargo|off_days|visit_point|multi_step_task|special_cargo|area_bounds|forbidden_zone|max_pickup_deadhead|max_haul_distance|max_monthly_deadhead|first_order_deadline|max_daily_orders|unknown",
                    "priority": "hard|soft",
                    "hours": None,
                    "required_days": None,
                    "cargo_names": [],
                    "target_cargo_id": None,
                    "point": {"lat": None, "lng": None, "radius_km": 1},
                    "time_window": {"start_hour": None, "end_hour": None},
                    "area_bounds": {"lat_min": 0, "lat_max": 0, "lng_min": 0, "lng_max": 0},
                    "deadline": None,
                    "distance_limit_km": None,
                    "steps": [
                        {
                            "action": "visit|wait",
                            "point": {"lat": None, "lng": None, "radius_km": 1},
                            "earliest_time": None,
                            "deadline": None,
                            "stay_minutes": 0,
                        }
                    ],
                }
            ]
        }
        system_prompt = (
            "You convert Chinese truck-driver preferences into structured JSON for a simulator.\n\n"
            "IMPORTANT RULES:\n"
            "1. Understand the SEMANTIC MEANING of the preference, not just keywords.\n"
            "2. A preference like 'must return home before 11pm' means home_nightly with time_window 23:00-08:00.\n"
            "3. A preference like 'old customer special cargo' means special_cargo with target_cargo_id.\n"
            "4. A preference like 'family emergency' means multi_step_task with steps.\n"
            "5. Do NOT assume preference types are fixed. New types may appear.\n"
            "6. If a preference is unclear, use 'unknown' kind.\n"
            "7. Extract ALL time-sensitive and location-sensitive tasks.\n\n"
            "PREFERENCE TYPES:\n"
            "- daily_rest: daily rest requirement (e.g., 'rest 8 hours daily')\n"
            "- weekday_rest: weekday-only rest requirement\n"
            "- quiet_hours: time window when driver cannot take orders (e.g., 'no orders 23:00-06:00')\n"
            "- home_nightly: must be at home location by certain time (e.g., 'return home before 11pm')\n"
            "- forbidden_cargo: cargo types to avoid (e.g., 'no chemicals')\n"
            "- soft_forbidden_cargo: cargo types to avoid if possible\n"
            "- off_days: required days off per month\n"
            "- visit_point: must visit a location on certain days\n"
            "- multi_step_task: complex task with multiple steps (e.g., 'pick up spouse, then return home')\n"
            "- special_cargo: specific cargo to take (e.g., 'cargo CARGO_ID')\n"
            "- area_bounds: geographic area restriction\n"
            "- forbidden_zone: area to avoid\n"
            "- max_pickup_deadhead: max distance to pickup\n"
            "- max_haul_distance: max haul distance\n"
            "- max_monthly_deadhead: max monthly deadhead distance\n"
            "- first_order_deadline: deadline for first order of the day\n"
            "- max_daily_orders: max orders per day\n\n"
            "EXAMPLES:\n"
            "Input: '每天23点前车辆须在自家位置（LAT，LNG）一公里内'\n"
            "Output: home_nightly with point=(LAT,LNG), time_window=23:00-08:00\n\n"
            "Input: '指定熟货源编号CARGO_ID'\n"
            "Output: special_cargo with target_cargo_id=CARGO_ID\n\n"
            "Input: '须先到（LAT1，LNG1）接上配偶，再返回老家（LAT2，LNG2）'\n"
            "Output: multi_step_task with steps=[go_to_point(LAT1,LNG1), go_to_point(LAT2,LNG2)]\n\n"
            "Input: '只在北纬22.42至22.89，东经113.74至114.66范围内运营'\n"
            "Output: area_bounds with area_bounds={lat_min:22.42, lat_max:22.89, lng_min:113.74, lng_max:114.66}\n\n"
            "Return strict JSON matching this shape: "
            + json.dumps(schema_hint, ensure_ascii=False)
        )
        return {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps({"preference": entry}, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
        }

    def _extract_json(self, content: str) -> str:
        text = str(content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text).strip()
            text = re.sub(r"```$", "", text).strip()
        return text or "{}"

    def _rules_from_payload(self, entry: Any, data: dict[str, Any]) -> list[PreferenceRule]:
        raw_text = self._entry_text(entry)
        penalty_amount, penalty_cap = self._extract_penalty(entry)
        active_start, active_end = self._extract_active_minutes(entry)
        rules_raw = data.get("rules") if isinstance(data.get("rules"), list) else [data]
        out: list[PreferenceRule] = []
        for item in rules_raw:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "unknown").strip()
            if kind == "soft_forbidden_cargo":
                kind = "forbidden_cargo"
                priority = "soft"
            else:
                priority = str(item.get("priority") or "soft").strip()
            point = _point_from_dict(item.get("point"))
            window = _window_from_dict(item.get("time_window"))
            area = _area_from_dict(item.get("area_bounds"))
            steps = tuple(step for raw in (item.get("steps") or []) if (step := _step_from_dict(raw)) is not None)
            metadata: dict[str, Any] = {}
            if steps:
                metadata["steps"] = steps
            if item.get("target_cargo_id") is not None:
                metadata["target_cargo_id"] = str(item.get("target_cargo_id")).strip()
            rule = PreferenceRule(
                kind=kind,
                priority=priority if priority in {"hard", "soft"} else "soft",
                penalty_amount=penalty_amount,
                penalty_cap=penalty_cap,
                time_window=window,
                cargo_names=tuple(str(v).strip() for v in (item.get("cargo_names") or []) if str(v).strip()),
                point=point,
                area_bounds=area,
                distance_limit_km=_safe_float(item.get("distance_limit_km")) if item.get("distance_limit_km") is not None else None,
                required_minutes=_safe_int(item.get("hours"), 0) * 60 if item.get("hours") is not None else None,
                required_days=_safe_int(item.get("required_days"), 0) if item.get("required_days") is not None else None,
                deadline_minute=parse_wall_time_to_minute(item.get("deadline")) if item.get("deadline") else None,
                active_start_minute=active_start,
                active_end_minute=active_end,
                raw_text=raw_text,
                metadata=metadata,
            )
            if rule.kind and rule.kind != "unknown":
                out.append(rule)
        return out

    def _entry_text(self, entry: Any) -> str:
        if isinstance(entry, str):
            return entry.strip()
        if isinstance(entry, dict):
            return str(entry.get("content") or entry.get("text") or "").strip()
        return ""

    def _extract_penalty(self, entry: Any) -> tuple[float, float | None]:
        if not isinstance(entry, dict):
            return 0.0, None
        amount = _safe_float(entry.get("penalty_amount"), 0.0)
        cap = None if entry.get("penalty_cap") is None else _safe_float(entry.get("penalty_cap"), 0.0)
        return amount, cap

    def _extract_active_minutes(self, entry: Any) -> tuple[int | None, int | None]:
        if not isinstance(entry, dict):
            return None, None
        return parse_wall_time_to_minute(entry.get("start_time")), parse_wall_time_to_minute(entry.get("end_time"))
