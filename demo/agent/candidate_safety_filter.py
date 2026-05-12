from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from agent.agent_models import CandidateScore, DecisionState, PreferenceRule
from agent.candidate_pool import BlockedCandidate, CandidatePool
from agent.mission_models import MissionPlan, MissionStep


@dataclass
class CandidateView:
    candidate_id: str
    action_type: str
    final_action: dict[str, Any]
    facts: dict[str, Any] = field(default_factory=dict)
    hard_invalid_reasons: list[str] = field(default_factory=list)
    soft_risk_reasons: list[str] = field(default_factory=list)
    preference_impacts: list[Any] = field(default_factory=list)
    source: str = "unknown"
    raw: Any = None


def to_candidate_view(candidate: Any) -> CandidateView:
    cargo_id = getattr(candidate, "cargo_id", None)

    final_action = getattr(candidate, "final_action", None)
    if final_action is None:
        action = getattr(candidate, "action", None)
        if isinstance(action, str):
            params: dict[str, Any] = {}
            raw_params = getattr(candidate, "params", None)
            if isinstance(raw_params, dict):
                params = raw_params
            final_action = {"type": action, **params}
        elif isinstance(action, dict):
            final_action = action
        elif cargo_id:
            final_action = {"type": "take_order", "cargo_id": cargo_id}
        else:
            final_action = {}

    candidate_id = getattr(candidate, "candidate_id", None)
    if not candidate_id:
        if isinstance(final_action, dict) and final_action.get("cargo_id"):
            candidate_id = f"take_order_{final_action.get('cargo_id')}"
        elif cargo_id:
            candidate_id = f"take_order_{cargo_id}"
        elif isinstance(final_action, dict) and final_action.get("type"):
            candidate_id = f"{final_action.get('type')}_unknown"
        else:
            candidate_id = "unknown_candidate"

    hard_reasons: list[str] = []
    raw_hard = getattr(candidate, "hard_invalid_reasons", None)
    if raw_hard:
        hard_reasons = [str(r) for r in raw_hard]
    else:
        for attr in ("reason", "reasons", "block_reason", "rejection_code"):
            value = getattr(candidate, attr, None)
            if value:
                if isinstance(value, (list, tuple)):
                    hard_reasons.extend(str(v) for v in value)
                else:
                    hard_reasons.append(str(value))
        block_reasons = getattr(candidate, "block_reasons", None)
        if block_reasons:
            hard_reasons.extend(str(r) for r in block_reasons)

    soft_reasons: list[str] = []
    raw_soft = getattr(candidate, "soft_risk_reasons", None)
    if raw_soft:
        soft_reasons = [str(r) for r in raw_soft]
    else:
        risk_reasons = getattr(candidate, "risk_reasons", None)
        if risk_reasons:
            soft_reasons = [str(r) for r in risk_reasons]
        risk_reason = getattr(candidate, "risk_reason", None)
        if risk_reason:
            soft_reasons.append(str(risk_reason))

    facts = getattr(candidate, "facts", None) or {}

    source = getattr(candidate, "source", None) or candidate.__class__.__name__

    action_type = getattr(candidate, "action_type", None)
    if not action_type:
        if isinstance(final_action, dict):
            action_type = final_action.get("type", final_action.get("action", "unknown"))
        else:
            action_type = "unknown"

    return CandidateView(
        candidate_id=str(candidate_id),
        action_type=str(action_type),
        final_action=final_action if isinstance(final_action, dict) else {},
        facts=facts if isinstance(facts, dict) else {},
        hard_invalid_reasons=hard_reasons,
        soft_risk_reasons=soft_reasons,
        preference_impacts=list(getattr(candidate, "preference_impacts", []) or []),
        source=str(source),
        raw=candidate,
    )


@dataclass(frozen=True)
class FilteredCandidates:
    valid_candidates: list[CandidateView]
    soft_risk_candidates: list[CandidateView]
    hard_invalid_candidates: list[CandidateView]
    summary: dict[str, Any]


class CandidateGrouper:
    """Phase 1.5: Only groups candidates, never filters or deletes soft risk.

    This module replaces CandidateSafetyFilter. It must NOT:
    - call SafetyGate
    - move candidates to blocked
    - delete soft risk candidates
    - make strategy decisions
    """

    def __init__(self) -> None:
        self._logger = logging.getLogger("agent.candidate_grouper")

    def apply(
        self,
        pool: CandidatePool,
        state: DecisionState,
        rules: tuple[PreferenceRule, ...],
        missions: tuple[MissionPlan, ...],
        locked_steps: list[tuple[MissionPlan, MissionStep]] | None = None,
    ) -> CandidatePool:
        """Deprecated: kept for compatibility but does nothing.

        Phase 1.5: grouping is done via split(). apply() is a no-op pass-through.
        """
        return pool

    def split(
        self,
        pool: CandidatePool,
        state: DecisionState,
        rules: tuple[PreferenceRule, ...],
        missions: tuple[MissionPlan, ...],
        locked_steps: list[tuple[MissionPlan, MissionStep]] | None = None,
    ) -> FilteredCandidates:
        """Group candidates by hard_invalid_reasons and soft_risk_reasons.

        All candidates are converted to CandidateView for uniform access.
        """
        all_raw: list[Any] = list(pool.executable) + list(pool.risky) + list(pool.blocked)
        views = [to_candidate_view(c) for c in all_raw]

        valid: list[CandidateView] = []
        soft_risk: list[CandidateView] = []
        hard_invalid: list[CandidateView] = []
        filter_stats: dict[str, int] = dict(pool.filter_stats)

        for view in views:
            if view.hard_invalid_reasons:
                for reason in view.hard_invalid_reasons:
                    filter_stats[reason] = filter_stats.get(reason, 0) + 1
                hard_invalid.append(view)
            elif view.soft_risk_reasons:
                soft_risk.append(view)
            else:
                valid.append(view)

        top_hard_reasons = sorted(
            filter_stats.keys(),
            key=lambda k: filter_stats[k],
            reverse=True,
        )[:3]
        top_soft_reasons = sorted(
            {reason for c in soft_risk for reason in c.soft_risk_reasons},
            key=lambda k: sum(1 for c in soft_risk if k in c.soft_risk_reasons),
            reverse=True,
        )[:3]

        summary = {
            "valid_count": len(valid),
            "soft_risk_count": len(soft_risk),
            "hard_invalid_count": len(hard_invalid),
            "top_hard_invalid_reasons": top_hard_reasons,
            "top_soft_risk_reasons": top_soft_reasons,
        }

        self._logger.info(
            "candidate grouper: total=%d valid=%d soft_risk=%d hard_invalid=%d",
            len(views),
            len(valid), len(soft_risk), len(hard_invalid),
        )

        return FilteredCandidates(
            valid_candidates=valid,
            soft_risk_candidates=soft_risk,
            hard_invalid_candidates=hard_invalid,
            summary=summary,
        )
