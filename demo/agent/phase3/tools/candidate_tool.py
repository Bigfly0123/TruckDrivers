from __future__ import annotations

from collections import Counter
from typing import Any

from agent.agent_models import Candidate
from agent.phase3.adapters.legacy_candidate_adapter import LegacyCandidateAdapter
from agent.phase3.agent_state import AgentState
from agent.phase3.tools.goal_tool import GoalTool


class CandidateTool:
    """Phase 3 deterministic candidate tool.

    This is the stable interface used by graph nodes. During Phase 3.0.5 it
    delegates to LegacyCandidateAdapter without changing candidate behavior.
    """

    def __init__(self) -> None:
        self._legacy = LegacyCandidateAdapter()
        self._goals = GoalTool()

    def build_candidates(self, state: AgentState) -> AgentState:
        legacy_candidates = self._legacy.build(state)
        base_candidates = [c for c in legacy_candidates if c.source != "constraint_satisfy"]
        legacy_satisfy_candidates = [c for c in legacy_candidates if c.source == "constraint_satisfy"]
        goal_candidates, goal_summary = self._goals.build_goal_candidates(state, base_candidates)
        state.base_candidates = base_candidates
        state.legacy_satisfy_candidates = legacy_satisfy_candidates
        state.raw_candidates = base_candidates + goal_candidates
        summary = self.summarize_raw_candidates(state.raw_candidates)
        summary["legacy_constraint_satisfy_candidate_count"] = len(legacy_satisfy_candidates)
        summary["base_candidate_count"] = len(base_candidates)
        summary.update({
            "goal_candidate_count": goal_summary.get("goal_candidate_count", 0),
            "active_goal_count": goal_summary.get("active_goal_count", 0),
            "active_goal_types": goal_summary.get("active_goal_types", {}),
            "goal_materialization_failures": goal_summary.get("goal_materialization_failures", {}),
            "stuck_goal_count": goal_summary.get("stuck_goal_count", 0),
            "goal_candidate_urgency_counts": goal_summary.get("goal_candidate_urgency_counts", {}),
            "goal_candidate_must_do_now_count": goal_summary.get("goal_candidate_must_do_now_count", 0),
            "hold_candidate_generated_count": goal_summary.get("hold_candidate_generated_count", 0),
            "rest_not_urgent_count": goal_summary.get("rest_not_urgent_count", 0),
            "ordered_steps_regression_count": goal_summary.get("ordered_steps_regression_count", 0),
        })
        state.tool_summaries["candidate_tool"] = summary
        state.debug["candidate_summary"] = summary
        return state

    def summarize_raw_candidates(self, candidates: list[Candidate]) -> dict[str, Any]:
        action_counts = Counter(c.action for c in candidates)
        source_counts = Counter(c.source or "unknown" for c in candidates)
        return {
            "raw_candidate_count": len(candidates),
            "take_order_candidate_count": action_counts.get("take_order", 0),
            "wait_candidate_count": action_counts.get("wait", 0),
            "reposition_candidate_count": action_counts.get("reposition", 0),
            "constraint_satisfy_candidate_count": source_counts.get("constraint_satisfy", 0),
            "goal_satisfy_candidate_count": source_counts.get("goal_satisfy", 0),
            "candidate_source_counts": dict(source_counts),
        }
