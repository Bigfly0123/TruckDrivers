from __future__ import annotations

from typing import Any

from agent.phase3.agent_state import AgentState


class DiagnosticTool:
    """Builds diagnostic facts only. It does not make decisions."""

    def build_decision_diagnosis(self, state: AgentState) -> dict[str, Any]:
        constraint = state.debug.get("constraint_summary", {})
        advisor = state.debug.get("advisor_summary", {})
        safety = state.debug.get("safety_summary", {})
        goal_summary = state.debug.get("goal_summary", {})
        reflection_summary = state.debug.get("reflection_summary", {})
        opportunity_summary = state.debug.get("opportunity_summary", {})
        selected_action = advisor.get("selected_candidate_action")
        selected_facts = state.selected_candidate.facts if state.selected_candidate is not None else {}
        final_action_name = (state.final_action or {}).get("action")
        selected_is_wait = selected_action == "wait" or final_action_name == "wait"
        has_profitable = int(constraint.get("valid_profitable_order_count") or 0) > 0
        selected_is_rest = selected_facts.get("goal_type") == "continuous_rest" and selected_is_wait
        best_net = constraint.get("best_valid_order_net")
        selected_net = advisor.get("selected_candidate_estimated_net")
        gap = None
        if best_net is not None and selected_net is not None:
            gap = float(best_net) - float(selected_net)
        diagnosis = {
            "decision_type": final_action_name or selected_action,
            "selected_is_order": selected_action == "take_order" or final_action_name == "take_order",
            "selected_is_wait": selected_is_wait,
            "selected_is_reposition": selected_action == "reposition" or final_action_name == "reposition",
            "why_no_order_selected": _why_no_order_selected(state, constraint, selected_is_wait),
            "why_wait_selected": _why_wait_selected(state, constraint, selected_is_wait),
            "why_fallback_used": state.fallback_reason if state.fallback_used else None,
            "has_valid_profitable_order": has_profitable,
            "best_valid_order_id": constraint.get("best_valid_order_id"),
            "best_valid_order_net": best_net,
            "selected_candidate_id": state.selected_candidate_id,
            "selected_candidate_net": selected_net,
            "selected_vs_best_valid_net_gap": gap,
            "dominant_hard_invalid_reason": constraint.get("dominant_hard_invalid_reason"),
            "hard_invalid_reason_counts": constraint.get("hard_invalid_reason_counts", {}),
            "advisor_chose_wait_despite_profitable_order": bool(selected_is_wait and has_profitable and not state.fallback_used),
            "safety_rejected_advisor_choice": bool(safety.get("safety_rejected") and state.fallback_used),
            "candidate_pool_empty": len(state.evaluated_candidates or state.raw_candidates) == 0,
            "only_wait_candidates_available": _only_wait_candidates_available(state),
            "active_goal_count": goal_summary.get("active_goal_count", 0),
            "goal_candidate_count": goal_summary.get("goal_candidate_count", 0),
            "goal_materialization_failures": goal_summary.get("goal_materialization_failures", {}),
            "stuck_goal_count": goal_summary.get("stuck_goal_count", 0),
            "goal_candidate_urgency_counts": goal_summary.get("goal_candidate_urgency_counts", {}),
            "goal_candidate_must_do_now_count": goal_summary.get("goal_candidate_must_do_now_count", 0),
            "hold_candidate_generated_count": goal_summary.get("hold_candidate_generated_count", 0),
            "rest_not_urgent_count": goal_summary.get("rest_not_urgent_count", 0),
            "ordered_steps_regression_count": goal_summary.get("ordered_steps_regression_count", 0),
            "selected_candidate_advances_goal": bool(selected_facts.get("advances_goal")),
            "selected_candidate_goal_id": selected_facts.get("goal_id"),
            "selected_candidate_goal_type": selected_facts.get("goal_type"),
            "selected_candidate_goal_urgency": selected_facts.get("urgency"),
            "selected_candidate_must_do_now": selected_facts.get("must_do_now"),
            "profitable_valid_order_but_selected_rest": bool(selected_is_rest and has_profitable and not state.fallback_used),
            "rest_opportunity_cost": float(best_net or 0) if selected_is_rest and has_profitable else 0.0,
            "active_reflection_hint_count": reflection_summary.get("active_reflection_hint_count", 0),
            "reflection_failure_types": reflection_summary.get("reflection_failure_types", {}),
            "wait_reason_category": _wait_reason_category(state, constraint, selected_facts, selected_is_wait),
            "selected_candidate_wait_opportunity_cost": selected_facts.get("wait_opportunity_cost"),
            "selected_candidate_long_term_score_hint": selected_facts.get("long_term_score_hint"),
            "best_long_term_candidate_id": opportunity_summary.get("best_long_term_candidate_id"),
            "best_long_term_score_hint": opportunity_summary.get("best_long_term_score_hint"),
            "selected_vs_best_long_term_gap": advisor.get("selected_vs_best_long_term_gap"),
            "advisor_ignored_best_long_term": _advisor_ignored_best_long_term(state, advisor, opportunity_summary),
            "high_cost_wait_selected": bool(selected_is_wait and float(selected_facts.get("wait_opportunity_cost") or 0.0) > 300.0),
            "target_cargo_unavailable_but_high_wait_cost": bool(
                selected_is_wait
                and selected_facts.get("target_cargo_visibility_status") in {"unavailable", "partially_visible"}
                and float(selected_facts.get("wait_opportunity_cost") or 0.0) > 300.0
            ),
        }
        state.diagnostics["decision_diagnosis"] = diagnosis
        state.debug["decision_diagnosis"] = diagnosis
        state.tool_summaries["diagnostic_tool"] = diagnosis
        return diagnosis


