from __future__ import annotations

from statistics import mean
from typing import Any

from agent.agent_models import Candidate
from agent.geo_utils import haversine_km
from agent.phase3.agent_state import AgentState

DESTINATION_RADIUS_KM = 80.0


class DestinationValueEstimator:
    def estimate(self, candidate: Candidate, state: AgentState) -> dict[str, object]:
        destination = _destination(candidate, state)
        if destination is None:
            return {
                "destination_opportunity_score": None,
                "destination_visible_cargo_count": None,
                "destination_avg_nearby_order_net": None,
            }
        nearby_nets = _nearby_order_nets(destination, state.valid_candidates + state.soft_risk_candidates)
        count = len(nearby_nets)
        avg_net = round(mean(nearby_nets), 2) if nearby_nets else None
        score = _score(count, avg_net)
        return {
            "destination_opportunity_score": score,
            "destination_visible_cargo_count": count,
            "destination_avg_nearby_order_net": avg_net,
        }


def _destination(candidate: Candidate, state: AgentState) -> tuple[float, float] | None:
    if candidate.action == "take_order":
        end = candidate.facts.get("end")
        if isinstance(end, (list, tuple)) and len(end) >= 2:
            return _point(end[0], end[1])
    if candidate.action == "reposition":
        return _point(candidate.params.get("latitude"), candidate.params.get("longitude"))
    if candidate.action == "wait" and state.decision_state is not None:
        return state.decision_state.current_latitude, state.decision_state.current_longitude
    return None


def _nearby_order_nets(destination: tuple[float, float], candidates: list[Candidate]) -> list[float]:
    nets: list[float] = []
    for candidate in candidates:
        if candidate.action != "take_order":
            continue
        start = candidate.facts.get("start")
        if not isinstance(start, (list, tuple)) or len(start) < 2:
            continue
        if haversine_km(destination[0], destination[1], start[0], start[1]) <= DESTINATION_RADIUS_KM:
            net = _safe_float(candidate.facts.get("estimated_net_after_penalty", candidate.facts.get("estimated_net")))
            if net > 0:
                nets.append(net)
    return nets


def _score(count: int, avg_net: float | None) -> float:
    density_score = min(1.0, count / 5.0)
    net_score = min(1.0, max(0.0, float(avg_net or 0.0)) / 1000.0)
    return round((density_score * 0.55) + (net_score * 0.45), 3)


def _point(lat: Any, lng: Any) -> tuple[float, float] | None:
    try:
        return float(lat), float(lng)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0

