from __future__ import annotations

from typing import Any

from agent.phase3.services.safety_service import (
    SafetyValidationService,
    action_from_candidate,
    fallback_wait,
    normalize_action,
)
from agent.phase3.agent_state import AgentState
from agent.phase3.tools.recovery import (
    choose_recovery_candidate,
    fallback_provenance,
    rank_recovery_candidates,
    recovery_candidate_summary,
)


class SafetyTool:
    """Phase 3 safety validation tool.

    Final safety validation remains a hard guardrail. It does not choose
    profit-seeking alternatives.
    """

    def __init__(self) -> None:
        self._safety = SafetyValidationService()

    def validate(self, state: AgentState) -> AgentState:
        if state.decision_state is None:
            raise ValueError("safety tool requires decision_state")
        candidate_before_safety = state.selected_candidate_id
        executable = _executable_candidates(state)
        if state.selected_candidate is None:
            action = state.final_action
            if action is None:
                recovered, recovery_reason = choose_recovery_candidate(executable)
                if recovered is not None:
                    state.selected_candidate_id = recovered.candidate_id
                    state.selected_candidate = recovered
                    state.advisor_result.update({
                        "recovery_used": True,
                        "recovery_reason": f"missing_selected_candidate:{recovery_reason}",
                        **recovery_candidate_summary(recovered),
                    })
                    action = action_from_candidate(recovered)
                else:
                    action, reason = fallback_wait(state.decision_state, "missing_selected_candidate")
                    state.mark_fallback(reason, action)
                    state.debug["fallback_provenance"] = fallback_provenance(
                        source="safety_tool",
                        reason=reason,
                        candidates=executable,
                        recovery_attempted=True,
                        recovery_failed_reason=recovery_reason,
                    )
            accepted, reason = self._safety.validate(action, state.decision_state, state.visible_cargo)
            state.safety_result = {"accepted": accepted, "reason": reason}
            if not accepted:
                recovered = None
                recovery_reason = "no_executable_candidate_for_recovery"
                recovery_reason_detail = ""
                for candidate, candidate_recovery_reason in rank_recovery_candidates(
                    executable
                ):
                    recovery_action = action_from_candidate(candidate)
                    recovery_accepted, recovery_reason_detail = self._safety.validate(
                        recovery_action,
                        state.decision_state,
                        state.visible_cargo,
                    )
                    if recovery_accepted:
                        recovered = candidate
                        recovery_reason = candidate_recovery_reason
                        break
                if recovered is not None:
                    state.selected_candidate_id = recovered.candidate_id
                    state.selected_candidate = recovered
                    state.advisor_result.update({
                        "recovery_used": True,
                        "recovery_reason": f"safety_rejected_missing_selected:{recovery_reason}",
                        **recovery_candidate_summary(recovered),
                    })
                    state.safety_result = {
                        "accepted": True,
                        "reason": recovery_reason_detail,
                        "rejected_selected_reason": reason,
                        "safety_recovery_used": True,
                        "safety_recovery_reason": recovery_reason,
                        **recovery_candidate_summary(recovered),
                    }
                else:
                    action, fallback_reason = fallback_wait(state.decision_state, f"fallback_safety_rejected:{reason}")
                    state.mark_fallback(fallback_reason, action)
                    state.debug["fallback_provenance"] = fallback_provenance(
                        source="safety_tool",
                        reason=fallback_reason,
                        candidates=executable,
                        recovery_attempted=True,
                        recovery_failed_reason=recovery_reason_detail or recovery_reason,
                    )
                    accepted, reason = self._safety.validate(action, state.decision_state, state.visible_cargo)
                    state.safety_result = {"accepted": accepted, "reason": reason}
        else:
            proposed = action_from_candidate(state.selected_candidate)
            accepted, reason = self._safety.validate(proposed, state.decision_state, state.visible_cargo)
            state.safety_result = {"accepted": accepted, "reason": reason}
            if not accepted:
                ranked_recovery = rank_recovery_candidates(
                    executable,
                    exclude_candidate_ids={state.selected_candidate.candidate_id},
                )
                recovered = None
                recovery_reason = "no_executable_candidate_for_recovery"
                recovery_reason_detail = ""
                for candidate, candidate_recovery_reason in ranked_recovery:
                    recovery_action = action_from_candidate(candidate)
                    recovery_accepted, recovery_reason_detail = self._safety.validate(
                        recovery_action,
                        state.decision_state,
                        state.visible_cargo,
                    )
                    if not recovery_accepted:
                        continue
                    recovered = candidate
                    recovery_reason = candidate_recovery_reason
                    break
                if recovered is not None:
                    recovery_action = action_from_candidate(recovered)
                    state.safety_result = {
                        "accepted": True,
                        "reason": recovery_reason_detail,
                        "rejected_selected_reason": reason,
                        "safety_recovery_used": True,
                        "safety_recovery_reason": recovery_reason,
                        **recovery_candidate_summary(recovered),
                    }
                    state.selected_candidate_id = recovered.candidate_id
                    state.selected_candidate = recovered
                    state.advisor_result.update({
                        "recovery_used": True,
                        "recovery_reason": f"safety_rejected:{recovery_reason}",
                        **recovery_candidate_summary(recovered),
                    })
                else:
                    action, fallback_reason = fallback_wait(state.decision_state, "all_recovery_candidates_failed_safety")
                    state.mark_fallback(fallback_reason, action)
                    state.debug["fallback_provenance"] = fallback_provenance(
                        source="safety_tool",
                        reason=fallback_reason,
                        candidates=executable,
                        recovery_attempted=True,
                        recovery_failed_reason=recovery_reason_detail or recovery_reason,
                    )
                    fallback_accepted, fallback_reason_detail = self._safety.validate(
                        action,
                        state.decision_state,
                        state.visible_cargo,
                    )
                    state.safety_result = {
                        "accepted": fallback_accepted,
                        "reason": fallback_reason_detail,
                        "rejected_selected_reason": reason,
                        "safety_recovery_attempted_count": len(ranked_recovery),
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
            "safety_recovery_used": bool(state.safety_result.get("safety_recovery_used")),
            "safety_recovery_reason": state.safety_result.get("safety_recovery_reason"),
            "recovery_candidate_id": state.safety_result.get("recovery_candidate_id"),
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


def _executable_candidates(state: AgentState) -> list[Any]:
    return state.executable_candidates or (state.valid_candidates + state.soft_risk_candidates)