def _why_no_order_selected(state: AgentState, constraint: dict[str, Any], selected_is_wait: bool) -> str | None:
    if state.fallback_used:
        return "fallback_used"
    if not selected_is_wait:
        return None
    if int(constraint.get("valid_order_count") or 0) == 0:
        return "no_valid_order"
    if int(constraint.get("valid_profitable_order_count") or 0) == 0:
        return "no_profitable_valid_order"
    return "advisor_selected_wait_despite_profitable_order"


def _why_wait_selected(state: AgentState, constraint: dict[str, Any], selected_is_wait: bool) -> str | None:
    if not selected_is_wait:
        return None
    if state.fallback_used:
        return state.fallback_reason
    if int(constraint.get("valid_profitable_order_count") or 0) == 0:
        return "no_profitable_valid_order"
    return "advisor_tradeoff_or_prompt_behavior"


def _wait_reason_category(
    state: AgentState,
    constraint: dict[str, Any],
    selected_facts: dict[str, Any],
    selected_is_wait: bool,
) -> str | None:
    if not selected_is_wait:
        return None
    if state.fallback_used:
        return "fallback_wait"
    if selected_facts.get("satisfies_constraint_type") == "forbid_action_in_time_window":
        return "forbid_window_wait"
    if selected_facts.get("satisfies_constraint_type") == "continuous_rest":
        return "rest_required_wait"
    if selected_facts.get("must_do_now") or selected_facts.get("urgency") == "critical":
        return "critical_goal_wait"
    if int(constraint.get("valid_order_count") or 0) == 0:
        return "no_valid_order"
    if int(constraint.get("valid_profitable_order_count") or 0) > 0:
        return "profitable_order_but_wait"
    if selected_facts.get("goal_id"):
        return "dayplan_or_goal_wait"
    return "unknown_wait"


def _advisor_ignored_best_long_term(
    state: AgentState,
    advisor: dict[str, Any],
    opportunity_summary: dict[str, Any],
) -> bool:
    best_id = str(opportunity_summary.get("best_long_term_candidate_id") or "")
    selected_id = str(state.selected_candidate_id or "")
    if not best_id or best_id == selected_id:
        return False
    try:
        gap = float(advisor.get("selected_vs_best_long_term_gap") or 0.0)
    except (TypeError, ValueError):
        return False
    return gap > 300.0


def _only_wait_candidates_available(state: AgentState) -> bool:
    executable = state.valid_candidates + state.soft_risk_candidates
    return bool(executable) and all(c.action == "wait" for c in executable)
