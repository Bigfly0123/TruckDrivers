from __future__ import annotations

from typing import Any

from agent.agent_models import Candidate
from agent.llm_decision_advisor import AdvisorContext
from agent.phase3.adapters.legacy_advisor_adapter import LegacyAdvisorAdapter, preference_text
from agent.phase3.adapters.legacy_constraint_adapter import LegacyConstraintAdapter
from agent.phase3.adapters.legacy_safety_adapter import fallback_wait
from agent.phase3.agent_state import AgentState
from simkit.ports import SimulationApiPort


class AdvisorNode:
    node_name = "advisor_node"

    def __init__(self, api: SimulationApiPort) -> None:
        self._adapter = LegacyAdvisorAdapter(api)
        self._constraint_adapter = LegacyConstraintAdapter()

    def __call__(self, state: AgentState) -> AgentState:
        if state.decision_state is None:
            raise ValueError("advisor node requires decision_state")
        executable = state.valid_candidates + state.soft_risk_candidates
        state.advisor_context = {"candidate_count": len(executable)}
        if not executable:
            action, reason = fallback_wait(state.decision_state, "no_candidates_available")
            state.mark_fallback(reason, action)
            _set_summary(state, self.node_name, {
                "advisor_candidate_count": 0,
                "fallback_used": True,
                "fallback_reason": reason,
            })
            return state

        candidate_summaries = self._constraint_adapter.build_candidate_summaries(state.evaluated_candidates)
        advisor_result = self._adapter.advise(
            AdvisorContext(
                state=state.decision_state,
                rules=state.preference_rules,
                valid_candidates=state.valid_candidates,
                soft_risk_candidates=state.soft_risk_candidates,
                raw_preferences=[preference_text(p) for p in list(state.raw_preferences or [])],
                recent_actions=_recent_actions(state),
                trigger_reason="normal_candidate_decision",
                candidate_summaries=candidate_summaries,
            )
        )
        if advisor_result is None:
            action, reason = fallback_wait(state.decision_state, "llm_api_failed")
            state.mark_fallback(reason, action)
            _set_summary(state, self.node_name, {
                "advisor_candidate_count": len(executable),
                "fallback_used": True,
                "fallback_reason": reason,
            })
            return state

        selected = _find_candidate(executable, advisor_result.selected_candidate_id)
        if selected is None:
            action, reason = fallback_wait(state.decision_state, "advisor_invalid_candidate")
            state.mark_fallback(reason, action)
            _set_summary(state, self.node_name, {
                "advisor_candidate_count": len(executable),
                "selected_candidate_id": advisor_result.selected_candidate_id,
                "fallback_used": True,
                "fallback_reason": reason,
            })
            return state

        state.advisor_result = {
            "selected_candidate_id": advisor_result.selected_candidate_id,
            "reason": advisor_result.reason,
            "accepted_risks": list(advisor_result.accepted_risks),
        }
        state.selected_candidate_id = advisor_result.selected_candidate_id
        state.selected_candidate = selected
        _set_summary(state, self.node_name, {
            "advisor_candidate_count": len(executable),
            "selected_candidate_id": selected.candidate_id,
            "selected_action": selected.action,
            "reason": advisor_result.reason,
            "fallback_used": False,
        })
        return state


def _recent_actions(state: AgentState) -> list[dict[str, Any]]:
    if state.decision_state is None:
        return []
    results: list[dict[str, Any]] = []
    for record in state.decision_state.history_records[-5:]:
        action = record.get("action") or record.get("action_name") or ""
        results.append({
            "action": str(action),
            "minute": record.get("minute") or record.get("simulation_minute"),
            "params": record.get("params") or {},
        })
    return results


def _find_candidate(candidates: list[Candidate], candidate_id: str) -> Candidate | None:
    for candidate in candidates:
        if candidate.candidate_id == candidate_id:
            return candidate
    return None


def _set_summary(state: AgentState, node_name: str, summary: dict[str, object]) -> None:
    state.debug.setdefault("node_summaries", {})[node_name] = summary
