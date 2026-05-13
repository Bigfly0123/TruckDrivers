from __future__ import annotations

from agent.phase3.adapters.legacy_safety_adapter import (
    action_from_candidate,
    fallback_wait,
    normalize_action,
)
from agent.phase3.agent_state import AgentState


class EmitNode:
    node_name = "emit_node"

    def __call__(self, state: AgentState) -> AgentState:
        if state.final_action is not None:
            state.final_action = normalize_action(state.final_action)
        elif state.selected_candidate is not None and state.safety_result.get("accepted"):
            state.final_action = normalize_action(action_from_candidate(state.selected_candidate))
        else:
            action, reason = fallback_wait(state.decision_state, "emit_missing_safe_action")
            state.mark_fallback(reason, action)
        _set_summary(state, self.node_name, {
            "final_action_type": (state.final_action or {}).get("action"),
            "selected_candidate_id": state.selected_candidate_id,
            "fallback_used": state.fallback_used,
            "fallback_reason": state.fallback_reason,
        })
        return state


def _set_summary(state: AgentState, node_name: str, summary: dict[str, object]) -> None:
    state.debug.setdefault("node_summaries", {})[node_name] = summary
