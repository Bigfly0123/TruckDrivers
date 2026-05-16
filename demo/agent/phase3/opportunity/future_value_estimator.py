from __future__ import annotations

from typing import Any

from agent.phase3.domain.agent_models import Candidate
from agent.phase3.opportunity.opportunity_schema import CandidateOpportunityFacts, MarketSnapshot

DEFAULT_DECISION_PENALTY_WEIGHT = 0.25


class FutureValueEstimator:
    def estimate(
        self,
        candidate: Candidate,
        market: MarketSnapshot,
        wait_facts: dict[str, object],
        destination_facts: dict[str, object],
    ) -> CandidateOpportunityFacts:
        immediate_net = _fact_float(candidate, "estimated_net") or 0.0
        expected_penalty = _fact_float(candidate, "marginal_penalty_exposure")
        if expected_penalty is None:
            expected_penalty = _fact_float(candidate, "estimated_penalty_exposure")
        expected_penalty = expected_penalty or 0.0
        net_after_penalty = _fact_float(candidate, "estimated_net_after_marginal_penalty")
        if net_after_penalty is None:
            net_after_penalty = _fact_float(candidate, "estimated_net_after_penalty")
        if net_after_penalty is None:
            net_after_penalty = float(immediate_net) - expected_penalty
        penalty_weight = _penalty_weight(candidate)
        decision_penalty_cost = round(float(expected_penalty) * penalty_weight, 2)
        net_after_decision_penalty = _fact_float(candidate, "estimated_net_after_decision_penalty")
        if net_after_decision_penalty is None:
            net_after_decision_penalty = float(immediate_net) - decision_penalty_cost
        base_net = float(net_after_decision_penalty or 0.0)
        destination_score = max(
            _safe_float(destination_facts.get("destination_opportunity_score")),
            _safe_float(candidate.facts.get("market_probe_score")),
        )
        wait_cost = _optional_float(wait_facts.get("wait_opportunity_cost"))
        duration = _duration_minutes(candidate)
        rate = _per_hour(net_after_decision_penalty, duration)
        best_alternative_net = _best_available_net(market)
        best_alternative_rate = _per_hour(best_alternative_net, 60)
        wait_gate = _wait_gate(candidate, market, wait_cost, best_alternative_rate)
        progress_delta = _goal_progress_delta(candidate)
        risk = _future_constraint_risk(candidate, market)
        risk_cost = _risk_cost(risk)
        future_value = round(destination_score * 500.0 - risk_cost, 2)
        wait_penalty = float(wait_cost or 0.0)
        idle_wait_penalty = _idle_wait_penalty(candidate, wait_gate["wait_expected_progress"], market)
        action_opportunity_cost = _action_opportunity_cost(candidate, best_alternative_net)
        long_term_score = round(base_net + future_value - wait_penalty - idle_wait_penalty - action_opportunity_cost + progress_delta, 2)
        decision_score = _decision_score(
            candidate=candidate,
            net_after_penalty=net_after_decision_penalty,
            rate=rate,
            future_value=future_value,
            wait_cost=wait_penalty,
            idle_wait_penalty=idle_wait_penalty,
            action_opportunity_cost=action_opportunity_cost,
            progress_delta=progress_delta,
            wait_allowed=wait_gate["wait_allowed"],
            best_alternative_net=best_alternative_net,
        )
        return CandidateOpportunityFacts(
            candidate_id=candidate.candidate_id,
            action_type=candidate.action,
            immediate_net=round(float(immediate_net), 2),
            expected_penalty=round(expected_penalty, 2),
            decision_penalty_weight=round(penalty_weight, 3),
            decision_penalty_cost=round(decision_penalty_cost, 2),
            net_after_decision_penalty=round(net_after_decision_penalty, 2),
            net_after_expected_penalty=round(net_after_penalty, 2),
            duration_minutes=duration,
            net_after_expected_penalty_per_hour=round(rate, 2),
            destination_opportunity_score=_optional_float(destination_facts.get("destination_opportunity_score")),
            destination_visible_cargo_count=_optional_int(destination_facts.get("destination_visible_cargo_count")),
            destination_avg_nearby_order_net=_optional_float(destination_facts.get("destination_avg_nearby_order_net")),
            wait_opportunity_cost=wait_cost,
            best_alternative_rate=round(best_alternative_rate, 2) if best_alternative_rate > 0 else None,
            best_forgone_order_id=_optional_str(wait_facts.get("best_forgone_order_id")),
            best_forgone_order_net=_optional_float(wait_facts.get("best_forgone_order_net")),
            profitable_order_count=_optional_int(wait_facts.get("profitable_order_count")),
            wait_allowed=wait_gate["wait_allowed"],
            wait_gate_reason=wait_gate["wait_gate_reason"],
            wait_expected_progress=wait_gate["wait_expected_progress"],
            goal_progress_delta=round(progress_delta, 2),
            decision_score=decision_score,
            decision_score_reason=_decision_reason(candidate, wait_gate["wait_gate_reason"]),
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
    if candidate.source == "market_probe":
        return "market_exploration"
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
        "market_exploration": 50.0,
    }.get(risk, 100.0)


