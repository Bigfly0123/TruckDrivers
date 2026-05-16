from __future__ import annotations

from typing import Any

from agent.phase3.domain.agent_models import Candidate
from agent.phase3.advisor.llm_decision_advisor import AdvisorContext
from agent.phase3.agent_state import AgentState
from agent.phase3.planning.day_plan import DayPlan
from agent.phase3.services.advisor_service import AdvisorService, preference_text
from agent.phase3.services.constraint_evaluation_service import ConstraintEvaluationService
from agent.phase3.services.safety_service import fallback_wait
from agent.phase3.tools.recovery import (
    choose_recovery_candidate,
    fallback_provenance,
    recovery_candidate_summary,
)
from simkit.ports import SimulationApiPort


class AdvisorTool:
    """Phase 3 advisor tool.

    LLM output remains constrained to candidate_id selection. This tool prepares
    input and records diagnostics, but does not invent executable actions.
    """

    def __init__(self, api: SimulationApiPort) -> None:
        self._advisor = AdvisorService(api)
        self._constraints = ConstraintEvaluationService()

    def decide(self, state: AgentState) -> AgentState:
        if state.decision_state is None:
            raise ValueError("advisor tool requires decision_state")
        executable = _executable_candidates(state)
        day_plan_context = _day_plan_context(state)
        advisor_valid, advisor_soft = _advisor_visible_candidates(state)
        advisor_executable = advisor_valid + advisor_soft
        opportunity_summary = state.debug.get("advisor_opportunity_summary", state.debug.get("opportunity_summary", {}))
        state.advisor_context = {
            "candidate_count": len(advisor_executable),
            "executable_candidate_count": len(executable),
            "day_plan": day_plan_context,
            "has_day_plan": bool(day_plan_context),
            "reflection_hints": list((state.reflection_context or {}).get("hints") or []),
            "active_reflection_hint_count": int((state.reflection_context or {}).get("active_reflection_hint_count") or 0),
            "opportunity_summary": opportunity_summary,
            "opportunity_facts_count": len(state.opportunity_facts),
            "decision_core_top_candidate_ids": [c.candidate_id for c in advisor_executable],
            "decision_core_filtered_candidate_count": max(0, len(executable) - len(advisor_executable)),
        }
        if not executable:
            action, reason = fallback_wait(state.decision_state, "no_candidates_available")
            state.mark_fallback(reason, action)
            state.debug["fallback_provenance"] = fallback_provenance(
                source="advisor_tool",
                reason=reason,
                candidates=executable,
                recovery_attempted=False,
            )
            summary = self.summarize_advisor_result(state)
            state.tool_summaries["advisor_tool"] = summary
            state.debug["advisor_summary"] = summary
            return state

        candidate_summaries = self._constraints.build_candidate_summaries(state.evaluated_candidates)
        opportunity_by_id = {
            str(fact.get("candidate_id")): fact
            for fact in state.opportunity_facts
            if isinstance(fact, dict) and fact.get("candidate_id")
        }
        result = self._advisor.advise(
            AdvisorContext(
                state=state.decision_state,
                rules=state.preference_rules,
                valid_candidates=advisor_valid,
                soft_risk_candidates=advisor_soft,
                raw_preferences=[preference_text(p) for p in list(state.raw_preferences or [])],
                recent_actions=_recent_actions(state),
                trigger_reason="normal_candidate_decision",
                candidate_summaries=candidate_summaries,
                day_plan=day_plan_context,
                reflection_hints=list((state.reflection_context or {}).get("hints") or []),
                opportunity_summary=opportunity_summary,
                candidate_opportunity_facts=opportunity_by_id,
            )
        )
        if result is None:
            recovered, recovery_reason = choose_recovery_candidate(executable)
            if recovered is None:
                action, reason = fallback_wait(state.decision_state, "llm_api_failed_no_recovery")
                state.mark_fallback(reason, action)
                state.debug["fallback_provenance"] = fallback_provenance(
                    source="advisor_tool",
                    reason=reason,
                    candidates=executable,
                    recovery_attempted=True,
                    recovery_failed_reason=recovery_reason,
                )
            else:
                state.selected_candidate_id = recovered.candidate_id
                state.selected_candidate = recovered
                state.advisor_result = {
                    "selected_candidate_id": recovered.candidate_id,
                    "reason": f"deterministic recovery after advisor returned no usable result: {recovery_reason}",
                    "accepted_risks": [],
                    "advisor_no_result": True,
                    "recovery_used": True,
                    "recovery_reason": recovery_reason,
                    **recovery_candidate_summary(recovered),
                }
        else:
            recovery_pool = advisor_executable or executable
            selected = None if not result.candidate_known else _find_candidate(executable, result.selected_candidate_id)
            if selected is None:
                recovered, recovery_reason = choose_recovery_candidate(recovery_pool)
                if recovered is None:
                    action, reason = fallback_wait(state.decision_state, "advisor_invalid_candidate_no_recovery")
                    state.mark_fallback(reason, action)
                    state.selected_candidate_id = result.selected_candidate_id
                    state.debug["fallback_provenance"] = fallback_provenance(
                        source="advisor_tool",
                        reason=reason,
                        candidates=recovery_pool,
                        recovery_attempted=True,
                        recovery_failed_reason=recovery_reason,
                    )
                else:
                    state.selected_candidate_id = recovered.candidate_id
                    state.selected_candidate = recovered
                    state.advisor_result = {
                        "selected_candidate_id": recovered.candidate_id,
                        "reason": f"deterministic recovery after unknown candidate: {recovery_reason}",
                        "accepted_risks": [],
                        "advisor_unknown_candidate": True,
                        "unknown_candidate_id": result.selected_candidate_id,
                        "unknown_candidate_reason": result.reason,
                        "executable_candidate_count_when_unknown": len(executable),
                        "profitable_order_existed_when_unknown": any(
                            c.action == "take_order" and (_fact_float(c, "estimated_net_after_penalty") or _fact_float(c, "estimated_net") or 0.0) > 0
                            for c in executable
                        ),
                        "recovery_used": True,
                        "recovery_reason": recovery_reason,
                        **recovery_candidate_summary(recovered),
                    }
            else:
                state.advisor_result = {
                    "selected_candidate_id": result.selected_candidate_id,
                    "reason": result.reason,
                    "accepted_risks": list(result.accepted_risks),
                    "advisor_unknown_candidate": not result.candidate_known,
                    "unknown_candidate_id": None,
                    "recovery_used": False,
                    "used_opportunity_signal": result.used_opportunity_signal,
                    "opportunity_reason": result.opportunity_reason,
                    "why_not_best_long_term_candidate": result.why_not_best_long_term_candidate,
                    "wait_opportunity_cost_accepted_reason": result.wait_opportunity_cost_accepted_reason,
                }
                state.selected_candidate_id = result.selected_candidate_id
                state.selected_candidate = selected
        summary = self.summarize_advisor_result(state)
        state.tool_summaries["advisor_tool"] = summary
        state.debug["advisor_summary"] = summary
        return state

    def summarize_advisor_result(self, state: AgentState) -> dict[str, Any]:
        selected = state.selected_candidate
        opportunity_summary = state.debug.get("advisor_opportunity_summary", state.debug.get("opportunity_summary", {})) or {}
        best_long_term = _safe_float_or_none(opportunity_summary.get("best_long_term_score_hint"))
        selected_long_term = _fact_float(selected, "long_term_score_hint")
        return {
            "selected_candidate_id": state.selected_candidate_id,
            "selected_candidate_source": selected.source if selected else None,
            "selected_candidate_action": selected.action if selected else None,
            "selected_candidate_estimated_net": _fact_float(selected, "estimated_net"),
            "selected_candidate_penalty_exposure": _fact_float(selected, "estimated_penalty_exposure"),
            "selected_candidate_estimated_net_after_penalty": _fact_float(selected, "estimated_net_after_penalty"),
            "advisor_reason": state.advisor_result.get("reason"),
            "used_opportunity_signal": bool(state.advisor_result.get("used_opportunity_signal")),
            "opportunity_reason": state.advisor_result.get("opportunity_reason"),
            "why_not_best_long_term_candidate": state.advisor_result.get("why_not_best_long_term_candidate"),
            "wait_opportunity_cost_accepted_reason": state.advisor_result.get("wait_opportunity_cost_accepted_reason"),
            "advisor_unknown_candidate": bool(state.advisor_result.get("advisor_unknown_candidate")),
            "unknown_candidate_id": state.advisor_result.get("unknown_candidate_id"),
            "advisor_no_result": bool(state.advisor_result.get("advisor_no_result")),
            "recovery_used": bool(state.advisor_result.get("recovery_used")),
            "recovery_reason": state.advisor_result.get("recovery_reason"),
            "recovery_candidate_id": state.advisor_result.get("recovery_candidate_id"),
            "recovery_candidate_action": state.advisor_result.get("recovery_candidate_action"),
            "recovery_candidate_estimated_net": state.advisor_result.get("recovery_candidate_estimated_net"),
            "recovery_candidate_long_term_score": state.advisor_result.get("recovery_candidate_long_term_score"),
            "executable_candidate_count_when_unknown": state.advisor_result.get("executable_candidate_count_when_unknown"),
            "profitable_order_existed_when_unknown": bool(state.advisor_result.get("profitable_order_existed_when_unknown")),
            "candidate_count_sent_to_advisor": state.advisor_context.get("candidate_count", 0),
            "executable_candidate_count": state.advisor_context.get("executable_candidate_count", 0),
            "decision_core_filtered_candidate_count": state.advisor_context.get("decision_core_filtered_candidate_count", 0),
            "decision_core_top_candidate_ids": state.advisor_context.get("decision_core_top_candidate_ids", []),
            "day_plan_primary_goal": (state.advisor_context.get("day_plan") or {}).get("primary_goal"),
            "day_plan_guidance_count": len((state.advisor_context.get("day_plan") or {}).get("advisor_guidance") or []),
            "day_plan_risk_focus_count": len((state.advisor_context.get("day_plan") or {}).get("risk_focus") or []),
            "day_plan_language": (state.advisor_context.get("day_plan") or {}).get("language"),
            "active_reflection_hint_count": state.advisor_context.get("active_reflection_hint_count", 0),
            "reflection_hint_failure_types": _reflection_failure_types(state),
            "reflection_hint_priorities": _reflection_priorities(state),
            "opportunity_facts_count": state.advisor_context.get("opportunity_facts_count", 0),
            "selected_candidate_long_term_score_hint": selected_long_term,
            "selected_candidate_decision_score": _fact_float(selected, "decision_score"),
            "selected_candidate_net_after_expected_penalty_per_hour": _fact_float(selected, "net_after_expected_penalty_per_hour"),
            "selected_candidate_wait_allowed": selected.facts.get("wait_allowed") if selected else None,
            "selected_candidate_wait_gate_reason": selected.facts.get("wait_gate_reason") if selected else None,
            "selected_candidate_wait_opportunity_cost": _fact_float(selected, "wait_opportunity_cost"),
            "selected_candidate_destination_opportunity_score": _fact_float(selected, "destination_opportunity_score"),
            "best_long_term_score_hint": best_long_term,
            "best_long_term_candidate_id": opportunity_summary.get("best_long_term_candidate_id"),
            "best_long_term_candidate_selectable": bool(opportunity_summary.get("best_long_term_candidate_selectable", True)),
            "selected_vs_best_long_term_gap": round(best_long_term - selected_long_term, 2)
            if best_long_term is not None and selected_long_term is not None else None,
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


def _advisor_visible_candidates(state: AgentState) -> tuple[list[Candidate], list[Candidate]]:
    executable = _executable_candidates(state)
    if not executable:
        return [], []
    summary = state.debug.get("advisor_opportunity_summary", state.debug.get("opportunity_summary", {})) or {}
    top_ids = [str(candidate_id) for candidate_id in summary.get("advisor_top_candidate_ids") or [] if candidate_id]
    if not top_ids:
        top_ids = _ranked_top_ids(executable)
    selected_ids = set(top_ids)
    valid = [candidate for candidate in state.valid_candidates if candidate.candidate_id in selected_ids]
    soft = [candidate for candidate in state.soft_risk_candidates if candidate.candidate_id in selected_ids]
    if valid or soft:
        return valid, soft
    return state.valid_candidates[:3], state.soft_risk_candidates[:3]


def _executable_candidates(state: AgentState) -> list[Candidate]:
    return state.executable_candidates or (state.valid_candidates + state.soft_risk_candidates)


def _ranked_top_ids(candidates: list[Candidate], limit: int = 7) -> list[str]:
    def score(candidate: Candidate) -> float:
        value = _fact_float(candidate, "decision_score")
        if value is None:
            value = _fact_float(candidate, "long_term_score_hint")
        if value is None:
            value = _fact_float(candidate, "estimated_net_after_penalty")
        return float(value if value is not None else -10**9)

    ordered = sorted(candidates, key=score, reverse=True)
    selected: list[str] = []
    counts: dict[str, int] = {}
    limits = {"take_order": 3, "wait": 1, "reposition": 2}
    for candidate in ordered:
        action = candidate.action
        if counts.get(action, 0) >= limits.get(action, 1):
            continue
        if action == "wait" and candidate.facts.get("wait_allowed") is False:
            continue
        selected.append(candidate.candidate_id)
        counts[action] = counts.get(action, 0) + 1
        if len(selected) >= limit:
            break
    if not selected:
        selected = [candidate.candidate_id for candidate in ordered[:limit]]
    return selected


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


def _safe_float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _reflection_failure_types(state: AgentState) -> dict[str, int]:
    counts: dict[str, int] = {}
    for hint in (state.reflection_context or {}).get("hints") or []:
        if not isinstance(hint, dict):
            continue
        failure_type = str(hint.get("failure_type") or "")
        if failure_type:
            counts[failure_type] = counts.get(failure_type, 0) + 1
    return counts


def _reflection_priorities(state: AgentState) -> dict[str, int]:
    counts: dict[str, int] = {}
    for hint in (state.reflection_context or {}).get("hints") or []:
        if not isinstance(hint, dict):
            continue
        priority = str(hint.get("priority") or "")
        if priority:
            counts[priority] = counts.get(priority, 0) + 1
    return counts
