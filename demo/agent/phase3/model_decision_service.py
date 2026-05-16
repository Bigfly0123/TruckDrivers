from __future__ import annotations

import logging
from typing import Any

from agent.phase3 import AgentState, build_default_graph
from simkit.ports import SimulationApiPort


class ModelDecisionService:
    def __init__(self, api: SimulationApiPort) -> None:
        self._logger = logging.getLogger("agent.decision_service")
        self._graph_runner = build_default_graph(api)

    def decide(self, driver_id: str) -> dict[str, Any]:
        state = AgentState(driver_id=driver_id)
        try:
            final_state = self._graph_runner.run(state)
            if final_state.final_action is not None:
                return self._normalize_action(final_state.final_action)
            self._logger.warning("phase3 graph returned no final action for driver_id=%s", driver_id)
            state.mark_fallback("phase3_missing_final_action", {"action": "wait", "params": {"duration_minutes": 60}})
            state.debug["fallback_provenance"] = {
                "fallback_used": True,
                "fallback_source": "model_decision_service",
                "fallback_reason": "phase3_missing_final_action",
                "fallback_wait_type": "unproven_fallback",
                "executable_candidate_count_before_fallback": 0,
                "profitable_order_existed_before_fallback": False,
                "recovery_attempted": False,
            }
            self._graph_runner.record_decision_summary(state)
        except Exception as exc:
            self._logger.exception("phase3 graph failed for driver_id=%s: %s", driver_id, exc)
            state.mark_fallback("phase3_unexpected_exception", {"action": "wait", "params": {"duration_minutes": 60}})
            state.debug["fallback_provenance"] = {
                "fallback_used": True,
                "fallback_source": "model_decision_service",
                "fallback_reason": "phase3_unexpected_exception",
                "fallback_wait_type": "unproven_fallback",
                "executable_candidate_count_before_fallback": 0,
                "profitable_order_existed_before_fallback": False,
                "recovery_attempted": False,
            }
            self._graph_runner.record_decision_summary(state)
        return {"action": "wait", "params": {"duration_minutes": 60}}

    def _normalize_action(self, action: dict[str, Any]) -> dict[str, Any]:
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