def _duration_minutes(candidate: Candidate) -> int:
    if candidate.action == "wait":
        return _safe_int(candidate.params.get("duration_minutes") or candidate.facts.get("duration_minutes"), 60)
    if candidate.action == "take_order":
        finish = _fact_float(candidate, "finish_minute")
        current = _safe_float(candidate.facts.get("current_minute"))
        if finish is not None and current > 0 and finish > current:
            return max(1, int(round(finish - current)))
        pickup = _safe_int(candidate.facts.get("pickup_minutes"), 0)
        haul = _safe_int(candidate.facts.get("estimated_duration_minutes"), 60)
        return max(1, pickup + haul)
    return max(30, _safe_int(candidate.facts.get("estimated_duration_minutes"), 60))


def _per_hour(net: float, duration_minutes: int) -> float:
    hours = max(1.0 / 60.0, float(duration_minutes) / 60.0)
    return float(net) / hours


def _best_available_net(market: MarketSnapshot) -> float:
    return max(float(market.best_valid_order_net or 0.0), float(market.best_soft_risk_order_net_after_penalty or 0.0))


def _wait_gate(
    candidate: Candidate,
    market: MarketSnapshot,
    wait_cost: float | None,
    best_alternative_rate: float,
) -> dict[str, object]:
    if candidate.action != "wait":
        return {
            "wait_allowed": None,
            "wait_gate_reason": None,
            "wait_expected_progress": None,
        }
    expected_progress = _wait_expected_progress(candidate)
    reason = _wait_reason(candidate)
    urgency = str(candidate.facts.get("urgency") or "")
    must_do_now = bool(candidate.facts.get("must_do_now"))
    completes = bool(candidate.facts.get("actually_satisfies_after_this_wait"))
    wait_cost_value = float(wait_cost or 0.0)
    if must_do_now or urgency == "critical":
        return {"wait_allowed": True, "wait_gate_reason": "critical_goal_progress", "wait_expected_progress": expected_progress}
    if completes and expected_progress:
        return {"wait_allowed": True, "wait_gate_reason": "completes_goal_or_constraint", "wait_expected_progress": expected_progress}
    if expected_progress and urgency == "high" and wait_cost_value <= max(300.0, _penalty_at_risk(candidate)):
        return {"wait_allowed": True, "wait_gate_reason": "high_urgency_progress_with_bounded_cost", "wait_expected_progress": expected_progress}
    if market.profitable_cargo_count > 0 and best_alternative_rate > 100.0:
        return {"wait_allowed": False, "wait_gate_reason": "profitable_order_available", "wait_expected_progress": expected_progress}
    if not expected_progress and market.profitable_cargo_count > 0:
        return {"wait_allowed": False, "wait_gate_reason": "idle_wait_with_market_opportunity", "wait_expected_progress": expected_progress}
    return {"wait_allowed": True, "wait_gate_reason": "no_strong_alternative", "wait_expected_progress": expected_progress}


def _wait_expected_progress(candidate: Candidate) -> bool:
    if bool(candidate.facts.get("actually_satisfies_after_this_wait")):
        return True
    if bool(candidate.facts.get("wait_expected_progress")):
        return True
    if candidate.facts.get("satisfies_constraint_type") == "continuous_rest":
        return bool(candidate.facts.get("must_do_now") or candidate.facts.get("current_rest_streak_minutes"))
    if candidate.facts.get("goal_id") and candidate.facts.get("step_type") in {"hold_location_until_time", "stay_until_time", "stay_at_location"}:
        return True
    return False


def _wait_reason(candidate: Candidate) -> str:
    if candidate.facts.get("satisfies_constraint_type") == "forbid_action_in_time_window":
        return "forbid_window_wait"
    if candidate.facts.get("satisfies_constraint_type") == "continuous_rest":
        return "rest_progress_wait"
    if candidate.facts.get("step_type") == "hold_location_until_time":
        return "goal_hold_wait"
    if candidate.facts.get("goal_id"):
        return "goal_wait"
    if candidate.source == "system":
        return "market_wait"
    return "unknown_wait"


