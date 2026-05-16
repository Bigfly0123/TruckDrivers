from __future__ import annotations

from agent.phase3.domain.agent_models import Candidate
from agent.phase3.agent_state import AgentState
from agent.phase3.candidates.candidate_fact_builder import CandidateFactBuilder


class CandidateGenerationService:
    """Build observable action candidates from current state and cargo facts."""

    def __init__(self) -> None:
        self._builder = CandidateFactBuilder()

    def build(self, state: AgentState) -> list[Candidate]:
        if state.decision_state is None:
            raise ValueError("candidate generation requires decision_state")
        return self._builder.build_candidates(
            state.decision_state,
            state.preference_rules,
            state.visible_cargo,
            state.constraints,
            state.constraint_runtime_state,
        )
