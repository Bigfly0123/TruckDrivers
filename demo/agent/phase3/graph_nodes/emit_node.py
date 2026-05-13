from __future__ import annotations

from agent.phase3.agent_state import AgentState
from agent.phase3.tools.diagnostic_tool import DiagnosticTool
from agent.phase3.tools.safety_tool import (
    candidate_action_from_selected,
    normalize_final_action,
    safe_fallback_wait,
)


class EmitNode:
    node_name = "emit_node"

    def __init__(self) -> None:
        self._diagnostic_tool = DiagnosticTool()

    def __call__(self, state: AgentState) -> AgentState:
        if state.final_action is not None:
            state.final_action = normalize_final_action(state.final_action)
        elif state.selected_candidate is not None and state.safety_result.get("accepted"):
            selected_action = candidate_action_from_selected(state)
            if selected_action is not None:
                state.final_action = normalize_final_action(selected_action)
        else:
            action, reason = safe_fallback_wait(state, "emit_missing_safe_action")
            state.mark_fallback(reason, action)
        diagnosis = self._diagnostic_tool.build_decision_diagnosis(state)
        _set_summary(state, self.node_name, {
            "final_action_type": (state.final_action or {}).get("action"),
            "selected_candidate_id": state.selected_candidate_id,
            "fallback_used": state.fallback_used,
            "fallback_reason": state.fallback_reason,
            "decision_diagnosis": diagnosis,
        })
        return state


def _set_summary(state: AgentState, node_name: str, summary: dict[str, object]) -> None:
    state.debug.setdefault("node_summaries", {})[node_name] = summary