def _goal_progress_delta(candidate: Candidate) -> float:
    if candidate.facts.get("satisfies_constraint_type") == "forbid_action_in_time_window":
        return 0.0
    if not candidate.facts.get("advances_goal") and not candidate.facts.get("satisfies_constraint_type"):
        return 0.0
    penalty = _penalty_at_risk(candidate)
    if penalty <= 0:
        return 0.0
    if bool(candidate.facts.get("actually_satisfies_after_this_wait")):
        return penalty
    urgency = str(candidate.facts.get("urgency") or "")
    if candidate.action == "reposition":
        if bool(candidate.facts.get("must_do_now")) or urgency == "critical":
            progress = penalty * 0.45
        elif urgency == "high":
            progress = penalty * 0.18
        elif urgency == "medium":
            progress = penalty * 0.04
        else:
            progress = penalty * 0.01
    elif bool(candidate.facts.get("must_do_now")) or urgency == "critical":
        progress = penalty * 0.65
    elif urgency == "high":
        progress = penalty * 0.35
    elif urgency == "medium":
        progress = penalty * 0.12
    else:
        progress = penalty * 0.03
    if bool(candidate.facts.get("stuck_suspected")) and not bool(candidate.facts.get("must_do_now")):
        progress *= 0.25
    return progress


def _decision_score(
    *,
    candidate: Candidate,
    net_after_penalty: float,
    rate: float,
    future_value: float,
    wait_cost: float,
    idle_wait_penalty: float,
    action_opportunity_cost: float,
    progress_delta: float,
    wait_allowed: object,
    best_alternative_net: float,
) -> float:
    rate_bonus = 0.0
    if candidate.action == "take_order":
        rate_bonus = max(-500.0, min(1500.0, rate)) * 0.35
    market_probe_bonus = 0.0
    if candidate.source == "market_probe":
        market_probe_bonus = max(0.0, _fact_float(candidate, "market_probe_score") or 0.0) * 350.0
    score = net_after_penalty + future_value + progress_delta + rate_bonus + market_probe_bonus - wait_cost - idle_wait_penalty - action_opportunity_cost
    if candidate.action == "wait" and wait_allowed is False:
        score -= max(1000.0, wait_cost * 2.0, best_alternative_net)
    if bool(candidate.facts.get("stuck_suspected")) and not bool(candidate.facts.get("must_do_now")):
        score -= 500.0
    return round(score, 2)


def _idle_wait_penalty(candidate: Candidate, wait_expected_progress: object, market: MarketSnapshot) -> float:
    if candidate.action != "wait":
        return 0.0
    if bool(wait_expected_progress):
        return 0.0
    if candidate.source != "system":
        return 0.0
    if market.visible_cargo_count <= 0:
        return 0.0
    if market.profitable_cargo_count > 0:
        return 600.0
    return 180.0


def _action_opportunity_cost(candidate: Candidate, best_alternative_net: float) -> float:
    if candidate.action == "take_order":
        return 0.0
    alternative = max(0.0, float(best_alternative_net or 0.0))
    if alternative <= 0:
        return 0.0
    if candidate.action == "wait":
        return 0.0
    urgency = str(candidate.facts.get("urgency") or "")
    if bool(candidate.facts.get("must_do_now")) or urgency == "critical":
        multiplier = 0.35
    elif urgency == "high":
        multiplier = 0.75
    else:
        multiplier = 1.0
    if candidate.source == "market_probe":
        multiplier = 0.9
    return round(alternative * multiplier, 2)


def _decision_reason(candidate: Candidate, wait_gate_reason: object) -> str:
    if candidate.action == "wait":
        return f"wait_gate={wait_gate_reason or 'none'}"
    if candidate.action == "take_order":
        return "order_net_rate_future_value"
    if candidate.action == "reposition":
        return "goal_progress_or_destination_positioning"
    return "candidate_value"


def _penalty_at_risk(candidate: Candidate) -> float:
    for key in ("penalty_at_risk", "penalty_if_missed", "penalty_if_rest_not_completed", "avoids_estimated_penalty"):
        value = _fact_float(candidate, key)
        if value is not None and value > 0:
            return value
    return 0.0


def _penalty_weight(candidate: Candidate) -> float:
    value = _fact_float(candidate, "decision_penalty_weight")
    if value is None:
        return DEFAULT_DECISION_PENALTY_WEIGHT
    return max(0.0, min(1.0, value))


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


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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
