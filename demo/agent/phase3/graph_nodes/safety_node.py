from __future__ import annotations

from agent.phase3.adapters.legacy_safety_adapter import (
    LegacySafetyAdapter,
    action_from_candidate,
    fallback_wait,
)
from agent.phase3.agent_state import AgentState


class SafetyNode:
    node_name = "safety_node"

    def __init__(self) -> None:
        self._adapter = LegacySafetyAdapter()

    def __call__(self, state: AgentState) -> AgentState:
        if state.decision_state is None:
            raise ValueError("safety node requires decision_state")
        if state.selected_candidate is None:
            action = state.final_action
            if action is None:
                action, reason = fallback_wait(state.decision_state, "missing_selected_candidate")
                state.mark_fallback(reason, action)
            accepted, reason = self._adapter.validate(action, state.decision_state, state.visible_cargo)
            if not accepted:
                action, fallback_reason = fallback_wait(state.decision_state, f"fallback_safety_rejected:{reason}")
                state.mark_fallback(fallback_reason, action)
                accepted, reason = self._adapter.validate(action, state.decision_state, state.visible_cargo)
            state.safety_result = {"accepted": accepted, "reason": reason}
            _set_summary(state, self.node_name, {
                "selected_candidate_id": state.selected_candidate_id,
                "safety_passed": accepted,
                "safety_reason": reason,
                "fallback_used": state.fallback_used,
            })
            return state

        proposed_action = action_from_candidate(state.selected_candidate)
        accepted, reason = self._adapter.validate(proposed_action, state.decision_state, state.visible_cargo)
        state.safety_result = {"accepted": accepted, "reason": reason}
        if not accepted:
            action, fallback_reason = fallback_wait(state.decision_state, "safety_rejection_retry_failed")
            state.mark_fallback(fallback_reason, action)
            fallback_accepted, fallback_validation_reason = self._adapter.validate(
                action,
                state.decision_state,
                state.visible_cargo,
            )
            state.safety_result = {
                "accepted": fallback_accepted,
                "reason": fallback_validation_reason,
                "rejected_selected_reason": reason,
            }
        _set_summary(state, self.node_name, {
            "selected_candidate_id": state.selected_candidate_id,
            "safety_passed": state.safety_result.get("accepted"),
            "safety_reason": state.safety_result.get("reason"),
            "fallback_used": state.fallback_used,
        })
        return state


def _set_summary(state: AgentState, node_name: str, summary: dict[str, object]) -> None:
    state.debug.setdefault("node_summaries", {})[node_name] = summary
