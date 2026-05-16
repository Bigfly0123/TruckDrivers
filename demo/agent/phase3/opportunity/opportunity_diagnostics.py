from __future__ import annotations

from statistics import mean
from typing import Any

from agent.phase3.opportunity.opportunity_schema import CandidateOpportunityFacts, MarketSnapshot


def build_advisor_opportunity_summary(
    *,
    market: MarketSnapshot,
    facts: list[CandidateOpportunityFacts],
    executable_ids: set[str],
    selected_candidate_id: str | None = None,
) -> dict[str, Any]:
    executable = [f for f in facts if f.candidate_id in executable_ids]
    long_term = [f.long_term_score_hint for f in executable if f.long_term_score_hint is not None]
    wait_costs = [f.wait_opportunity_cost for f in executable if f.wait_opportunity_cost is not None]
    high_cost_waits = [f for f in executable if f.action_type == "wait" and float(f.wait_opportunity_cost or 0.0) > 300.0]
    best = max(executable, key=lambda f: float(f.long_term_score_hint or -10**9), default=None)
    best_decision = max(executable, key=lambda f: float(f.decision_score or -10**9), default=None)
    advisor_top = _advisor_top_candidates(executable)
    selected = next((f for f in executable if f.candidate_id == selected_candidate_id), None)
    gap = None
    if selected is not None and best is not None:
        gap = round(float(best.long_term_score_hint or 0.0) - float(selected.long_term_score_hint or 0.0), 2)
    return {
        "market_snapshot": market.to_dict(),
        "executable_candidate_count": len(executable),
        "candidate_count_with_future_value": len(long_term),
        "wait_opportunity_cost_avg": round(mean(wait_costs), 2) if wait_costs else 0.0,
        "wait_opportunity_cost_sum": round(sum(float(v or 0.0) for v in wait_costs), 2),
        "high_cost_wait_count": len(high_cost_waits),
        "take_order_destination_value_avg": _avg_destination_value(executable),
        "selected_long_term_score_hint": selected.long_term_score_hint if selected else None,
        "best_long_term_score_hint": best.long_term_score_hint if best else None,
        "best_long_term_candidate_id": best.candidate_id if best else None,
        "best_executable_long_term_candidate_id": best.candidate_id if best else None,
        "best_executable_long_term_score": best.long_term_score_hint if best else None,
        "best_executable_candidate_action": best.action_type if best else None,
        "best_executable_candidate_estimated_net": best.immediate_net if best else None,
        "best_executable_candidate_estimated_net_after_penalty": best.net_after_expected_penalty if best else None,
        "best_executable_candidate_wait_cost": best.wait_opportunity_cost if best else None,
        "best_long_term_candidate_selectable": bool(best is not None),
        "best_decision_candidate_id": best_decision.candidate_id if best_decision else None,
        "best_decision_score": best_decision.decision_score if best_decision else None,
        "best_decision_candidate_action": best_decision.action_type if best_decision else None,
        "advisor_top_candidate_ids": [f.candidate_id for f in advisor_top],
        "advisor_top_candidate_count": len(advisor_top),
        "wait_gate_blocked_count": sum(1 for f in executable if f.action_type == "wait" and f.wait_allowed is False),
        "wait_gate_allowed_count": sum(1 for f in executable if f.action_type == "wait" and f.wait_allowed is True),
        "top_executable_candidates_by_decision_score": [
            _candidate_brief(f) for f in sorted(
                executable,
                key=lambda item: float(item.decision_score or -10**9),
                reverse=True,
            )[:5]
        ],
        "selected_vs_best_long_term_gap": gap,
        "specific_cargo_watch_active_count": sum(
            1 for f in executable if f.target_cargo_visibility_status in {"unavailable", "partially_visible"}
        ),
        "target_cargo_unavailable_but_high_wait_cost_count": sum(
            1
            for f in high_cost_waits
            if f.target_cargo_visibility_status in {"unavailable", "partially_visible"}
        ),
        "top_executable_candidates_by_long_term_score": [
            {
                "candidate_id": f.candidate_id,
                "action": f.action_type,
                "long_term_score_hint": f.long_term_score_hint,
                "immediate_net": f.immediate_net,
                "net_after_decision_penalty": f.net_after_decision_penalty,
                "wait_opportunity_cost": f.wait_opportunity_cost,
                "destination_opportunity_score": f.destination_opportunity_score,
                "future_constraint_risk": f.future_constraint_risk,
                "decision_score": f.decision_score,
                "wait_allowed": f.wait_allowed,
                "wait_gate_reason": f.wait_gate_reason,
                "net_after_expected_penalty_per_hour": f.net_after_expected_penalty_per_hour,
            }
            for f in sorted(executable, key=lambda item: float(item.long_term_score_hint or -10**9), reverse=True)[:5]
        ],
        "high_cost_wait_warnings": [
            {
                "candidate_id": f.candidate_id,
                "wait_opportunity_cost": f.wait_opportunity_cost,
                "best_forgone_order_id": f.best_forgone_order_id,
                "best_forgone_order_net": f.best_forgone_order_net,
                "cargo_watch_hint": f.cargo_watch_hint,
            }
            for f in high_cost_waits[:5]
        ],
        "non_selectable_candidate_id_exposed_to_advisor": False,
    }


