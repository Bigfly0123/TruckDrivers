from __future__ import annotations

import logging
from typing import Any

from agent.agent_models import DecisionState
from agent.geo_utils import haversine_km


PROTECTED_WAIT_KEYWORDS = frozenset({
    "daily rest",
    "quiet hours",
    "home",
    "stay",
    "mission",
    "pickup",
    "family",
    "nightly",
    "visit",
    "off day",
})


class ActionContract:
    """Final generic action sanity checks before returning to the simulator.

    This is not a strategy layer. It only rejects actions that are malformed,
    physically meaningless, or likely to fail validation regardless of driver
    preference semantics.
    """

    def __init__(self) -> None:
        self._logger = logging.getLogger("agent.action_contract")

    def enforce(
        self,
        action: dict[str, Any],
        state: DecisionState,
        visible_items: list[dict[str, Any]],
        *,
        source: str = "",
    ) -> dict[str, Any]:
        action_name = str(action.get("action", "")).strip().lower()
        params = action.get("params") if isinstance(action.get("params"), dict) else {}

        if action_name == "take_order":
            cargo_id = str(params.get("cargo_id") or "").strip()
            if not cargo_id:
                return self._fallback_wait(state, "missing_cargo_id", source)
            visible_ids = self._visible_cargo_ids(visible_items)
            if cargo_id not in visible_ids:
                self._logger.info(
                    "action contract rejected take_order: source=%s cargo=%s not_in_visible_items",
                    source,
                    cargo_id,
                )
                return self._fallback_wait(state, "cargo_not_visible", source)
            return action

        if action_name == "reposition":
            try:
                dest_lat = float(params["latitude"])
                dest_lng = float(params["longitude"])
            except (KeyError, TypeError, ValueError):
                return self._fallback_wait(state, "bad_reposition_target", source)
            dist = haversine_km(state.current_latitude, state.current_longitude, dest_lat, dest_lng)
            if dist < 0.5:
                self._logger.info(
                    "action contract rejected reposition: source=%s distance=%.2fkm",
                    source,
                    dist,
                )
                return self._fallback_wait(state, "tiny_reposition", source)
            return action

        if action_name == "wait":
            try:
                duration = int(params.get("duration_minutes", 60))
            except (TypeError, ValueError):
                duration = 60
            duration = max(1, min(duration, max(1, state.remaining_minutes or duration)))
            reason = str(
                params.get("_planner_reason")
                or params.get("_safety_rejection_reason")
                or params.get("_advisor_reason")
                or ""
            )
            protected = any(k in reason for k in PROTECTED_WAIT_KEYWORDS)
            if source == "mission":
                protected = True
            if duration > 480 and not protected:
                self._logger.info(
                    "action contract clamped long wait: source=%s duration=%d reason=%s",
                    source,
                    duration,
                    reason,
                )
                duration = 180
            new_params = dict(params)
            new_params["duration_minutes"] = duration
            return {"action": "wait", "params": new_params}

        return self._fallback_wait(state, "unknown_action", source)

    def _visible_cargo_ids(self, visible_items: list[dict[str, Any]]) -> set[str]:
        ids: set[str] = set()
        for item in visible_items:
            cargo = item.get("cargo") if isinstance(item, dict) and isinstance(item.get("cargo"), dict) else item
            if not isinstance(cargo, dict):
                continue
            cargo_id = str(cargo.get("cargo_id") or "").strip()
            if cargo_id:
                ids.add(cargo_id)
        return ids

    def _fallback_wait(self, state: DecisionState, reason: str, source: str) -> dict[str, Any]:
        wait = max(1, min(60, state.remaining_minutes or 60))
        self._logger.info(
            "action contract fallback wait: source=%s reason=%s duration=%d",
            source,
            reason,
            wait,
        )
        return {
            "action": "wait",
            "params": {
                "duration_minutes": wait,
                "_contract_rejection_reason": reason,
            },
        }
