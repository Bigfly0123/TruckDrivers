from __future__ import annotations

from agent.phase3.agent_state import AgentState
from agent.phase3.opportunity.opportunity_value_tool import OpportunityValueTool


class OpportunityNode:
    node_name = "opportunity_node"

    def __init__(self, tool: OpportunityValueTool | None = None) -> None:
        self._tool = tool or OpportunityValueTool()

    def __call__(self, state: AgentState) -> AgentState:
        state = self._tool.annotate(state)
        _set_summary(state, self.node_name, state.debug.get("opportunity_summary", {}))
        return state


def _set_summary(state: AgentState, node_name: str, summary: dict[str, object]) -> None:
    state.debug.setdefault("node_summaries", {})[node_name] = summary
