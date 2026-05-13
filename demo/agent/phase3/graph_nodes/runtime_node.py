from __future__ import annotations

from agent.phase3.agent_state import AgentState
from agent.phase3.tools.state_tool import StateTool


class RuntimeNode:
    node_name = "runtime_node"

    def __init__(self) -> None:
        self._tool = StateTool()

    def __call__(self, state: AgentState) -> AgentState:
        state = self._tool.build_runtime_state(state)
        _set_summary(state, self.node_name, state.debug.get("runtime_summary", {}))
        return state


def _set_summary(state: AgentState, node_name: str, summary: dict[str, object]) -> None:
    state.debug.setdefault("node_summaries", {})[node_name] = summary
