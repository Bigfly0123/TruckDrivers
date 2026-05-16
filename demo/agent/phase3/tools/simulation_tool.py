from __future__ import annotations

from typing import Any

from agent.phase3.candidates.candidate_fact_builder import estimate_scan_cost
from agent.phase3.observation.state_tracker import StateTracker
from simkit.ports import SimulationApiPort


class SimulationTool:
    """Phase 3 deterministic observation tool.

    Tool = stable Phase 3 interface. It may use current adapters/modules
    internally, but graph nodes should depend on this interface.
    """

    def __init__(self, api: SimulationApiPort) -> None:
        self._api = api
        self._state_tracker = StateTracker()

    def observe(self, driver_id: str) -> dict[str, Any]:
        status = self._api.get_driver_status(driver_id)
        latitude = float(status["current_lat"])
        longitude = float(status["current_lng"])
        cargo_response = self._api.query_cargo(
            driver_id=driver_id,
            latitude=latitude,
            longitude=longitude,
        )
        items = cargo_response.get("items", [])
        if not isinstance(items, list):
            items = []
        history = self._api.query_decision_history(driver_id, -1)
        records = history.get("records") if isinstance(history, dict) else []
        if not isinstance(records, list):
            records = []
        decision_state = self._state_tracker.build(
            driver_id=driver_id,
            status=status,
            history_payload=history,
            scan_cost_minutes=estimate_scan_cost(len(items)),
            empty_query=len(items) == 0,
        )
        return {
            "driver_status": status,
            "visible_cargo": items,
            "decision_history": records,
            "raw_preferences": list(status.get("preferences") or []),
            "decision_state": decision_state,
            "step_id": len(decision_state.history_records),
            "current_time": decision_state.current_minute,
            "current_day": decision_state.current_day,
            "current_location": {
                "lat": decision_state.current_latitude,
                "lng": decision_state.current_longitude,
            },
        }
