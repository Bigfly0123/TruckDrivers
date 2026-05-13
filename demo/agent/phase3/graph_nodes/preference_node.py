from __future__ import annotations

from agent.phase3.agent_state import AgentState
from agent.phase3.tools.preference_tool import PreferenceTool
from simkit.ports import SimulationApiPort


class PreferenceNode:
    node_name = "preference_node"

    def __init__(self, api: SimulationApiPort) -> None:
        self._tool = PreferenceTool(api)

    def __call__(self, state: AgentState) -> AgentState:
        state = self._tool.build_constraints(state)
        _set_summary(state, self.node_name, state.debug.get("preference_summary", {}))
        return state


def _set_summary(state: AgentState, node_name: str, summary: dict[str, object]) -> None:
    state.debug.setdefault("node_summaries", {})[node_name] = summary
