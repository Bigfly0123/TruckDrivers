from __future__ import annotations

from collections import Counter
from typing import Any

from agent.agent_models import Candidate
from agent.phase3.agent_state import AgentState


def action_counts(candidates: list[Candidate]) -> dict[str, int]:
    return dict(Counter(c.action for c in candidates))


def hard_invalid_reason_counts(candidates: list[Candidate]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for candidate in candidates:
        counts.update(str(reason) for reason in candidate.hard_invalid_reasons)
    return dict(counts.most_common(10))


def sample_hard_invalid_candidates(candidates: list[Candidate], limit: int = 5) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for candidate in candidates[:limit]:
        samples.append({
            "candidate_id": candidate.candidate_id,
            "action": candidate.action,
            "source": candidate.source,
            "cargo_id": candidate.params.get("cargo_id"),
            "hard_invalid_reasons": list(candidate.hard_invalid_reasons),
            "pickup_arrival_minute": candidate.facts.get("pickup_arrival_minute"),
            "cargo_deadline_minute": candidate.facts.get("cargo_deadline_minute"),
            "deadline_source": candidate.facts.get("deadline_source"),
            "finish_minute": candidate.facts.get("finish_minute"),
        })
    return samples


def candidate_summary(state: AgentState) -> dict[str, Any]:
    satisfy_types = sorted({
        str(c.facts.get("satisfies_constraint_type") or c.facts.get("constraint_type") or "")
        for c in state.raw_candidates
        if c.source == "constraint_satisfy"
    })
    return {
        "raw_candidate_count": len(state.raw_candidates),
        "candidate_action_counts": action_counts(state.raw_candidates),
        "satisfy_candidate_types": [t for t in satisfy_types if t],
    }


def constraint_summary(state: AgentState) -> dict[str, Any]:
    return {
        "candidate_count": len(state.evaluated_candidates),
        "valid_count": len(state.valid_candidates),
        "soft_risk_count": len(state.soft_risk_candidates),
        "hard_invalid_count": len(state.hard_invalid_candidates),
        "hard_invalid_reason_counts": hard_invalid_reason_counts(state.hard_invalid_candidates),
    }


def final_decision_summary(state: AgentState) -> dict[str, Any]:
    selected_action = state.selected_candidate.action if state.selected_candidate is not None else None
    hard_reason_counts = hard_invalid_reason_counts(state.hard_invalid_candidates)
    return {
        "driver_id": state.driver_id,
        "step_id": state.step_id,
        "step": state.step_id,
        "current_time": state.current_time,
        "current_day": state.current_day,
        "day": state.current_day,
        "minute": state.current_time % 1440 if state.current_time is not None else None,
        "current_location": state.current_location,
        "visible_cargo_count": len(state.visible_cargo),
        "candidate_count": len(state.evaluated_candidates or state.raw_candidates),
        "valid_count": len(state.valid_candidates),
        "soft_risk_count": len(state.soft_risk_candidates),
        "hard_invalid_count": len(state.hard_invalid_candidates),
        "hard_invalid_reason_counts": hard_reason_counts,
        "top_hard_invalid_reasons": hard_reason_counts,
        "sample_hard_invalid_candidates": sample_hard_invalid_candidates(state.hard_invalid_candidates),
        "advisor_candidate_count": state.advisor_context.get("candidate_count", 0),
        "selected_candidate_id": state.selected_candidate_id,
        "selected_action": selected_action,
        "selected_reason": state.advisor_result.get("reason"),
        "safety_passed": state.safety_result.get("accepted"),
        "safety_accepted": state.safety_result.get("accepted"),
        "fallback_used": state.fallback_used,
        "fallback_reason": state.fallback_reason,
        "final_action": state.final_action,
    }
