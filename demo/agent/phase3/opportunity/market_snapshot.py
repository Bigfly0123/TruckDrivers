from __future__ import annotations

from statistics import mean
from typing import Any

from agent.phase3.domain.agent_models import Candidate
from agent.phase3.domain.geo_utils import haversine_km
from agent.phase3.agent_state import AgentState
from agent.phase3.opportunity.opportunity_schema import MarketSnapshot

NEARBY_RADIUS_KM = 80.0


def build_market_snapshot(state: AgentState) -> MarketSnapshot:
    zero_risk = state.zero_risk_candidates or state.valid_candidates
    risk_tradeoff = state.risk_tradeoff_candidates or state.soft_risk_candidates
    valid_orders = [c for c in zero_risk if c.action == "take_order"]
    soft_orders = [c for c in risk_tradeoff if c.action == "take_order"]
    profitable_valid = [c for c in valid_orders if _net(c) > 0]
    profitable_soft = [c for c in soft_orders if _net_after_penalty(c) > 0]
    best_valid = _best(valid_orders, _net)
    best_soft = _best(soft_orders, _net_after_penalty)
    nearby_nets = [
        _net(c)
        for c in valid_orders + soft_orders
        if _candidate_start_distance(state, c) <= NEARBY_RADIUS_KM
    ]
    target_status, missing_count, visible_count = _target_visibility(state)
    return MarketSnapshot(
        visible_cargo_count=len(state.visible_cargo),
        profitable_cargo_count=len(profitable_valid) + len(profitable_soft),
        best_valid_order_id=best_valid.candidate_id if best_valid else None,
        best_valid_order_net=_net(best_valid) if best_valid else None,
        best_soft_risk_order_id=best_soft.candidate_id if best_soft else None,
        best_soft_risk_order_net_after_penalty=_net_after_penalty(best_soft) if best_soft else None,
        nearby_cargo_density=len(nearby_nets),
        nearby_avg_net=round(mean(nearby_nets), 2) if nearby_nets else None,
        time_of_day_bucket=_time_bucket(state.current_time),
        target_cargo_visibility_status=target_status,
        missing_target_cargo_count=missing_count,
        visible_target_cargo_count=visible_count,
    )


def _target_visibility(state: AgentState) -> tuple[str, int, int]:
    runtime = state.constraint_runtime_state
    specific = getattr(runtime, "specific_cargo", None) if runtime is not None else None
    missing = tuple(getattr(specific, "missing_target_cargo_ids", ()) or ())
    visible = tuple(getattr(specific, "visible_target_cargo_ids", ()) or ())
    total = len(missing) + len(visible)
    if total <= 0:
        return "untracked", 0, 0
    if missing and visible:
        return "partially_visible", len(missing), len(visible)
    if missing:
        return "unavailable", len(missing), len(visible)
    return "visible", len(missing), len(visible)


def _candidate_start_distance(state: AgentState, candidate: Candidate) -> float:
    start = candidate.facts.get("start")
    if isinstance(start, (list, tuple)) and len(start) >= 2:
        return haversine_km(state.decision_state.current_latitude, state.decision_state.current_longitude, start[0], start[1])
    return 10**9


def _time_bucket(current_time: int | None) -> str:
    if current_time is None:
        return "unknown"
    minute = int(current_time) % 1440
    if minute < 360:
        return "night"
    if minute < 720:
        return "morning"
    if minute < 1080:
        return "afternoon"
    return "evening"


def _net(candidate: Candidate | None) -> float:
    if candidate is None:
        return 0.0
    return _safe_float(candidate.facts.get("estimated_net"))


def _net_after_penalty(candidate: Candidate | None) -> float:
    if candidate is None:
        return 0.0
    return _safe_float(
        candidate.facts.get(
            "estimated_net_after_decision_penalty",
            candidate.facts.get("estimated_net_after_penalty", candidate.facts.get("estimated_net")),
        )
    )


def _best(candidates: list[Candidate], key_fn: Any) -> Candidate | None:
    if not candidates:
        return None
    return max(candidates, key=key_fn)


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
