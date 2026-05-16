from __future__ import annotations

from agent.phase3.domain.agent_models import Candidate
from agent.phase3.opportunity.opportunity_schema import MarketSnapshot


class WaitCostEstimator:
    def estimate(self, candidate: Candidate, market: MarketSnapshot) -> dict[str, object]:
        if candidate.action != "wait":
            return {
                "wait_opportunity_cost": None,
                "best_forgone_order_id": None,
                "best_forgone_order_net": None,
                "profitable_order_count": market.profitable_cargo_count,
            }
        duration = _duration_minutes(candidate)
        best_net = _best_available_net(market)
        cost = round(max(0.0, best_net) * min(1.0, duration / 60.0), 2)
        return {
            "wait_opportunity_cost": cost,
            "best_forgone_order_id": market.best_valid_order_id or market.best_soft_risk_order_id,
            "best_forgone_order_net": round(best_net, 2) if best_net > 0 else None,
            "profitable_order_count": market.profitable_cargo_count,
        }


def _duration_minutes(candidate: Candidate) -> int:
    try:
        return max(1, int(candidate.params.get("duration_minutes") or candidate.facts.get("duration_minutes") or 0))
    except (TypeError, ValueError):
        return 60


def _best_available_net(market: MarketSnapshot) -> float:
    values = [
        market.best_valid_order_net,
        market.best_soft_risk_order_net_after_penalty,
    ]
    return max(float(v or 0.0) for v in values)

