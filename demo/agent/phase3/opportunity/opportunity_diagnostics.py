from __future__ import annotations

from statistics import mean
from typing import Any

from agent.phase3.opportunity.opportunity_schema import CandidateOpportunityFacts, MarketSnapshot


def build_opportunity_summary(
    *,
    market: MarketSnapshot,
    facts: list[CandidateOpportunityFacts],
    selected_candidate_id: str | None = None,
) -> dict[str, Any]:
    long_term = [f.long_term_score_hint for f in facts if f.long_term_score_hint is not None]
    wait_costs = [f.wait_opportunity_cost for f in facts if f.wait_opportunity_cost is not None]
    high_cost_waits = [f for f in facts if f.action_type == "wait" and float(f.wait_opportunity_cost or 0.0) > 300.0]
    best = max(facts, key=lambda f: float(f.long_term_score_hint or -10**9), default=None)
    selected = next((f for f in facts if f.candidate_id == selected_candidate_id), None)
    gap = None
    if selected is not None and best is not None:
        gap = round(float(best.long_term_score_hint or 0.0) - float(selected.long_term_score_hint or 0.0), 2)
    return {
        "market_snapshot": market.to_dict(),
        "candidate_count_with_future_value": len(long_term),
        "wait_opportunity_cost_avg": round(mean(wait_costs), 2) if wait_costs else 0.0,
        "wait_opportunity_cost_sum": round(sum(float(v or 0.0) for v in wait_costs), 2),
        "high_cost_wait_count": len(high_cost_waits),
        "take_order_destination_value_avg": _avg_destination_value(facts),
        "selected_long_term_score_hint": selected.long_term_score_hint if selected else None,
        "best_long_term_score_hint": best.long_term_score_hint if best else None,
        "best_long_term_candidate_id": best.candidate_id if best else None,
        "selected_vs_best_long_term_gap": gap,
        "specific_cargo_watch_active_count": sum(
            1 for f in facts if f.target_cargo_visibility_status in {"unavailable", "partially_visible"}
        ),
        "target_cargo_unavailable_but_high_wait_cost_count": sum(
            1
            for f in high_cost_waits
            if f.target_cargo_visibility_status in {"unavailable", "partially_visible"}
        ),
        "top_candidates_by_long_term_score_hint": [
            {
                "candidate_id": f.candidate_id,
                "action": f.action_type,
                "long_term_score_hint": f.long_term_score_hint,
                "immediate_net": f.immediate_net,
                "wait_opportunity_cost": f.wait_opportunity_cost,
                "destination_opportunity_score": f.destination_opportunity_score,
                "future_constraint_risk": f.future_constraint_risk,
            }
            for f in sorted(facts, key=lambda item: float(item.long_term_score_hint or -10**9), reverse=True)[:5]
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
    }


def _avg_destination_value(facts: list[CandidateOpportunityFacts]) -> float:
    values = [
        float(f.destination_opportunity_score or 0.0)
        for f in facts
        if f.action_type == "take_order" and f.destination_opportunity_score is not None
    ]
    return round(mean(values), 3) if values else 0.0

