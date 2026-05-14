from __future__ import annotations

from collections import Counter
from typing import Any

from agent.agent_models import Candidate
from agent.phase3.agent_state import AgentState


def action_counts(candidates: list[Candidate]) -> dict[str, int]:
    return dict(Counter(c.action for c in candidates))


def hard_invalid_reason_counts(candidates: list[Candidate]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for candidate in candidates:
        counts.update(str(reason) for reason in candidate.hard_invalid_reasons)
    return dict(counts.most_common(10))


def sample_hard_invalid_candidates(candidates: list[Candidate], limit: int = 5) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for candidate in candidates[:limit]:
        samples.append({
            "candidate_id": candidate.candidate_id,
            "action": candidate.action,
            "source": candidate.source,
            "cargo_id": candidate.params.get("cargo_id"),
            "hard_invalid_reasons": list(candidate.hard_invalid_reasons),
            "pickup_arrival_minute": candidate.facts.get("pickup_arrival_minute"),
            "cargo_deadline_minute": candidate.facts.get("cargo_deadline_minute"),
            "deadline_source": candidate.facts.get("deadline_source"),
            "finish_minute": candidate.facts.get("finish_minute"),
        })
    return samples


def candidate_summary(state: AgentState) -> dict[str, Any]:
    satisfy_types = sorted({
        str(c.facts.get("satisfies_constraint_type") or c.facts.get("constraint_type") or "")
        for c in state.raw_candidates
        if c.source in {"constraint_satisfy", "goal_satisfy"}
    })
    goal_summary = state.debug.get("goal_summary", {})
    return {
        "raw_candidate_count": len(state.raw_candidates),
        "candidate_action_counts": action_counts(state.raw_candidates),
        "satisfy_candidate_types": [t for t in satisfy_types if t],
        "base_candidate_count": len(state.base_candidates),
        "goal_candidate_count": len(state.goal_candidates),
        "legacy_constraint_satisfy_candidate_count": len(state.legacy_satisfy_candidates),
        "active_goal_count": goal_summary.get("active_goal_count", len(state.active_goals)),
        "active_goal_types": goal_summary.get("active_goal_types", {}),
        "goal_materialization_failures": goal_summary.get("goal_materialization_failures", {}),
        "stuck_goal_count": goal_summary.get("stuck_goal_count", 0),
        "goal_candidate_urgency_counts": goal_summary.get("goal_candidate_urgency_counts", {}),
        "goal_candidate_must_do_now_count": goal_summary.get("goal_candidate_must_do_now_count", 0),
        "hold_candidate_generated_count": goal_summary.get("hold_candidate_generated_count", 0),
        "rest_not_urgent_count": goal_summary.get("rest_not_urgent_count", 0),
        "ordered_steps_regression_count": goal_summary.get("ordered_steps_regression_count", 0),
    }


def constraint_summary(state: AgentState) -> dict[str, Any]:
    return {
        "candidate_count": len(state.evaluated_candidates),
        "valid_count": len(state.valid_candidates),
        "soft_risk_count": len(state.soft_risk_candidates),
        "hard_invalid_count": len(state.hard_invalid_candidates),
        "hard_invalid_reason_counts": hard_invalid_reason_counts(state.hard_invalid_candidates),
    }


def final_decision_summary(state: AgentState) -> dict[str, Any]:
    selected_action = state.selected_candidate.action if state.selected_candidate is not None else None
    hard_reason_counts = hard_invalid_reason_counts(state.hard_invalid_candidates)
    constraint = state.debug.get("constraint_summary", {})
    advisor = state.debug.get("advisor_summary", {})
    safety = state.debug.get("safety_summary", {})
    diagnosis = state.debug.get("decision_diagnosis", {})
    day_plan = state.day_plan.to_advisor_context() if state.day_plan is not None else {}
    selected_facts = state.selected_candidate.facts if state.selected_candidate is not None else {}
    goal_summary = state.debug.get("goal_summary", {})
    reflection_summary = state.debug.get("reflection_summary", {})
    opportunity_summary = state.debug.get("opportunity_summary", {})
    return {
        "driver_id": state.driver_id,
        "step_id": state.step_id,
        "step": state.step_id,
        "current_time": state.current_time,
        "current_day": state.current_day,
        "day": state.current_day,
        "minute": state.current_time % 1440 if state.current_time is not None else None,
        "current_location": state.current_location,
        "visible_cargo_count": len(state.visible_cargo),
        "candidate_count": len(state.evaluated_candidates or state.raw_candidates),
        "valid_count": len(state.valid_candidates),
        "soft_risk_count": len(state.soft_risk_candidates),
        "hard_invalid_count": len(state.hard_invalid_candidates),
        "valid_order_count": constraint.get("valid_order_count"),
        "valid_profitable_order_count": constraint.get("valid_profitable_order_count"),
        "best_valid_order_id": constraint.get("best_valid_order_id"),
        "best_valid_order_net": constraint.get("best_valid_order_net"),
        "best_soft_risk_order_id": constraint.get("best_soft_risk_order_id"),
        "best_soft_risk_order_net_after_penalty": constraint.get("best_soft_risk_order_net_after_penalty"),
        "dominant_hard_invalid_reason": constraint.get("dominant_hard_invalid_reason"),
        "hard_invalid_reason_counts": hard_reason_counts,
        "top_hard_invalid_reasons": hard_reason_counts,
        "sample_hard_invalid_candidates": sample_hard_invalid_candidates(state.hard_invalid_candidates),
        "advisor_candidate_count": state.advisor_context.get("candidate_count", 0),
        "active_reflection_hint_count": state.advisor_context.get("active_reflection_hint_count", 0),
        "reflection_hints_used": state.advisor_context.get("active_reflection_hint_count", 0),
        "reflection_active_hint_count_after_update": reflection_summary.get("active_reflection_hint_count", 0),
        "reflection_hint_priorities": reflection_summary.get("reflection_hint_priorities", {}),
        "reflection_failure_types": reflection_summary.get("reflection_failure_types", {}),
        "reflection_new_failure_count": reflection_summary.get("new_failure_count", 0),
        "reflection_new_hint_count": reflection_summary.get("new_hint_count", 0),
        "reflection_new_failure_types": reflection_summary.get("new_failure_types", {}),
        "reflection_filtered_illegal_fields": reflection_summary.get("reflection_filtered_illegal_fields", 0),
        "opportunity_summary": opportunity_summary,
        "opportunity_facts_count": len(state.opportunity_facts),
        "candidate_count_with_future_value": opportunity_summary.get("candidate_count_with_future_value"),
        "wait_opportunity_cost_avg": opportunity_summary.get("wait_opportunity_cost_avg"),
        "wait_opportunity_cost_sum": opportunity_summary.get("wait_opportunity_cost_sum"),
        "high_cost_wait_count": opportunity_summary.get("high_cost_wait_count"),
        "take_order_destination_value_avg": opportunity_summary.get("take_order_destination_value_avg"),
        "specific_cargo_watch_active_count": opportunity_summary.get("specific_cargo_watch_active_count"),
        "target_cargo_unavailable_but_high_wait_cost_count": opportunity_summary.get("target_cargo_unavailable_but_high_wait_cost_count"),
        "active_goal_count": goal_summary.get("active_goal_count", len(state.active_goals)),
        "active_goal_types": goal_summary.get("active_goal_types", {}),
        "goal_candidate_count": goal_summary.get("goal_candidate_count", len(state.goal_candidates)),
        "goal_materialization_failures": goal_summary.get("goal_materialization_failures", {}),
        "goal_stuck_suspected_count": goal_summary.get("stuck_goal_count", 0),
        "goal_stuck_samples": goal_summary.get("stuck_goals", []),
        "goal_candidate_urgency_counts": goal_summary.get("goal_candidate_urgency_counts", {}),
        "goal_candidate_must_do_now_count": goal_summary.get("goal_candidate_must_do_now_count", 0),
        "hold_candidate_generated_count": goal_summary.get("hold_candidate_generated_count", 0),
        "rest_not_urgent_count": goal_summary.get("rest_not_urgent_count", 0),
        "ordered_steps_regression_count": goal_summary.get("ordered_steps_regression_count", 0),
        "day_plan_summary": day_plan.get("strategy_summary"),
        "day_plan_primary_goal": day_plan.get("primary_goal"),
        "day_plan_risk_focus": day_plan.get("risk_focus"),
        "day_plan_rest_strategy": day_plan.get("rest_strategy"),
        "day_plan_advisor_guidance": day_plan.get("advisor_guidance"),
        "day_plan_guidance_count": len(day_plan.get("advisor_guidance") or []),
        "day_plan_risk_focus_count": len(day_plan.get("risk_focus") or []),
        "day_plan_fallback_used": day_plan.get("fallback_used"),
        "day_plan_language": day_plan.get("language"),
        "day_plan_generated_this_step": state.day_plan_generated_this_step,
        "selected_candidate_id": state.selected_candidate_id,
        "selected_candidate_source": advisor.get("selected_candidate_source"),
        "selected_candidate_goal_id": selected_facts.get("goal_id"),
        "selected_candidate_goal_type": selected_facts.get("goal_type"),
        "selected_candidate_goal_step_index": selected_facts.get("step_index"),
        "selected_candidate_goal_step_type": selected_facts.get("step_type"),
        "selected_candidate_advances_goal": selected_facts.get("advances_goal"),
        "selected_candidate_goal_materialization_reason": selected_facts.get("materialization_reason"),
        "selected_candidate_goal_urgency": selected_facts.get("urgency"),
        "selected_candidate_must_do_now": selected_facts.get("must_do_now"),
        "selected_candidate_penalty_at_risk": selected_facts.get("penalty_at_risk"),
        "selected_candidate_opportunity_cost_hint": selected_facts.get("opportunity_cost_hint"),
        "selected_candidate_long_term_score_hint": selected_facts.get("long_term_score_hint"),
        "selected_candidate_wait_opportunity_cost": selected_facts.get("wait_opportunity_cost"),
        "selected_candidate_destination_opportunity_score": selected_facts.get("destination_opportunity_score"),
        "selected_candidate_future_value_estimate": selected_facts.get("future_value_estimate"),
        "selected_candidate_future_constraint_risk": selected_facts.get("future_constraint_risk"),
        "selected_candidate_cargo_watch_hint": selected_facts.get("cargo_watch_hint"),
        "selected_candidate_target_cargo_visibility_status": selected_facts.get("target_cargo_visibility_status"),
        "best_long_term_candidate_id": advisor.get("best_long_term_candidate_id"),
        "best_long_term_score_hint": advisor.get("best_long_term_score_hint"),
        "selected_vs_best_long_term_gap": advisor.get("selected_vs_best_long_term_gap"),
        "selected_action": selected_action,
        "selected_candidate_action": advisor.get("selected_candidate_action") or selected_action,
        "selected_candidate_estimated_net": advisor.get("selected_candidate_estimated_net"),
        "selected_candidate_penalty_exposure": advisor.get("selected_candidate_penalty_exposure"),
        "selected_candidate_estimated_net_after_penalty": advisor.get("selected_candidate_estimated_net_after_penalty"),
        "selected_reason": state.advisor_result.get("reason"),
        "advisor_reason": advisor.get("advisor_reason") or state.advisor_result.get("reason"),
        "used_opportunity_signal": bool(state.advisor_result.get("used_opportunity_signal")),
        "opportunity_reason": state.advisor_result.get("opportunity_reason"),
        "why_not_best_long_term_candidate": state.advisor_result.get("why_not_best_long_term_candidate"),
        "wait_opportunity_cost_accepted_reason": state.advisor_result.get("wait_opportunity_cost_accepted_reason"),
        "safety_passed": state.safety_result.get("accepted"),
        "safety_accepted": state.safety_result.get("accepted"),
        "safety_rejected": safety.get("safety_rejected"),
        "safety_reject_reason": safety.get("safety_reject_reason"),
        "fallback_used": state.fallback_used,
        "fallback_reason": state.fallback_reason,
        "final_action": state.final_action,
        "diagnosis": diagnosis,
    }
