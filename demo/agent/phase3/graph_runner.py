from __future__ import annotations

from typing import Callable

from agent.phase3.agent_state import AgentState
from agent.phase3.trace_logger import TraceLogger
from simkit.ports import SimulationApiPort

GraphNode = Callable[[AgentState], AgentState]


class GraphRunner:
    def __init__(self, nodes: list[GraphNode], trace_logger: TraceLogger | None = None) -> None:
        self._nodes = nodes
        self._trace_logger = trace_logger

    def run(self, state: AgentState) -> AgentState:
        try:
            for node in self._nodes:
                node_name = _node_name(node)
                if self._trace_logger:
                    self._trace_logger.node_start(state, node_name)
                try:
                    state = node(state)
                    if self._trace_logger:
                        self._trace_logger.node_end(state, node_name)
                except Exception as exc:
                    state.errors.append({
                        "node": node_name,
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    })
                    if self._trace_logger:
                        self._trace_logger.node_error(state, node_name, exc)
                    raise
            return state
        finally:
            if self._trace_logger and state.final_action is not None:
                self._trace_logger.decision_summary(state)

    def record_decision_summary(self, state: AgentState) -> None:
        if self._trace_logger:
            self._trace_logger.decision_summary(state)


def build_default_graph(api: SimulationApiPort) -> GraphRunner:
    from agent.phase3.agents.strategic_planner_agent import StrategicPlannerAgent
    from agent.phase3.graph_nodes.advisor_node import AdvisorNode
    from agent.phase3.graph_nodes.candidate_node import CandidateNode
    from agent.phase3.graph_nodes.constraint_node import ConstraintNode
    from agent.phase3.graph_nodes.emit_node import EmitNode
    from agent.phase3.graph_nodes.observe_node import ObserveNode
    from agent.phase3.graph_nodes.planning_node import PlanningNode
    from agent.phase3.graph_nodes.preference_node import PreferenceNode
    from agent.phase3.graph_nodes.reflection_node import MemoryUpdateNode, ReflectionNode
    from agent.phase3.graph_nodes.runtime_node import RuntimeNode
    from agent.phase3.graph_nodes.safety_node import SafetyNode
    from agent.phase3.memory.reflection_tool import ReflectionTool
    from agent.phase3.planning.day_plan_store import DayPlanStore

    day_plan_store = DayPlanStore()
    strategic_planner = StrategicPlannerAgent(api)
    reflection_tool = ReflectionTool()

    return GraphRunner(
        nodes=[
            ObserveNode(api),
            PreferenceNode(api),
            RuntimeNode(),
            CandidateNode(),
            ConstraintNode(),
            PlanningNode(strategic_planner, day_plan_store),
            ReflectionNode(reflection_tool),
            AdvisorNode(api),
            SafetyNode(),
            EmitNode(),
            MemoryUpdateNode(reflection_tool),
        ],
        trace_logger=TraceLogger(),
    )


def _node_name(node: GraphNode) -> str:
    explicit = getattr(node, "node_name", None)
    if explicit:
        return str(explicit)
    return getattr(node, "__name__", node.__class__.__name__)
