from __future__ import annotations

from typing import Any

from agent.agent_models import Candidate
from agent.llm_decision_advisor import AdvisorContext
from agent.phase3.adapters.legacy_advisor_adapter import LegacyAdvisorAdapter, preference_text
from agent.phase3.adapters.legacy_constraint_adapter import LegacyConstraintAdapter
from agent.phase3.adapters.legacy_safety_adapter import fallback_wait
from agent.phase3.agent_state import AgentState
from agent.phase3.planning.day_plan import DayPlan
from simkit.ports import SimulationApiPort


class AdvisorTool:
    """Phase 3 advisor tool.

    LLM output remains constrained to candidate_id selection. This tool prepares
    input and records diagnostics, but does not invent executable actions.
    """

    def __init__(self, api: SimulationApiPort) -> None:
        self._legacy = LegacyAdvisorAdapter(api)
        self._constraint_adapter = LegacyConstraintAdapter()

    def decide(self, state: AgentState) -> AgentState:
        if state.decision_state is None:
            raise ValueError("advisor tool requires decision_state")
        executable = state.valid_candidates + state.soft_risk_candidates
        day_plan_context = _day_plan_context(state)
        state.advisor_context = {
            "candidate_count": len(executable),
            "day_plan": day_plan_context,
            "has_day_plan": bool(day_plan_context),
        }
        if not executable:
            action, reason = fallback_wait(state.decision_state, "no_candidates_available")
            state.mark_fallback(reason, action)
            summary = self.summarize_advisor_result(state)
            state.tool_summaries["advisor_tool"] = summary
            state.debug["advisor_summary"] = summary
            return state

        candidate_summaries = self._constraint_adapter.build_candidate_summaries(state.evaluated_candidates)
        result = self._legacy.advise(
            AdvisorContext(
                state=state.decision_state,
                rules=state.preference_rules,
                valid_candidates=state.valid_candidates,
                soft_risk_candidates=state.soft_risk_candidates,
                raw_preferences=[preference_text(p) for p in list(state.raw_preferences or [])],
                recent_actions=_recent_actions(state),
                trigger_reason="normal_candidate_decision",
                candidate_summaries=candidate_summaries,
                day_plan=day_plan_context,
            )
        )
        if result is None:
            action, reason = fallback_wait(state.decision_state, "llm_api_failed")
            state.mark_fallback(reason, action)
        else:
            selected = _find_candidate(executable, result.selected_candidate_id)
            if selected is None:
                action, reason = fallback_wait(state.decision_state, "advisor_invalid_candidate")
                state.mark_fallback(reason, action)
                state.selected_candidate_id = result.selected_candidate_id
            else:
                state.advisor_result = {
                    "selected_candidate_id": result.selected_candidate_id,
                    "reason": result.reason,
                    "accepted_risks": list(result.accepted_risks),
                }
                state.selected_candidate_id = result.selected_candidate_id
                state.selected_candidate = selected
        summary = self.summarize_advisor_result(state)
        state.tool_summaries["advisor_tool"] = summary
        state.debug["advisor_summary"] = summary
        return state

    def summarize_advisor_result(self, state: AgentState) -> dict[str, Any]:
        selected = state.selected_candidate
        return {
            "selected_candidate_id": state.selected_candidate_id,
            "selected_candidate_source": selected.source if selected else None,
            "selected_candidate_action": selected.action if selected else None,
            "selected_candidate_estimated_net": _fact_float(selected, "estimated_net"),
            "selected_candidate_penalty_exposure": _fact_float(selected, "estimated_penalty_exposure"),
            "selected_candidate_estimated_net_after_penalty": _fact_float(selected, "estimated_net_after_penalty"),
            "advisor_reason": state.advisor_result.get("reason"),
            "candidate_pool_size_sent_to_advisor": state.advisor_context.get("candidate_count", 0),
            "day_plan_primary_goal": (state.advisor_context.get("day_plan") or {}).get("primary_goal"),
            "day_plan_guidance_count": len((state.advisor_context.get("day_plan") or {}).get("advisor_guidance") or []),
            "day_plan_risk_focus_count": len((state.advisor_context.get("day_plan") or {}).get("risk_focus") or []),
            "day_plan_language": (state.advisor_context.get("day_plan") or {}).get("language"),
            "fallback_used": state.fallback_used,
            "fallback_reason": state.fallback_reason,
        }


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


def _day_plan_context(state: AgentState) -> dict[str, Any]:
    if state.day_plan is not None:
        return state.day_plan.normalize(_normalization_context(state)).to_advisor_context()
    plan = DayPlan(
        driver_id=state.driver_id,
        day=int(state.current_day or 0),
        strategy_summary="",
        primary_goal="",
        fallback_used=True,
        reason="planning_node_missing_day_plan",
    ).normalize(_normalization_context(state))
    return plan.to_advisor_context()


def _normalization_context(state: AgentState) -> dict[str, Any]:
    constraint_summary = state.debug.get("constraint_summary", {})
    return {
        "constraint_types": sorted({getattr(c, "kind", "") for c in state.constraints if getattr(c, "kind", "")}),
        "dominant_hard_invalid_reason": constraint_summary.get("dominant_hard_invalid_reason"),
        "hard_invalid_reason_counts": constraint_summary.get("hard_invalid_reason_counts"),
        "runtime_summary": state.debug.get("runtime_summary", {}),
        "diagnostic_summary": state.debug.get("decision_diagnosis", {}),
    }


def _fact_float(candidate: Candidate | None, key: str) -> float | None:
    if candidate is None:
        return None
    value = candidate.facts.get(key)
    if value is None and key == "estimated_net_after_penalty":
        value = candidate.facts.get("estimated_net")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
