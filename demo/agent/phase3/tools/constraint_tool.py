from __future__ import annotations

from collections import Counter
from typing import Any

from agent.agent_models import Candidate
from agent.phase3.adapters.legacy_constraint_adapter import LegacyConstraintAdapter
from agent.phase3.agent_state import AgentState
from agent.phase3.utils.summaries import (
    hard_invalid_reason_classification,
    hard_invalid_reason_counts,
    hard_soft_boundary_reclassification_count,
)


class ConstraintTool:
    """Phase 3 deterministic constraint tool.

    It evaluates and groups candidates through the legacy evaluator without
    changing constraint behavior.
    """

    def __init__(self) -> None:
        self._legacy = LegacyConstraintAdapter()

    def evaluate_candidates(self, state: AgentState) -> AgentState:
        state.evaluated_candidates = self._legacy.evaluate(state)
        state.valid_candidates = [
            c for c in state.evaluated_candidates
            if not c.hard_invalid_reasons and not c.soft_risk_reasons
        ]
        state.soft_risk_candidates = [
            c for c in state.evaluated_candidates
            if not c.hard_invalid_reasons and c.soft_risk_reasons
        ]
        state.hard_invalid_candidates = [
            c for c in state.evaluated_candidates
            if c.hard_invalid_reasons
        ]
        summary = self.summarize_constraints(state)
        state.tool_summaries["constraint_tool"] = summary
        state.debug["constraint_summary"] = summary
        return state

    def summarize_constraints(self, state: AgentState) -> dict[str, Any]:
        valid_orders = _orders(state.valid_candidates)
        soft_orders = _orders(state.soft_risk_candidates)
        profitable_valid = [c for c in valid_orders if _net(c) > 0]
        profitable_soft = [c for c in soft_orders if _net_after_penalty(c) > 0]
        best_valid = _best(valid_orders, _net)
        best_soft = _best(soft_orders, _net_after_penalty)
        hard_counts = hard_invalid_reason_counts(state.hard_invalid_candidates)
        dominant_reason = next(iter(hard_counts), None)
        return {
            "candidate_count": len(state.evaluated_candidates),
            "valid_count": len(state.valid_candidates),
            "soft_risk_count": len(state.soft_risk_candidates),
            "hard_invalid_count": len(state.hard_invalid_candidates),
            "valid_order_count": len(valid_orders),
            "valid_profitable_order_count": len(profitable_valid),
            "soft_risk_order_count": len(soft_orders),
            "soft_risk_profitable_order_count": len(profitable_soft),
            "best_valid_order_id": best_valid.candidate_id if best_valid else None,
            "best_valid_order_net": _net(best_valid) if best_valid else None,
            "best_soft_risk_order_id": best_soft.candidate_id if best_soft else None,
            "best_soft_risk_order_net_after_penalty": _net_after_penalty(best_soft) if best_soft else None,
            "hard_invalid_reason_counts": hard_counts,
            "hard_invalid_reason_classification": hard_invalid_reason_classification(hard_counts),
            "dominant_hard_invalid_reason": dominant_reason,
            "hard_soft_boundary_reclassification_count": hard_soft_boundary_reclassification_count(state.evaluated_candidates),
            "candidate_action_counts": dict(Counter(c.action for c in state.evaluated_candidates)),
        }


def _orders(candidates: list[Candidate]) -> list[Candidate]:
    return [c for c in candidates if c.action == "take_order"]


def _net(candidate: Candidate | None) -> float:
    if candidate is None:
        return 0.0
    return float(candidate.facts.get("estimated_net", 0) or 0)


def _net_after_penalty(candidate: Candidate | None) -> float:
    if candidate is None:
        return 0.0
    return float(candidate.facts.get("estimated_net_after_penalty", candidate.facts.get("estimated_net", 0)) or 0)


def _best(candidates: list[Candidate], key_fn: Any) -> Candidate | None:
    if not candidates:
        return None
    return max(candidates, key=key_fn)
