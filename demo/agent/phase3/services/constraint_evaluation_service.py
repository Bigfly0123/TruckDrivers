from __future__ import annotations

from agent.phase3.domain.agent_models import Candidate
from agent.phase3.constraints.constraint_evaluator import ConstraintEvaluator
from agent.phase3.advisor.llm_decision_advisor import CandidateSummary
from agent.phase3.agent_state import AgentState

_TRUE_HARD_REASONS = {
    "invalid_cargo_geometry",
    "cargo_online_expired",
    "load_time_window_expired",
    "load_time_window_unreachable",
    "end_month_unreachable",
}

_REACHABILITY_HARD_REASONS = {
    "cargo_online_expired",
    "load_time_window_expired",
    "load_time_window_unreachable",
    "end_month_unreachable",
}

DECISION_PENALTY_WEIGHT = 0.25


class ConstraintEvaluationService:
    """Evaluate hard invalidity, soft risk, and penalty exposure for candidates."""

    def __init__(self) -> None:
        self._evaluator = ConstraintEvaluator()

    def evaluate(self, state: AgentState) -> list[Candidate]:
        if state.decision_state is None:
            raise ValueError("constraint evaluation requires decision_state")
        evaluated: list[Candidate] = []
        for candidate in state.raw_candidates:
            result = self._evaluator.evaluate(
                candidate,
                state.constraints,
                state.decision_state,
                state.constraint_runtime_state,
            )
            merged_hard, merged_soft, boundary_notes = _classify_boundary(
                candidate.hard_invalid_reasons + result.hard_invalid_reasons,
                candidate.soft_risk_reasons + result.soft_risk_reasons,
            )
            penalty = result.estimated_penalty_exposure
            enriched_facts = dict(candidate.facts)
            enriched_facts["constraint_impacts"] = tuple(
                {
                    "constraint_id": impact.constraint_id,
                    "constraint_type": impact.constraint_type,
                    "status": impact.status,
                    "penalty": impact.penalty,
                    "detail": impact.detail,
                }
                for impact in result.constraint_impacts
            )
            enriched_facts["estimated_penalty_exposure"] = penalty
            enriched_facts["marginal_penalty_exposure"] = penalty
            decision_penalty = round(penalty * DECISION_PENALTY_WEIGHT, 2)
            enriched_facts["decision_penalty_weight"] = DECISION_PENALTY_WEIGHT
            enriched_facts["decision_penalty_cost"] = decision_penalty
            net = float(enriched_facts.get("estimated_net", 0) or 0)
            enriched_facts["estimated_net_after_penalty"] = round(net - penalty, 2)
            enriched_facts["estimated_net_after_marginal_penalty"] = round(net - penalty, 2)
            enriched_facts["estimated_net_after_decision_penalty"] = round(net - decision_penalty, 2)
            enriched_facts["satisfies_constraints"] = result.satisfies_all_constraints
            if any(reason in _REACHABILITY_HARD_REASONS for reason in merged_hard):
                enriched_facts["simulator_executable"] = False
                enriched_facts["non_executable_layer"] = "cargo_reachability"
            elif candidate.action == "take_order":
                enriched_facts.setdefault("simulator_executable", True)
            if boundary_notes:
                enriched_facts["hard_soft_boundary_reclassification"] = tuple(boundary_notes)
            evaluated.append(Candidate(
                candidate_id=candidate.candidate_id,
                action=candidate.action,
                params=candidate.params,
                source=candidate.source,
                facts=enriched_facts,
                hard_invalid_reasons=merged_hard,
                soft_risk_reasons=merged_soft,
            ))
        return evaluated

    def build_candidate_summaries(self, candidates: list[Candidate]) -> dict[str, CandidateSummary]:
        summaries: dict[str, CandidateSummary] = {}
        for candidate in candidates:
            impacts_raw = candidate.facts.get("constraint_impacts", ())
            impacts_list: list[dict[str, object]] = []
            if isinstance(impacts_raw, tuple):
                impacts_list = [impact for impact in impacts_raw if isinstance(impact, dict)]
            summaries[candidate.candidate_id] = CandidateSummary(
                candidate_id=candidate.candidate_id,
                action=candidate.action,
                estimated_net=float(candidate.facts.get("estimated_net", 0) or 0),
                estimated_penalty_exposure=float(candidate.facts.get("estimated_penalty_exposure", 0) or 0),
                estimated_net_after_penalty=float(candidate.facts.get("estimated_net_after_penalty", 0) or 0),
                satisfies_constraints=bool(candidate.facts.get("satisfies_constraints", True)),
                soft_risk_reasons=candidate.soft_risk_reasons,
                constraint_impacts=tuple(impacts_list),
            )
        return summaries


def _classify_boundary(
    hard_reasons: tuple[str, ...],
    soft_reasons: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[dict[str, str], ...]]:
    """Only simulator-impossible reasons stay hard; preferences remain soft risks."""

    hard: list[str] = []
    soft: list[str] = list(soft_reasons)
    notes: list[dict[str, str]] = []
    for reason in hard_reasons:
        reason_text = str(reason)
        if reason_text in _TRUE_HARD_REASONS:
            hard.append(reason_text)
            continue
        if reason_text.startswith("constraint_"):
            soft_reason = f"{reason_text}_risk"
            if soft_reason not in soft:
                soft.append(soft_reason)
            notes.append({
                "reason": reason_text,
                "from": "hard_invalid",
                "to": "soft_risk",
                "classification": "should_be_soft",
            })
            continue
        hard.append(reason_text)
    return tuple(hard), tuple(soft), tuple(notes)
