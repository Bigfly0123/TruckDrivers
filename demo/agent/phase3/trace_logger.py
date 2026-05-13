from __future__ import annotations

import json
import logging
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
        self._write_graph_event(state, "node_start", node_name, {})

    def node_end(self, state: AgentState, node_name: str) -> None:
        summary = state.debug.get("node_summaries", {}).get(node_name, {})
        self._write_graph_event(state, "node_end", node_name, summary)

    def node_error(self, state: AgentState, node_name: str, exc: Exception) -> None:
        self._write_graph_event(
            state,
            "node_error",
            node_name,
            {},
            error={"error_type": type(exc).__name__, "message": str(exc)},
        )

    def decision_summary(self, state: AgentState) -> None:
        summary = final_decision_summary(state)
        self._write_graph_event(state, "final_action_summary", "graph", summary)
        self._write_jsonl(self._decision_path, summary)

    def _write_graph_event(
        self,
        state: AgentState,
        event: str,
        node_name: str,
        summary: dict[str, Any],
        error: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "event": event,
            "node": node_name,
            "driver_id": state.driver_id,
            "step_id": state.step_id,
            "current_day": state.current_day,
            "summary": summary,
        }
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
