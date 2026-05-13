from __future__ import annotations

from agent.agent_models import Candidate
from agent.phase3.agent_state import AgentState
from agent.planner import CandidateFactBuilder


class LegacyCandidateAdapter:
    def __init__(self) -> None:
        self._builder = CandidateFactBuilder()

    def build(self, state: AgentState) -> list[Candidate]:
        if state.decision_state is None:
            raise ValueError("candidate adapter requires decision_state")
        return self._builder.build_candidate_pool(
            state.decision_state,
            state.preference_rules,
            state.visible_cargo,
            state.constraints,
            state.constraint_runtime_state,
        )
