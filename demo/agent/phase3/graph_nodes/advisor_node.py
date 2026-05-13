from __future__ import annotations

from agent.phase3.agent_state import AgentState
from agent.phase3.tools.advisor_tool import AdvisorTool
from simkit.ports import SimulationApiPort


class AdvisorNode:
    node_name = "advisor_node"

    def __init__(self, api: SimulationApiPort) -> None:
        self._tool = AdvisorTool(api)

    def __call__(self, state: AgentState) -> AgentState:
        state = self._tool.decide(state)
        _set_summary(state, self.node_name, state.debug.get("advisor_summary", {}))
        return state


def _set_summary(state: AgentState, node_name: str, summary: dict[str, object]) -> None:
    state.debug.setdefault("node_summaries", {})[node_name] = summary
