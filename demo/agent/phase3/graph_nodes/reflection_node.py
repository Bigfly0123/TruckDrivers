from __future__ import annotations

from agent.phase3.agent_state import AgentState
from agent.phase3.memory.reflection_tool import ReflectionTool


class ReflectionNode:
    node_name = "reflection_node"

    def __init__(self, tool: ReflectionTool) -> None:
        self._tool = tool

    def __call__(self, state: AgentState) -> AgentState:
        state = self._tool.prepare_context(state)
        _set_summary(state, self.node_name, state.debug.get("reflection_summary", {}))
        return state


class MemoryUpdateNode:
    node_name = "memory_update_node"

    def __init__(self, tool: ReflectionTool) -> None:
        self._tool = tool

    def __call__(self, state: AgentState) -> AgentState:
        state = self._tool.update_memory(state)
        _set_summary(state, self.node_name, state.debug.get("reflection_summary", {}))
        return state


def _set_summary(state: AgentState, node_name: str, summary: dict[str, object]) -> None:
    state.debug.setdefault("node_summaries", {})[node_name] = summary
