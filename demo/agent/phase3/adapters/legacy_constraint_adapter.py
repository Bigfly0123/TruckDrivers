from __future__ import annotations

from agent.agent_models import Candidate
from agent.constraint_evaluator import ConstraintEvaluator
from agent.llm_decision_advisor import CandidateSummary
from agent.phase3.agent_state import AgentState


class LegacyConstraintAdapter:
    def __init__(self) -> None:
        self._evaluator = ConstraintEvaluator()

    def evaluate(self, state: AgentState) -> list[Candidate]:
        if state.decision_state is None:
            raise ValueError("constraint adapter requires decision_state")
        evaluated: list[Candidate] = []
        for candidate in state.raw_candidates:
            result = self._evaluator.evaluate(
                candidate,
                state.constraints,
                state.decision_state,
                state.constraint_runtime_state,
            )
            merged_hard = candidate.hard_invalid_reasons + result.hard_invalid_reasons
            merged_soft = candidate.soft_risk_reasons + result.soft_risk_reasons
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
            net = float(enriched_facts.get("estimated_net", 0) or 0)
            enriched_facts["estimated_net_after_penalty"] = round(net - penalty, 2)
            enriched_facts["satisfies_constraints"] = result.satisfies_all_constraints
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
