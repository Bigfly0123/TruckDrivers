from __future__ import annotations

from dataclasses import replace
from typing import Any

from agent.agent_models import Candidate
from agent.phase3.agent_state import AgentState
from agent.phase3.opportunity.destination_value_estimator import DestinationValueEstimator
from agent.phase3.opportunity.future_value_estimator import FutureValueEstimator
from agent.phase3.opportunity.market_snapshot import build_market_snapshot
from agent.phase3.opportunity.opportunity_diagnostics import build_opportunity_summary
from agent.phase3.opportunity.opportunity_schema import CandidateOpportunityFacts
from agent.phase3.opportunity.wait_cost_estimator import WaitCostEstimator


class OpportunityValueTool:
    """Adds opportunity/future-value evidence to existing candidates.

    This tool never creates final actions and never changes hard-validity
    categories. Advisor and SafetyGate remain responsible for selection and
    final validation.
    """

    def __init__(self) -> None:
        self._wait_cost = WaitCostEstimator()
        self._destination = DestinationValueEstimator()
        self._future = FutureValueEstimator()

    def annotate(self, state: AgentState) -> AgentState:
        market = build_market_snapshot(state)
        facts_by_id: dict[str, CandidateOpportunityFacts] = {}
        annotated: list[Candidate] = []
        for candidate in state.evaluated_candidates:
            wait_facts = self._wait_cost.estimate(candidate, market)
            destination_facts = self._destination.estimate(candidate, state)
            opportunity_facts = self._future.estimate(candidate, market, wait_facts, destination_facts)
            facts_by_id[candidate.candidate_id] = opportunity_facts
            annotated.append(_with_opportunity_facts(candidate, opportunity_facts))

        annotated_by_id = {c.candidate_id: c for c in annotated}
        state.evaluated_candidates = annotated
        state.valid_candidates = _replace_candidates(state.valid_candidates, annotated_by_id)
        state.soft_risk_candidates = _replace_candidates(state.soft_risk_candidates, annotated_by_id)
        state.hard_invalid_candidates = _replace_candidates(state.hard_invalid_candidates, annotated_by_id)
        state.opportunity_facts = [facts.to_dict() for facts in facts_by_id.values()]
        state.opportunity_context = {
            "market_snapshot": market.to_dict(),
            "candidate_opportunity_facts": state.opportunity_facts,
        }
        summary = build_opportunity_summary(
            market=market,
            facts=list(facts_by_id.values()),
            selected_candidate_id=state.selected_candidate_id,
        )
        state.tool_summaries["opportunity_value_tool"] = summary
        state.debug["opportunity_summary"] = summary
        return state


def _with_opportunity_facts(candidate: Candidate, facts: CandidateOpportunityFacts) -> Candidate:
    merged = dict(candidate.facts)
    for key, value in facts.to_dict().items():
        if key in {"candidate_id", "action_type"}:
            continue
        if value is not None:
            merged[key] = value
    return replace(candidate, facts=merged)


def _replace_candidates(candidates: list[Candidate], annotated_by_id: dict[str, Candidate]) -> list[Candidate]:
    return [annotated_by_id.get(candidate.candidate_id, candidate) for candidate in candidates]

