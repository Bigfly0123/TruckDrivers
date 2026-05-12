from __future__ import annotations

import logging
from typing import Any

from agent.agent_models import DecisionState
from agent.geo_utils import haversine_km, parse_wall_time_to_minute
from agent.planner import _DEADLINE_KEYS, LOAD_WINDOW_BUFFER_MINUTES


REPOSITION_SPEED_KM_PER_HOUR = 60.0
EARTH_MAX_LAT = 90.0
EARTH_MAX_LNG = 180.0


class SafetyGate:
    def __init__(self) -> None:
        self._logger = logging.getLogger("agent.safety_gate")

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

        self._logger.warning("safety_gate: unknown action=%s", action_name)
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

        visible_ids = set()
        for item in items:
            cargo = item.get("cargo") if isinstance(item.get("cargo"), dict) else {}
            cid = str(cargo.get("cargo_id") or "").strip()
            if cid:
                visible_ids.add(cid)
        if cargo_id not in visible_ids:
            return False, "cargo_not_visible"

        matched_item = None
        for item in items:
            cargo = item.get("cargo") if isinstance(item.get("cargo"), dict) else {}
            if str(cargo.get("cargo_id") or "").strip() == cargo_id:
                matched_item = item
                break
        if matched_item is None:
            return False, "cargo_not_found"

        cargo = matched_item.get("cargo") if isinstance(matched_item.get("cargo"), dict) else {}
        deadline_minute = self._parse_deadline(cargo)
        if deadline_minute is not None:
            if state.current_minute >= deadline_minute:
                return False, "load_time_window_expired"

            pickup_km = 0.0
            try:
                pickup_km = float(matched_item.get("distance_km", 0))
            except (TypeError, ValueError):
                pass
            from agent.geo_utils import distance_to_minutes
            pickup_minutes = 0 if pickup_km <= 1e-6 else distance_to_minutes(pickup_km, REPOSITION_SPEED_KM_PER_HOUR)
            arrival_minute = state.current_minute + pickup_minutes
            if arrival_minute + LOAD_WINDOW_BUFFER_MINUTES > deadline_minute:
                return False, "load_time_window_unreachable"

        return True, ""

    def _parse_deadline(self, cargo: dict[str, Any]) -> int | None:
        for key in _DEADLINE_KEYS:
            value = cargo.get(key)
            if value is None or value == "":
                continue
            try:
                parsed = parse_wall_time_to_minute(value)
            except Exception:
                parsed = None
            if parsed is not None:
                return parsed
        return None

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
