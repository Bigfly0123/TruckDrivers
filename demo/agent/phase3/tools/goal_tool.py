from __future__ import annotations

from typing import Any

from agent.phase3.domain.agent_models import Candidate
from agent.phase3.agent_state import AgentState
from agent.phase3.goals.goal_builder import GoalBuilder
from agent.phase3.goals.goal_diagnostics import summarize_goal_layer
from agent.phase3.goals.goal_materializer import GoalMaterializer
from agent.phase3.goals.goal_progress_engine import GoalProgressEngine


class GoalTool:
    """Builds goal-aware satisfy candidates from compiled constraints."""

    def __init__(self) -> None:
        self._builder = GoalBuilder()
        self._progress = GoalProgressEngine()
        self._materializer = GoalMaterializer()

    def build_goal_candidates(self, state: AgentState, base_candidates: list[Candidate]) -> tuple[list[Candidate], dict[str, Any]]:
        if state.decision_state is None:
            raise ValueError("goal tool requires decision_state")
        goals = self._builder.build(state.constraints)
        progress_by_goal = self._progress.evaluate(
            goals,
            state.decision_state,
            state.constraint_runtime_state,
        )
        goal_candidates, materializer_diagnostics = self._materializer.materialize(
            goals=goals,
            progress_by_goal=progress_by_goal,
            state=state.decision_state,
            runtime=state.constraint_runtime_state,
            base_candidates=base_candidates,
        )
        summary = summarize_goal_layer(
            goals=goals,
            progress_by_goal=progress_by_goal,
            materializer_diagnostics=materializer_diagnostics,
            goal_candidates=goal_candidates,
        )
        state.active_goals = goals
        state.goal_progress = progress_by_goal
        state.goal_candidates = goal_candidates
        state.goal_diagnostics = {
            "materializer": materializer_diagnostics,
            "summary": summary,
        }
        state.tool_summaries["goal_tool"] = summary
        state.debug["goal_summary"] = summary
        return goal_candidates, summary
