from __future__ import annotations

from typing import Any

from agent.phase3.adapters.legacy_safety_adapter import (
    LegacySafetyAdapter,
    action_from_candidate,
    fallback_wait,
    normalize_action,
)
from agent.phase3.agent_state import AgentState


class SafetyTool:
    """Phase 3 SafetyGate tool.

    SafetyGate remains a final hard-validation guardrail. It does not choose
    profit-seeking alternatives.
    """

    def __init__(self) -> None:
        self._legacy = LegacySafetyAdapter()

    def validate(self, state: AgentState) -> AgentState:
        if state.decision_state is None:
            raise ValueError("safety tool requires decision_state")
        candidate_before_safety = state.selected_candidate_id
        if state.selected_candidate is None:
            action = state.final_action
            if action is None:
                action, reason = fallback_wait(state.decision_state, "missing_selected_candidate")
                state.mark_fallback(reason, action)
            accepted, reason = self._legacy.validate(action, state.decision_state, state.visible_cargo)
            state.safety_result = {"accepted": accepted, "reason": reason}
            if not accepted:
                action, fallback_reason = fallback_wait(state.decision_state, f"fallback_safety_rejected:{reason}")
                state.mark_fallback(fallback_reason, action)
                accepted, reason = self._legacy.validate(action, state.decision_state, state.visible_cargo)
                state.safety_result = {"accepted": accepted, "reason": reason}
        else:
            proposed = action_from_candidate(state.selected_candidate)
            accepted, reason = self._legacy.validate(proposed, state.decision_state, state.visible_cargo)
            state.safety_result = {"accepted": accepted, "reason": reason}
            if not accepted:
                action, fallback_reason = fallback_wait(state.decision_state, "safety_rejection_retry_failed")
                state.mark_fallback(fallback_reason, action)
                fallback_accepted, fallback_reason_detail = self._legacy.validate(
                    action,
                    state.decision_state,
                    state.visible_cargo,
                )
                state.safety_result = {
                    "accepted": fallback_accepted,
                    "reason": fallback_reason_detail,
                    "rejected_selected_reason": reason,
                }
        summary = self.summarize_safety_result(state, candidate_before_safety)
        state.tool_summaries["safety_tool"] = summary
        state.debug["safety_summary"] = summary
        return state

    def summarize_safety_result(self, state: AgentState, candidate_before_safety: str | None = None) -> dict[str, Any]:
        reject_reason = state.safety_result.get("rejected_selected_reason") or state.safety_result.get("reason")
        safety_passed = bool(state.safety_result.get("accepted"))
        return {
            "safety_checked": True,
            "safety_passed": safety_passed,
            "safety_rejected": not safety_passed or bool(state.safety_result.get("rejected_selected_reason")),
            "safety_reject_reason": reject_reason if not safety_passed or state.safety_result.get("rejected_selected_reason") else None,
            "candidate_before_safety": candidate_before_safety,
            "final_candidate_after_safety": None if state.fallback_used else state.selected_candidate_id,
            "fallback_used": state.fallback_used,
            "fallback_reason": state.fallback_reason,
        }


def candidate_action_from_selected(state: AgentState) -> dict[str, Any] | None:
    if state.selected_candidate is None:
        return None
    return action_from_candidate(state.selected_candidate)


def normalize_final_action(action: dict[str, Any]) -> dict[str, Any]:
    return normalize_action(action)


def safe_fallback_wait(state: AgentState, reason: str) -> tuple[dict[str, Any], str]:
    return fallback_wait(state.decision_state, reason)
