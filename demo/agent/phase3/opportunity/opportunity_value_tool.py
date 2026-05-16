from __future__ import annotations

from dataclasses import replace
from typing import Any

from agent.phase3.domain.agent_models import Candidate
from agent.phase3.agent_state import AgentState
from agent.phase3.opportunity.destination_value_estimator import DestinationValueEstimator
from agent.phase3.opportunity.future_value_estimator import FutureValueEstimator
from agent.phase3.opportunity.market_snapshot import build_market_snapshot
from agent.phase3.opportunity.opportunity_diagnostics import (
    build_advisor_opportunity_summary,
    build_diagnostic_opportunity_summary,
)
from agent.phase3.opportunity.opportunity_schema import CandidateOpportunityFacts
from agent.phase3.opportunity.wait_cost_estimator import WaitCostEstimator


class OpportunityValueTool:
    """Adds opportunity/future-value evidence to existing candidates.

    This tool never creates final actions and never changes hard-validity
    categories. Advisor and final safety validation remain responsible for selection and
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
        state.zero_risk_candidates = _replace_candidates(state.zero_risk_candidates, annotated_by_id)
        state.risk_tradeoff_candidates = _replace_candidates(state.risk_tradeoff_candidates, annotated_by_id)
        state.non_executable_candidates = _replace_candidates(state.non_executable_candidates, annotated_by_id)
        state.executable_candidates = state.zero_risk_candidates + state.risk_tradeoff_candidates
        executable_ids = {c.candidate_id for c in state.executable_candidates}
        hard_reasons_by_id = {
            c.candidate_id: tuple(c.hard_invalid_reasons)
            for c in state.hard_invalid_candidates
        }
        state.opportunity_facts = [facts.to_dict() for facts in facts_by_id.values()]
        advisor_summary = build_advisor_opportunity_summary(
            market=market,
            facts=list(facts_by_id.values()),
            executable_ids=executable_ids,
            selected_candidate_id=state.selected_candidate_id,
        )
        diagnostic_summary = build_diagnostic_opportunity_summary(
            market=market,
            facts=list(facts_by_id.values()),
            executable_ids=executable_ids,
            hard_invalid_reasons_by_id=hard_reasons_by_id,
        )
        state.opportunity_context = {
            "market_snapshot": market.to_dict(),
            "candidate_opportunity_facts": state.opportunity_facts,
            "advisor_opportunity_summary": advisor_summary,
            "diagnostic_opportunity_summary": diagnostic_summary,
        }
        summary = {
            **advisor_summary,
            "advisor_opportunity_summary": advisor_summary,
            "diagnostic_opportunity_summary": diagnostic_summary,
        }
        state.tool_summaries["opportunity_value_tool"] = summary
        state.debug["opportunity_summary"] = summary
        state.debug["advisor_opportunity_summary"] = advisor_summary
        state.debug["diagnostic_opportunity_summary"] = diagnostic_summary
        return state


def _with_opportunity_facts(candidate: Candidate, facts: CandidateOpportunityFacts) -> Candidate:
    merged = dict(candidate.facts)
    for key, value in facts.to_dict().items():
        if key in {"candidate_id", "action_type"}:
            continue
        if value is not None:
            merged[key] = value
    if candidate.action == "wait":
        merged.setdefault("wait_purpose", _wait_purpose(candidate))
        merged.setdefault("wait_expected_progress", _wait_expected_progress(candidate))
    return replace(candidate, facts=merged)


def _replace_candidates(candidates: list[Candidate], annotated_by_id: dict[str, Candidate]) -> list[Candidate]:
    return [annotated_by_id.get(candidate.candidate_id, candidate) for candidate in candidates]


def _wait_purpose(candidate: Candidate) -> str:
    satisfy_type = str(candidate.facts.get("satisfies_constraint_type") or candidate.facts.get("goal_type") or "")
    step_type = str(candidate.facts.get("step_type") or "")
    if satisfy_type == "continuous_rest":
        return "rest_progress_wait"
    if satisfy_type == "be_at_location_by_deadline" and step_type in {"stay_at_location", "stay_until_time", "hold_location_until_time"}:
        return "home_window_wait"
    if step_type == "hold_location_until_time":
        return "goal_hold_wait"
    if candidate.facts.get("goal_id"):
        return "goal_wait"
    if candidate.source == "system":
        return "market_wait"
    return "unknown_wait"


def _wait_expected_progress(candidate: Candidate) -> bool:
    purpose = _wait_purpose(candidate)
    if purpose in {"rest_progress_wait", "home_window_wait", "goal_hold_wait", "goal_wait"}:
        return True
    return bool(candidate.facts.get("actually_satisfies_after_this_wait"))
