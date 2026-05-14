from __future__ import annotations

from collections import Counter
from typing import Any

from agent.phase3.goals.goal_schema import Goal, GoalProgress


def summarize_goal_layer(
    *,
    goals: list[Goal],
    progress_by_goal: dict[str, GoalProgress],
    materializer_diagnostics: list[dict[str, Any]],
    goal_candidate_count: int,
) -> dict[str, Any]:
    type_counts = Counter(goal.goal_type for goal in goals)
    stuck = [
        {
            "goal_id": progress.goal_id,
            "current_step_index": progress.current_step_index,
            "repeated_step_action_count": progress.repeated_step_action_count,
        }
        for progress in progress_by_goal.values()
        if progress.stuck_suspected
    ]
    failure_counts = Counter(
        str(item.get("reason") or item.get("status") or "unknown")
        for item in materializer_diagnostics
        if item.get("level") in {"warning", "error"} or item.get("status") not in {None, "materialized"}
    )
    return {
        "active_goal_count": len(goals),
        "active_goal_types": dict(type_counts),
        "goal_candidate_count": goal_candidate_count,
        "goal_materialization_diagnostic_count": len(materializer_diagnostics),
        "goal_materialization_failures": dict(failure_counts),
        "stuck_goal_count": len(stuck),
        "stuck_goals": stuck[:5],
    }
