from __future__ import annotations

from agent.phase3.adapters.legacy_candidate_adapter import LegacyCandidateAdapter
from agent.phase3.agent_state import AgentState
from agent.phase3.utils.summaries import candidate_summary


class CandidateNode:
    node_name = "candidate_node"

    def __init__(self) -> None:
        self._adapter = LegacyCandidateAdapter()

    def __call__(self, state: AgentState) -> AgentState:
        state.raw_candidates = self._adapter.build(state)
        _set_summary(state, self.node_name, candidate_summary(state))
        return state


def _set_summary(state: AgentState, node_name: str, summary: dict[str, object]) -> None:
    state.debug.setdefault("node_summaries", {})[node_name] = summary
