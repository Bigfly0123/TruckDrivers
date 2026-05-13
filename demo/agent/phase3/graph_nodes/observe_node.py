from __future__ import annotations

from agent.phase3.agent_state import AgentState
from agent.phase3.tools.simulation_tool import SimulationTool
from simkit.ports import SimulationApiPort


class ObserveNode:
    node_name = "observe_node"

    def __init__(self, api: SimulationApiPort) -> None:
        self._tool = SimulationTool(api)

    def __call__(self, state: AgentState) -> AgentState:
        observed = self._tool.observe(state.driver_id)
        state.driver_status = observed["driver_status"]
        state.visible_cargo = observed["visible_cargo"]
        state.decision_history = observed["decision_history"]
        state.raw_preferences = observed["raw_preferences"]
        state.decision_state = observed["decision_state"]
        state.step_id = observed["step_id"]
        state.current_time = observed["current_time"]
        state.current_day = observed["current_day"]
        state.current_location = observed["current_location"]
        summary = {
            "current_time": state.current_time,
            "current_day": state.current_day,
            "visible_cargo_count": len(state.visible_cargo),
            "history_count": len(state.decision_history),
            "current_location": state.current_location,
        }
        state.tool_summaries["simulation_tool"] = summary
        _set_summary(state, self.node_name, summary)
        return state


def _set_summary(state: AgentState, node_name: str, summary: dict[str, object]) -> None:
    state.debug.setdefault("node_summaries", {})[node_name] = summary
