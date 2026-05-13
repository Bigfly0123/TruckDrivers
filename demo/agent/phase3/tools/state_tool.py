from __future__ import annotations

from agent.constraint_runtime import compute_constraint_runtime_state
from agent.phase3.agent_state import AgentState


class StateTool:
    """Phase 3 deterministic runtime-state tool."""

    def build_runtime_state(self, state: AgentState) -> AgentState:
        if state.decision_state is None:
            raise ValueError("state tool requires decision_state")
        visible_cargo_ids: set[str] = set()
        for item in state.visible_cargo:
            cargo = item.get("cargo") if isinstance(item.get("cargo"), dict) else {}
            cid = str(cargo.get("cargo_id") or "").strip()
            if cid:
                visible_cargo_ids.add(cid)
        runtime = compute_constraint_runtime_state(
            state.decision_state.history_records,
            state.decision_state.current_minute,
            state.constraints,
            visible_cargo_ids,
        )
        state.constraint_runtime_state = runtime
        summary = {
            "has_runtime_state": True,
            "rest_current_streak": runtime.rest.current_rest_streak_minutes,
            "rest_max_streak_today": runtime.rest.max_rest_streak_today,
            "runtime_constraint_count": len(state.constraints),
        }
        state.tool_summaries["state_tool"] = summary
        state.debug["runtime_summary"] = summary
        return state
