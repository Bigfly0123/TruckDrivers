from __future__ import annotations

from agent.phase3.agent_state import AgentState
from agent.phase3.tools.constraint_tool import ConstraintTool


class ConstraintNode:
    node_name = "constraint_node"

    def __init__(self) -> None:
        self._tool = ConstraintTool()

    def __call__(self, state: AgentState) -> AgentState:
        state = self._tool.evaluate_candidates(state)
        _set_summary(state, self.node_name, state.debug.get("constraint_summary", {}))
        return state


def _set_summary(state: AgentState, node_name: str, summary: dict[str, object]) -> None:
    state.debug.setdefault("node_summaries", {})[node_name] = summary
