from __future__ import annotations

from agent.phase3.adapters.legacy_constraint_adapter import LegacyConstraintAdapter
from agent.phase3.agent_state import AgentState
from agent.phase3.utils.summaries import constraint_summary


class ConstraintNode:
    node_name = "constraint_node"

    def __init__(self) -> None:
        self._adapter = LegacyConstraintAdapter()

    def __call__(self, state: AgentState) -> AgentState:
        state.evaluated_candidates = self._adapter.evaluate(state)
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
        summary = constraint_summary(state)
        state.debug["constraint_summary"] = summary
        _set_summary(state, self.node_name, summary)
        return state


def _set_summary(state: AgentState, node_name: str, summary: dict[str, object]) -> None:
    state.debug.setdefault("node_summaries", {})[node_name] = summary
