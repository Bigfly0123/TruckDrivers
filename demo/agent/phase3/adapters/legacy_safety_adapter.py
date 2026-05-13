from __future__ import annotations

from typing import Any

from agent.agent_models import Candidate, DecisionState
from agent.safety_gate import SafetyGate


class LegacySafetyAdapter:
    def __init__(self) -> None:
        self._safety_gate = SafetyGate()

    def validate(
        self,
        action: dict[str, Any],
        state: DecisionState,
        items: list[dict[str, Any]],
    ) -> tuple[bool, str]:
        return self._safety_gate.validate(action, state, items)


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
