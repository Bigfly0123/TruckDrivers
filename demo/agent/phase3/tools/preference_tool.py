from __future__ import annotations

from agent.phase3.agent_state import AgentState
from agent.phase3.services.preference_service import PreferenceService
from simkit.ports import SimulationApiPort


class PreferenceTool:
    """Phase 3 deterministic preference tool.

    It compiles raw driver preferences into general constraints. It does not
    make action choices.
    """

    def __init__(self, api: SimulationApiPort) -> None:
        self._service = PreferenceService(api)

    def build_constraints(self, state: AgentState) -> AgentState:
        rules, constraints = self._service.compile(list(state.raw_preferences or []))
        state.preference_rules = rules
        state.constraints = constraints
        summary = {
            "preference_rule_count": len(rules),
            "constraint_count": len(constraints),
            "constraint_types": sorted({c.constraint_type for c in constraints}),
        }
        state.tool_summaries["preference_tool"] = summary
        state.debug["preference_summary"] = summary
        return state
