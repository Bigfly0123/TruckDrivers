from __future__ import annotations

from typing import Any

from agent.phase3.domain.agent_models import Candidate


def choose_recovery_candidate(
    candidates: list[Candidate],
    *,
    exclude_candidate_ids: set[str] | None = None,
) -> tuple[Candidate | None, str]:
    """Choose an executable candidate only for exception recovery paths."""

    ranked = rank_recovery_candidates(candidates, exclude_candidate_ids=exclude_candidate_ids)
    if not ranked:
        return None, "no_executable_candidate_for_recovery"
    return ranked[0]


def rank_recovery_candidates(
    candidates: list[Candidate],
    *,
    exclude_candidate_ids: set[str] | None = None,
) -> list[tuple[Candidate, str]]:
    """Rank executable recovery candidates without inventing new actions."""

    excluded = exclude_candidate_ids or set()
    pool = [c for c in candidates if c.candidate_id not in excluded]
    if not pool:
        return []

    with_decision_score = [c for c in pool if _fact_float(c, "decision_score") is not None]
    if with_decision_score:
        return [
            (c, "highest_executable_decision_score")
            for c in sorted(with_decision_score, key=lambda c: _fact_float(c, "decision_score") or -10**9, reverse=True)
        ]

    with_long_term = [c for c in pool if _fact_float(c, "long_term_score_hint") is not None]
    if with_long_term:
        return [
            (c, "highest_executable_long_term_score")
            for c in sorted(with_long_term, key=lambda c: _fact_float(c, "long_term_score_hint") or -10**9, reverse=True)
        ]

    with_net_after_penalty = [c for c in pool if _fact_float(c, "estimated_net_after_penalty") is not None]
    if with_net_after_penalty:
        return [
            (c, "highest_executable_estimated_net_after_penalty")
            for c in sorted(with_net_after_penalty, key=lambda c: _fact_float(c, "estimated_net_after_penalty") or -10**9, reverse=True)
        ]

    with_net = [c for c in pool if _fact_float(c, "estimated_net") is not None]
    if with_net:
        return [
            (c, "highest_executable_estimated_net")
            for c in sorted(with_net, key=lambda c: _fact_float(c, "estimated_net") or -10**9, reverse=True)
        ]

    goal_wait = [c for c in pool if c.action == "wait" and c.source == "goal_satisfy"]
    if goal_wait:
        return [(c, "goal_satisfy_wait") for c in goal_wait]

    purpose_wait = [
        c for c in pool
        if c.action == "wait"
        and str(c.facts.get("wait_purpose") or "") in {"rest_progress_wait", "home_window_wait", "goal_hold_wait"}
    ]
    if purpose_wait:
        return [(c, "purpose_wait") for c in purpose_wait]

    return [(c, "first_executable_candidate") for c in pool]


def recovery_candidate_summary(candidate: Candidate | None) -> dict[str, Any]:
    if candidate is None:
        return {}
    return {
        "recovery_candidate_id": candidate.candidate_id,
        "recovery_candidate_action": candidate.action,
        "recovery_candidate_source": candidate.source,
        "recovery_candidate_estimated_net": _fact_float(candidate, "estimated_net"),
        "recovery_candidate_estimated_net_after_penalty": _fact_float(candidate, "estimated_net_after_penalty"),
        "recovery_candidate_long_term_score": _fact_float(candidate, "long_term_score_hint"),
    }


def fallback_provenance(
    *,
    source: str,
    reason: str,
    candidates: list[Candidate],
    recovery_attempted: bool,
    recovery_failed_reason: str | None = None,
) -> dict[str, Any]:
    profitable_order = any(
        c.action == "take_order"
        and (_fact_float(c, "estimated_net_after_penalty") or _fact_float(c, "estimated_net") or 0.0) > 0
        for c in candidates
    )
    return {
        "fallback_used": True,
        "fallback_source": source,
        "fallback_reason": reason,
        "fallback_wait_type": "true_last_resort" if not candidates or recovery_attempted else "unproven_fallback",
        "executable_candidate_count_before_fallback": len(candidates),
        "profitable_order_existed_before_fallback": profitable_order,
        "recovery_attempted": recovery_attempted,
        "recovery_failed_reason": recovery_failed_reason,
    }


def _fact_float(candidate: Candidate, key: str) -> float | None:
    value = candidate.facts.get(key)
    if value is None and key == "estimated_net_after_penalty":
        value = candidate.facts.get("estimated_net")
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
