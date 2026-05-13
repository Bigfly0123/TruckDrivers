from __future__ import annotations

from collections import Counter
from typing import Any

from agent.agent_models import Candidate
from agent.phase3.adapters.legacy_candidate_adapter import LegacyCandidateAdapter
from agent.phase3.agent_state import AgentState


class CandidateTool:
    """Phase 3 deterministic candidate tool.

    This is the stable interface used by graph nodes. During Phase 3.0.5 it
    delegates to LegacyCandidateAdapter without changing candidate behavior.
    """

    def __init__(self) -> None:
        self._legacy = LegacyCandidateAdapter()

    def build_candidates(self, state: AgentState) -> AgentState:
        state.raw_candidates = self._legacy.build(state)
        summary = self.summarize_raw_candidates(state.raw_candidates)
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
            "candidate_source_counts": dict(source_counts),
        }
