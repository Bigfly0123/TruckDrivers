from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.phase3.agent_state import AgentState
from agent.phase3.utils.json_cleaner import clean_for_json
from agent.phase3.utils.summaries import final_decision_summary


class TraceLogger:
    def __init__(self, log_dir: Path | None = None) -> None:
        self._logger = logging.getLogger("agent.phase3.trace")
        self._log_dir = log_dir or Path(__file__).resolve().parents[2] / "results" / "logs"
        self._graph_trace_path = self._log_dir / "agent_graph_trace.jsonl"
        self._decision_path = self._log_dir / "agent_decisions.jsonl"

    def node_start(self, state: AgentState, node_name: str) -> None:
        state.debug.setdefault("_node_start_times", {})[node_name] = time.perf_counter()
        self._write_graph_event(state, "node_start", node_name, {})

    def node_end(self, state: AgentState, node_name: str) -> None:
        summary = state.debug.get("node_summaries", {}).get(node_name, {})
        start = state.debug.get("_node_start_times", {}).pop(node_name, None)
        duration_ms = round((time.perf_counter() - start) * 1000, 2) if start is not None else None
        self._write_graph_event(state, "node_end", node_name, summary, duration_ms=duration_ms)
        tool_name = _tool_name_for_node(node_name)
        if tool_name and tool_name in state.tool_summaries:
            self.tool_summary(state, tool_name, state.tool_summaries[tool_name])
        if node_name == "planning_node":
            planning_summary = state.debug.get("planning_summary", {})
            event = str(planning_summary.get("event") or "planning_summary")
            if event in {"day_plan_created", "day_plan_reused"}:
                self._write_graph_event(state, event, "planning_node", planning_summary)
            self._write_graph_event(state, "planning_summary", "planning_node", planning_summary)
        if node_name in {"reflection_node", "memory_update_node"}:
            self._write_graph_event(state, "reflection_summary", node_name, state.debug.get("reflection_summary", {}))

    def node_error(self, state: AgentState, node_name: str, exc: Exception) -> None:
        self._write_graph_event(
            state,
            "node_error",
            node_name,
            {},
            error={"error_type": type(exc).__name__, "message": str(exc)},
        )

    def tool_summary(self, state: AgentState, tool_name: str, summary: dict[str, Any]) -> None:
        self._write_graph_event(state, "tool_summary", tool_name, summary)

    def decision_diagnosis(self, state: AgentState) -> None:
        diagnosis = state.diagnostics.get("decision_diagnosis", {})
        if diagnosis:
            self._write_graph_event(state, "decision_diagnosis", "diagnostic_tool", diagnosis)

    def decision_summary(self, state: AgentState) -> None:
        summary = final_decision_summary(state)
        self.decision_diagnosis(state)
        self._write_graph_event(state, "final_action_summary", "graph", summary)
        self._write_jsonl(self._decision_path, summary)

    def _write_graph_event(
        self,
        state: AgentState,
        event: str,
        node_name: str,
        summary: dict[str, Any],
        error: dict[str, Any] | None = None,
        duration_ms: float | None = None,
    ) -> None:
        payload = {
            "event": event,
            "node": node_name,
            "run_id": state.request_id,
            "driver_id": state.driver_id,
            "step_id": state.step_id,
            "current_day": state.current_day,
            "current_time": state.current_time,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
        }
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        if error is not None:
            payload["error"] = error
        state.trace.append(payload)
        self._write_jsonl(self._graph_trace_path, payload)

    def _write_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        try:
            self._log_dir.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(clean_for_json(payload), ensure_ascii=False, default=str) + "\n")
        except Exception as exc:
            self._logger.warning("failed to write phase3 trace: %s", exc)


def _tool_name_for_node(node_name: str) -> str | None:
    return {
        "observe_node": "simulation_tool",
        "preference_node": "preference_tool",
        "runtime_node": "state_tool",
        "candidate_node": "candidate_tool",
        "constraint_node": "constraint_tool",
        "planning_node": "strategic_planner_agent",
        "reflection_node": "reflection_tool",
        "memory_update_node": "reflection_tool",
        "advisor_node": "advisor_tool",
        "safety_node": "safety_tool",
        "emit_node": "diagnostic_tool",
    }.get(node_name)
