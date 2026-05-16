from __future__ import annotations

from typing import Any

from agent.phase3.domain.agent_models import Candidate, GeoPoint


def wait_candidate(
    *,
    candidate_id: str,
    duration_minutes: int,
    facts: dict[str, Any],
) -> Candidate:
    return Candidate(
        candidate_id=candidate_id,
        action="wait",
        params={"duration_minutes": max(1, int(duration_minutes))},
        source="goal_satisfy",
        facts=facts,
    )


def reposition_candidate(
    *,
    candidate_id: str,
    point: GeoPoint,
    facts: dict[str, Any],
) -> Candidate:
    return Candidate(
        candidate_id=candidate_id,
        action="reposition",
        params={"latitude": point.latitude, "longitude": point.longitude},
        source="goal_satisfy",
        facts=facts,
    )


def clone_goal_order_candidate(
    *,
    candidate_id: str,
    base: Candidate,
    facts: dict[str, Any],
) -> Candidate:
    merged = dict(base.facts)
    merged.update(facts)
    return Candidate(
        candidate_id=candidate_id,
        action=base.action,
        params=dict(base.params),
        source="goal_satisfy",
        facts=merged,
        hard_invalid_reasons=base.hard_invalid_reasons,
        soft_risk_reasons=base.soft_risk_reasons,
    )
