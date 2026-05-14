from __future__ import annotations

from collections import Counter
from typing import Any

from agent.agent_models import Candidate
from agent.phase3.goals.goal_schema import Goal, GoalProgress


def summarize_goal_layer(
    *,
    goals: list[Goal],
    progress_by_goal: dict[str, GoalProgress],
    materializer_diagnostics: list[dict[str, Any]],
    goal_candidates: list[Candidate],
) -> dict[str, Any]:
    type_counts = Counter(goal.goal_type for goal in goals)
    urgency_counts: Counter[str] = Counter()
    must_do_now_count = 0
    hold_candidate_count = 0
    rest_not_urgent_count = 0
    regression_count = 0
    stuck = [
        {
            "goal_id": progress.goal_id,
            "current_step_index": progress.current_step_index,
            "repeated_step_action_count": progress.repeated_step_action_count,
        }
        for progress in progress_by_goal.values()
        if progress.stuck_suspected
    ]
    for progress in progress_by_goal.values():
        if progress.regression_suspected:
            regression_count += 1
    for item in materializer_diagnostics:
        if item.get("reason") == "rest_not_urgent":
            rest_not_urgent_count += 1
    failure_counts = Counter(
        str(item.get("reason") or item.get("status") or "unknown")
        for item in materializer_diagnostics
        if item.get("level") in {"warning", "error"} or item.get("status") not in {None, "materialized"}
    )
    for candidate in goal_candidates:
        urgency = str(candidate.facts.get("urgency") or "unknown")
        urgency_counts[urgency] += 1
        if candidate.facts.get("must_do_now"):
            must_do_now_count += 1
        if candidate.facts.get("step_type") == "hold_location_until_time":
            hold_candidate_count += 1
    return {
        "active_goal_count": len(goals),
        "active_goal_types": dict(type_counts),
        "goal_candidate_count": len(goal_candidates),
        "goal_candidate_urgency_counts": dict(urgency_counts),
        "goal_candidate_must_do_now_count": must_do_now_count,
        "hold_candidate_generated_count": hold_candidate_count,
        "rest_not_urgent_count": rest_not_urgent_count,
        "ordered_steps_regression_count": regression_count,
        "goal_materialization_diagnostic_count": len(materializer_diagnostics),
        "goal_materialization_failures": dict(failure_counts),
        "stuck_goal_count": len(stuck),
        "stuck_goals": stuck[:5],
    }
