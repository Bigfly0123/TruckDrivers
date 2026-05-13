from __future__ import annotations

from agent.phase3.adapters.legacy_preference_adapter import LegacyPreferenceAdapter
from agent.phase3.agent_state import AgentState
from simkit.ports import SimulationApiPort


class PreferenceNode:
    node_name = "preference_node"

    def __init__(self, api: SimulationApiPort) -> None:
        self._adapter = LegacyPreferenceAdapter(api)

    def __call__(self, state: AgentState) -> AgentState:
        # Phase 3.0 temporary adapter. Future phases may replace semantic
        # interpretation with a dedicated PreferenceInterpreterAgent.
        rules, constraints = self._adapter.compile(list(state.raw_preferences or []))
        state.preference_rules = rules
        state.constraints = constraints
        _set_summary(state, self.node_name, {
            "preference_rule_count": len(rules),
            "constraint_count": len(constraints),
            "constraint_types": sorted({c.constraint_type for c in constraints}),
        })
        return state


def _set_summary(state: AgentState, node_name: str, summary: dict[str, object]) -> None:
    state.debug.setdefault("node_summaries", {})[node_name] = summary
