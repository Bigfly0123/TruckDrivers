from __future__ import annotations

import logging
from typing import Any

from agent.phase3.domain.agent_models import Candidate, DecisionState
from agent.phase3.domain.geo_utils import distance_to_minutes, parse_wall_time_to_minute

REPOSITION_SPEED_KM_PER_HOUR = 60.0
EARTH_MAX_LAT = 90.0
EARTH_MAX_LNG = 180.0
LOAD_WINDOW_BUFFER_MINUTES = 5
DEADLINE_KEYS = (
    "load_time_window_end",
    "load_end_time",
    "loading_end_time",
    "load_deadline",
    "pickup_deadline",
    "latest_load_time",
)


class SafetyValidationService:
    """Final hard validation for executable actions."""

    def __init__(self) -> None:
        self._logger = logging.getLogger("agent.phase3.safety_service")

    def validate(
        self,
        action: dict[str, Any],
        state: DecisionState,
        items: list[dict[str, Any]],
    ) -> tuple[bool, str]:
        action_name = str(action.get("action", "")).strip().lower()
        params = action.get("params") if isinstance(action.get("params"), dict) else {}

        if action_name == "wait":
            return self._validate_wait(params, state)
        if action_name == "take_order":
            return self._validate_take_order(params, state, items)
        if action_name == "reposition":
            return self._validate_reposition(params)

        self._logger.warning("safety validation: unknown action=%s", action_name)
        return False, "invalid_action_schema"

    def _validate_wait(
        self,
        params: dict[str, Any],
        state: DecisionState,
    ) -> tuple[bool, str]:
        duration = params.get("duration_minutes", 0)
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            return False, "invalid_wait_duration"
        if duration < 1:
            return False, "wait_duration_too_short"
        if state.remaining_minutes is not None and duration > state.remaining_minutes:
            return False, "wait_exceeds_remaining"
        return True, ""

    def _validate_take_order(
        self,
        params: dict[str, Any],
        state: DecisionState,
        items: list[dict[str, Any]],
    ) -> tuple[bool, str]:
        cargo_id = str(params.get("cargo_id") or "").strip()
        if not cargo_id:
            return False, "missing_cargo_id"

        matched_item = _visible_item_by_cargo_id(items, cargo_id)
        if matched_item is None:
            return False, "cargo_not_visible"

        cargo = matched_item.get("cargo") if isinstance(matched_item.get("cargo"), dict) else {}
        deadline_minute = _parse_deadline(cargo)
        if deadline_minute is not None:
            if state.current_minute >= deadline_minute:
                return False, "load_time_window_expired"

            pickup_km = _safe_float(matched_item.get("distance_km"), 0.0)
            pickup_minutes = 0 if pickup_km <= 1e-6 else distance_to_minutes(pickup_km, REPOSITION_SPEED_KM_PER_HOUR)
            arrival_minute = state.current_minute + pickup_minutes
            if arrival_minute + LOAD_WINDOW_BUFFER_MINUTES > deadline_minute:
                return False, "load_time_window_unreachable"

        return True, ""

    def _validate_reposition(
        self,
        params: dict[str, Any],
    ) -> tuple[bool, str]:
        try:
            lat = float(params.get("latitude", 0))
            lng = float(params.get("longitude", 0))
        except (TypeError, ValueError):
            return False, "invalid_reposition_coordinates"
        if abs(lat) > EARTH_MAX_LAT or abs(lng) > EARTH_MAX_LNG:
            return False, "reposition_out_of_bounds"
        return True, ""


def action_from_candidate(candidate: Candidate) -> dict[str, Any]:
    return {"action": candidate.action, "params": dict(candidate.params)}


def normalize_action(action: dict[str, Any]) -> dict[str, Any]:
    action_name = str(action.get("action", "")).strip().lower()
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    if action_name == "take_order":
        cargo_id = str(params.get("cargo_id", "")).strip()
        if cargo_id:
            return {"action": "take_order", "params": {"cargo_id": cargo_id}}
    if action_name == "wait":
        try:
            duration = max(1, int(params.get("duration_minutes", 60)))
        except (TypeError, ValueError):
            duration = 60
        return {"action": "wait", "params": {"duration_minutes": duration}}
    if action_name == "reposition":
        try:
            return {
                "action": "reposition",
                "params": {
                    "latitude": float(params.get("latitude", 0)),
                    "longitude": float(params.get("longitude", 0)),
                },
            }
        except (TypeError, ValueError):
            pass
    return action


def fallback_wait(state: DecisionState | None, reason: str) -> tuple[dict[str, Any], str]:
    duration = 60
    if state is not None:
        duration = max(1, min(60, state.remaining_minutes or 60))
    return {"action": "wait", "params": {"duration_minutes": duration}}, reason


def _visible_item_by_cargo_id(items: list[dict[str, Any]], cargo_id: str) -> dict[str, Any] | None:
    for item in items:
        cargo = item.get("cargo") if isinstance(item.get("cargo"), dict) else {}
        if str(cargo.get("cargo_id") or "").strip() == cargo_id:
            return item
    return None


def _parse_deadline(cargo: dict[str, Any]) -> int | None:
    load_time = cargo.get("load_time")
    if isinstance(load_time, (list, tuple)) and len(load_time) == 2:
        parsed = _parse_minute(load_time[1])
        if parsed is not None:
            return parsed
    for key in DEADLINE_KEYS:
        value = cargo.get(key)
        if value is None or value == "":
            continue
        parsed = _parse_minute(value)
        if parsed is not None:
            return parsed
    return None


def _parse_minute(value: Any) -> int | None:
    try:
        return parse_wall_time_to_minute(value)
    except Exception:
        return None


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
