from __future__ import annotations

from agent.phase3.agent_state import AgentState
from agent.phase3.agents.strategic_planner_agent import StrategicPlannerAgent
from agent.phase3.planning.day_plan_store import DayPlanStore


class PlanningNode:
    node_name = "planning_node"

    def __init__(self, planner: StrategicPlannerAgent, store: DayPlanStore) -> None:
        self._planner = planner
        self._store = store

    def __call__(self, state: AgentState) -> AgentState:
        day = int(state.current_day or 0)
        existing = self._store.get(state.driver_id, day)
        normalize_context = _normalization_context(state)
        if existing is None:
            plan = self._planner.plan_day(state).normalize(normalize_context)
            self._store.set(plan)
            state.day_plan_generated_this_step = True
            event = "day_plan_created"
        else:
            plan = existing.normalize(normalize_context)
            state.day_plan_generated_this_step = False
            event = "day_plan_reused"
        state.day_plan = plan
        summary = {
            "event": event,
            "driver_id": plan.driver_id,
            "day": plan.day,
            "strategy_summary": plan.strategy_summary,
            "primary_goal": plan.primary_goal,
            "risk_focus": list(plan.risk_focus),
            "risk_focus_count": len(plan.risk_focus),
            "advisor_guidance": list(plan.advisor_guidance),
            "advisor_guidance_count": len(plan.advisor_guidance),
            "confidence": plan.confidence,
            "reason": plan.reason,
            "fallback_used": plan.fallback_used,
            "language": plan.language,
        }
        state.debug["planning_summary"] = summary
        state.tool_summaries["strategic_planner_agent"] = summary
        _set_summary(state, self.node_name, summary)
        return state


def _set_summary(state: AgentState, node_name: str, summary: dict[str, object]) -> None:
    state.debug.setdefault("node_summaries", {})[node_name] = summary


def _normalization_context(state: AgentState) -> dict[str, object]:
    constraint_summary = state.debug.get("constraint_summary", {})
    diagnosis = state.debug.get("decision_diagnosis", {})
    return {
        "constraint_types": sorted({getattr(c, "kind", "") for c in state.constraints if getattr(c, "kind", "")}),
        "dominant_hard_invalid_reason": constraint_summary.get("dominant_hard_invalid_reason"),
        "hard_invalid_reason_counts": constraint_summary.get("hard_invalid_reason_counts"),
        "runtime_summary": state.debug.get("runtime_summary", {}),
        "diagnostic_summary": diagnosis,
    }