def build_diagnostic_opportunity_summary(
    *,
    market: MarketSnapshot,
    facts: list[CandidateOpportunityFacts],
    executable_ids: set[str],
    hard_invalid_reasons_by_id: dict[str, tuple[str, ...]],
) -> dict[str, Any]:
    non_selectable = [f for f in facts if f.candidate_id not in executable_ids]
    high_value_hard = [
        f for f in non_selectable
        if f.action_type == "take_order" and float(f.long_term_score_hint or -10**9) > 0
    ]
    reason_counts: dict[str, int] = {}
    for candidate_id in {f.candidate_id for f in non_selectable}:
        for reason in hard_invalid_reasons_by_id.get(candidate_id, ()):
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return {
        "market_snapshot": market.to_dict(),
        "all_candidate_count": len(facts),
        "hard_invalid_candidate_count": len(non_selectable),
        "high_value_hard_invalid_count": len(high_value_hard),
        "top_non_selectable_candidate_reasons": dict(sorted(reason_counts.items(), key=lambda item: item[1], reverse=True)[:10]),
        "top_hard_invalid_by_long_term_score": [
            {
                "candidate_id": f.candidate_id,
                "action": f.action_type,
                "long_term_score_hint": f.long_term_score_hint,
                "immediate_net": f.immediate_net,
                "hard_invalid_reasons": list(hard_invalid_reasons_by_id.get(f.candidate_id, ())),
            }
            for f in sorted(non_selectable, key=lambda item: float(item.long_term_score_hint or -10**9), reverse=True)[:5]
        ],
        "non_selectable_candidate_id_exposed_to_advisor": False,
        "candidate_count_with_future_value": sum(1 for f in facts if f.long_term_score_hint is not None),
        "specific_cargo_watch_active_count": sum(
            1 for f in facts if f.target_cargo_visibility_status in {"unavailable", "partially_visible"}
        ),
    }


def _avg_destination_value(facts: list[CandidateOpportunityFacts]) -> float:
    values = [
        float(f.destination_opportunity_score or 0.0)
        for f in facts
        if f.action_type == "take_order" and f.destination_opportunity_score is not None
    ]
    return round(mean(values), 3) if values else 0.0


def _advisor_top_candidates(facts: list[CandidateOpportunityFacts]) -> list[CandidateOpportunityFacts]:
    selected: list[CandidateOpportunityFacts] = []
    selected_ids: set[str] = set()
    selectable = [f for f in facts if not (f.action_type == "wait" and f.wait_allowed is False)]

    def add(items: list[CandidateOpportunityFacts], limit: int) -> None:
        for fact in items:
            if len([f for f in selected if f.action_type == fact.action_type]) >= limit:
                break
            if fact.candidate_id in selected_ids:
                continue
            selected.append(fact)
            selected_ids.add(fact.candidate_id)

    ordered = sorted(selectable, key=lambda item: float(item.decision_score or -10**9), reverse=True)
    best_order_score = max(
        (float(f.decision_score or -10**9) for f in ordered if f.action_type == "take_order"),
        default=-10**9,
    )
    critical = [
        f for f in ordered
        if f.goal_progress_delta and float(f.goal_progress_delta or 0.0) >= 500.0
        and float(f.decision_score or -10**9) >= max(0.0, best_order_score * 0.75)
    ][:2]
    for fact in critical:
        if fact.candidate_id not in selected_ids:
            selected.append(fact)
            selected_ids.add(fact.candidate_id)
    add([f for f in ordered if f.action_type == "take_order"], 3)
    allowed_waits = [f for f in ordered if f.action_type == "wait" and f.wait_allowed is not False]
    add(allowed_waits, 1)
    add([f for f in ordered if f.action_type == "reposition"], 2)
    for fact in ordered:
        if len(selected) >= 7:
            break
        if fact.candidate_id in selected_ids:
            continue
        selected.append(fact)
        selected_ids.add(fact.candidate_id)
    return sorted(selected, key=lambda item: float(item.decision_score or -10**9), reverse=True)[:7]


def _candidate_brief(f: CandidateOpportunityFacts) -> dict[str, Any]:
    return {
        "candidate_id": f.candidate_id,
        "action": f.action_type,
        "decision_score": f.decision_score,
        "net_after_expected_penalty": f.net_after_expected_penalty,
        "net_after_decision_penalty": f.net_after_decision_penalty,
        "net_after_expected_penalty_per_hour": f.net_after_expected_penalty_per_hour,
        "duration_minutes": f.duration_minutes,
        "goal_progress_delta": f.goal_progress_delta,
        "wait_allowed": f.wait_allowed,
        "wait_gate_reason": f.wait_gate_reason,
        "wait_opportunity_cost": f.wait_opportunity_cost,
    }
