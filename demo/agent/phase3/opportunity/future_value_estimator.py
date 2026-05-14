from __future__ import annotations

from typing import Any

from agent.agent_models import Candidate
from agent.phase3.opportunity.opportunity_schema import CandidateOpportunityFacts, MarketSnapshot


class FutureValueEstimator:
    def estimate(
        self,
        candidate: Candidate,
        market: MarketSnapshot,
        wait_facts: dict[str, object],
        destination_facts: dict[str, object],
    ) -> CandidateOpportunityFacts:
        immediate_net = _fact_float(candidate, "estimated_net_after_penalty")
        if immediate_net is None:
            immediate_net = _fact_float(candidate, "estimated_net")
        destination_score = _safe_float(destination_facts.get("destination_opportunity_score"))
        wait_cost = _optional_float(wait_facts.get("wait_opportunity_cost"))
        risk = _future_constraint_risk(candidate, market)
        risk_cost = _risk_cost(risk)
        future_value = round(destination_score * 500.0 - risk_cost, 2)
        base_net = float(immediate_net or 0.0)
        wait_penalty = float(wait_cost or 0.0)
        long_term_score = round(base_net + future_value - wait_penalty, 2)
        return CandidateOpportunityFacts(
            candidate_id=candidate.candidate_id,
            action_type=candidate.action,
            immediate_net=round(base_net, 2),
            destination_opportunity_score=_optional_float(destination_facts.get("destination_opportunity_score")),
            destination_visible_cargo_count=_optional_int(destination_facts.get("destination_visible_cargo_count")),
            destination_avg_nearby_order_net=_optional_float(destination_facts.get("destination_avg_nearby_order_net")),
            wait_opportunity_cost=wait_cost,
            best_forgone_order_id=_optional_str(wait_facts.get("best_forgone_order_id")),
            best_forgone_order_net=_optional_float(wait_facts.get("best_forgone_order_net")),
            profitable_order_count=_optional_int(wait_facts.get("profitable_order_count")),
            future_constraint_risk=risk,
            future_value_estimate=future_value,
            long_term_score_hint=long_term_score,
            target_cargo_visibility_status=market.target_cargo_visibility_status,
            specific_cargo_wait_cost=_specific_cargo_wait_cost(candidate, market, wait_cost),
            specific_cargo_blocked_by_current_action_risk=_specific_cargo_action_risk(candidate, market),
            cargo_watch_hint=_cargo_watch_hint(candidate, market),
            explanation=_explanation(candidate, wait_cost, destination_score, risk),
        )


def _future_constraint_risk(candidate: Candidate, market: MarketSnapshot) -> str:
    urgency = str(candidate.facts.get("urgency") or "")
    if candidate.facts.get("must_do_now") or urgency == "critical":
        return "critical_goal"
    if candidate.action == "wait" and market.profitable_cargo_count > 0:
        return "market_opportunity_decay"
    if market.target_cargo_visibility_status == "unavailable" and candidate.action in {"take_order", "reposition"}:
        return "target_cargo_watch_risk"
    if candidate.soft_risk_reasons:
        return "soft_preference_risk"
    return "low"


def _risk_cost(risk: str) -> float:
    return {
        "critical_goal": 0.0,
        "low": 0.0,
        "soft_preference_risk": 150.0,
        "market_opportunity_decay": 200.0,
        "target_cargo_watch_risk": 250.0,
    }.get(risk, 100.0)


def _specific_cargo_wait_cost(candidate: Candidate, market: MarketSnapshot, wait_cost: float | None) -> float | None:
    if market.target_cargo_visibility_status != "unavailable":
        return None
    if candidate.action != "wait":
        return None
    return round(float(wait_cost or 0.0), 2)


def _specific_cargo_action_risk(candidate: Candidate, market: MarketSnapshot) -> str | None:
    if market.target_cargo_visibility_status != "unavailable":
        return None
    if candidate.action == "take_order":
        return "taking_order_may_delay_future_target_cargo_attempt"
    if candidate.action == "reposition":
        return "reposition_may_help_or_hurt_future_target_cargo_attempt"
    if candidate.action == "wait":
        return "waiting_preserves_current_position_but_has_market_cost"
    return None


def _cargo_watch_hint(candidate: Candidate, market: MarketSnapshot) -> str | None:
    if market.target_cargo_visibility_status not in {"unavailable", "partially_visible"}:
        return None
    if candidate.action == "wait":
        return "target cargo is not currently visible; compare wait cost with target penalty risk"
    if candidate.action == "take_order":
        return "target cargo is not currently visible; order choice should justify delaying target watch"
    if candidate.action == "reposition":
        return "target cargo is not currently visible; reposition should preserve future optionality"
    return None


def _explanation(candidate: Candidate, wait_cost: float | None, destination_score: float, risk: str) -> str:
    if candidate.action == "wait":
        return f"wait_cost={round(float(wait_cost or 0.0), 2)}, risk={risk}"
    return f"destination_score={round(destination_score, 3)}, risk={risk}"


def _fact_float(candidate: Candidate, key: str) -> float | None:
    try:
        value = candidate.facts.get(key)
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None

