from __future__ import annotations

from agent.phase3.agent_state import AgentState
from agent.planner import estimate_scan_cost
from agent.state_tracker import StateTracker
from simkit.ports import SimulationApiPort


class ObserveNode:
    node_name = "observe_node"

    def __init__(self, api: SimulationApiPort) -> None:
        self._api = api
        self._state_tracker = StateTracker()

    def __call__(self, state: AgentState) -> AgentState:
        status = self._api.get_driver_status(state.driver_id)
        latitude = float(status["current_lat"])
        longitude = float(status["current_lng"])
        cargo_response = self._api.query_cargo(
            driver_id=state.driver_id,
            latitude=latitude,
            longitude=longitude,
        )
        items = cargo_response.get("items", [])
        if not isinstance(items, list):
            items = []
        history = self._api.query_decision_history(state.driver_id, -1)
        records = history.get("records") if isinstance(history, dict) else []
        if not isinstance(records, list):
            records = []

        decision_state = self._state_tracker.build(
            driver_id=state.driver_id,
            status=status,
            history_payload=history,
            scan_cost_minutes=estimate_scan_cost(len(items)),
            empty_query=len(items) == 0,
        )

        state.driver_status = status
        state.visible_cargo = items
        state.decision_history = records
        state.raw_preferences = list(status.get("preferences") or [])
        state.decision_state = decision_state
        state.step_id = len(decision_state.history_records)
        state.current_time = decision_state.current_minute
        state.current_day = decision_state.current_day
        state.current_location = {
            "lat": decision_state.current_latitude,
            "lng": decision_state.current_longitude,
        }
        _set_summary(state, self.node_name, {
            "current_time": state.current_time,
            "current_day": state.current_day,
            "visible_cargo_count": len(items),
            "history_count": len(records),
            "current_location": state.current_location,
        })
        return state


def _set_summary(state: AgentState, node_name: str, summary: dict[str, object]) -> None:
    state.debug.setdefault("node_summaries", {})[node_name] = summary
