from __future__ import annotations

from typing import Any

from agent.phase3.agent_state import AgentState
from agent.phase3.memory.failure_pattern_extractor import FailurePatternExtractor
from agent.phase3.memory.memory_schema import ReflectionHint
from agent.phase3.memory.memory_store import MemoryStore
from agent.phase3.memory.reflection_agent import ReflectionAgent
from agent.phase3.memory.reflection_diagnostics import reflection_summary


class ReflectionTool:
    def __init__(self, store: MemoryStore | None = None) -> None:
        self._store = store or MemoryStore()
        self._extractor = FailurePatternExtractor()
        self._agent = ReflectionAgent()

    def prepare_context(self, state: AgentState) -> AgentState:
        self._store.expire_old_hints(state.current_day)
        hints = self._store.get_active_hints(state.driver_id, state.current_day)
        state.reflection_hints = hints
        context = _hints_to_context(hints)
        state.reflection_context = {
            "hints": context,
            "active_reflection_hint_count": len(hints),
        }
        summary = reflection_summary(active_hints=hints)
        state.tool_summaries["reflection_tool"] = summary
        state.debug["reflection_summary"] = summary
        return state

    def update_memory(self, state: AgentState) -> AgentState:
        failures = self._extractor.extract_from_state(state)
        added_failures = []
        for failure in failures:
            if self._store.add_failure(failure):
                added_failures.append(failure)
        hints = self._agent.generate_hints(added_failures)
        added_hints: list[ReflectionHint] = []
        filtered = 0
        for hint in hints:
            if _has_illegal_fields(hint.message):
                filtered += 1
                continue
            if self._store.add_hint(hint):
                added_hints.append(hint)
        active = self._store.get_active_hints(state.driver_id, state.current_day)
        state.reflection_hints = active
        state.reflection_context = {
            "hints": _hints_to_context(active),
            "active_reflection_hint_count": len(active),
        }
        summary = reflection_summary(
            active_hints=active,
            new_failures=added_failures,
            new_hints=added_hints,
            filtered_illegal_fields=filtered,
        )
        state.tool_summaries["reflection_tool"] = summary
        state.debug["reflection_summary"] = summary
        return state


def _hints_to_context(hints: list[ReflectionHint]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for hint in hints:
        result.append({
            "priority": hint.priority,
            "scope": hint.scope,
            "failure_type": hint.failure_type,
            "message": hint.message,
            "applies_to_goal_type": hint.applies_to_goal_type,
            "confidence": hint.confidence,
        })
    return result


def _has_illegal_fields(message: str) -> bool:
    text = str(message or "")
    return any(token in text for token in ("candidate_id", "cargo_id", "order_id", "final_action"))
