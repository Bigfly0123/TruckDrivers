from __future__ import annotations

from agent.phase3.adapters.legacy_preference_adapter import LegacyPreferenceAdapter
from agent.phase3.agent_state import AgentState
from simkit.ports import SimulationApiPort


class PreferenceTool:
    """Phase 3 deterministic preference tool.

    Adapter = temporary bridge to legacy implementation. Future phases may
    insert a PreferenceInterpreterAgent before or instead of this adapter.
    """

    def __init__(self, api: SimulationApiPort) -> None:
        self._legacy = LegacyPreferenceAdapter(api)

    def build_constraints(self, state: AgentState) -> AgentState:
        rules, constraints = self._legacy.compile(list(state.raw_preferences or []))
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
