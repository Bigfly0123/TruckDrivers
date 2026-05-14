from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class MarketSnapshot:
    visible_cargo_count: int = 0
    profitable_cargo_count: int = 0
    best_valid_order_id: str | None = None
    best_valid_order_net: float | None = None
    best_soft_risk_order_id: str | None = None
    best_soft_risk_order_net_after_penalty: float | None = None
    nearby_cargo_density: int = 0
    nearby_avg_net: float | None = None
    time_of_day_bucket: str = "unknown"
    target_cargo_visibility_status: str = "untracked"
    missing_target_cargo_count: int = 0
    visible_target_cargo_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateOpportunityFacts:
    candidate_id: str
    action_type: str
    immediate_net: float | None = None
    destination_opportunity_score: float | None = None
    destination_visible_cargo_count: int | None = None
    destination_avg_nearby_order_net: float | None = None
    wait_opportunity_cost: float | None = None
    best_forgone_order_id: str | None = None
    best_forgone_order_net: float | None = None
    profitable_order_count: int | None = None
    future_constraint_risk: str | None = None
    future_value_estimate: float | None = None
    long_term_score_hint: float | None = None
    target_cargo_visibility_status: str | None = None
    specific_cargo_wait_cost: float | None = None
    specific_cargo_blocked_by_current_action_risk: str | None = None
    cargo_watch_hint: str | None = None
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

