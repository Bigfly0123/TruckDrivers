from __future__ import annotations

import hashlib
from typing import Any

from agent.phase3.agent_state import AgentState
from agent.phase3.memory.memory_schema import FailurePattern


class FailurePatternExtractor:
    def extract_from_state(self, state: AgentState) -> list[FailurePattern]:
        diagnosis = state.debug.get("decision_diagnosis", {})
        if not isinstance(diagnosis, dict):
            diagnosis = {}
        goal_summary = state.debug.get("goal_summary", {})
        if not isinstance(goal_summary, dict):
            goal_summary = {}

        patterns: list[FailurePattern] = []
        patterns.extend(self._profitable_order_but_wait(state, diagnosis))
        patterns.extend(self._rest_over_profit(state, diagnosis))
        patterns.extend(self._goal_overuse(state))
        patterns.extend(self._ordered_step_regression(state, goal_summary))
        patterns.extend(self._reached_but_left_window(state, goal_summary))
        patterns.extend(self._specific_cargo_unavailable(state, goal_summary))
        return patterns

    def _profitable_order_but_wait(self, state: AgentState, diagnosis: dict[str, Any]) -> list[FailurePattern]:
        if not diagnosis.get("advisor_chose_wait_despite_profitable_order"):
            return []
        best_net = _float(diagnosis.get("best_valid_order_net"))
        if best_net < 300:
            return []
        return [self._pattern(
            state,
            "profitable_order_but_wait",
            "high" if best_net >= 800 else "medium",
            {
                "best_valid_order_net": best_net,
                "selected_candidate_source": state.debug.get("advisor_summary", {}).get("selected_candidate_source"),
            },
            "Recent decision waited while a profitable valid order was available.",
            "When a profitable valid order is available and goal urgency is not critical, weigh freight income before choosing idle wait.",
            0.8,
        )]

    def _rest_over_profit(self, state: AgentState, diagnosis: dict[str, Any]) -> list[FailurePattern]:
        if not diagnosis.get("profitable_valid_order_but_selected_rest"):
            return []
        cost = _float(diagnosis.get("rest_opportunity_cost"))
        return [self._pattern(
            state,
            "rest_over_profit",
            "high" if cost >= 800 else "medium",
            {"rest_opportunity_cost": cost},
            "Recent decision favored non-urgent rest over profitable freight.",
            "Treat rest progress as optional unless must_do_now is true or penalty risk exceeds the visible freight opportunity.",
            0.85,
        )]

    def _goal_overuse(self, state: AgentState) -> list[FailurePattern]:
        selected = state.selected_candidate
        if selected is None or selected.source != "goal_satisfy":
            return []
        urgency = str(selected.facts.get("urgency") or "")
        if urgency not in {"low", "medium"}:
            return []
        return [self._pattern(
            state,
            "goal_overuse",
            "medium",
            {"goal_type": selected.facts.get("goal_type"), "urgency": urgency},
            "Recent decision selected low or medium urgency goal progress.",
            "Low and medium urgency goal candidates are advisory progress; compare them against available revenue before selecting.",
            0.7,
        )]

    def _ordered_step_regression(self, state: AgentState, goal_summary: dict[str, Any]) -> list[FailurePattern]:
        count = int(goal_summary.get("ordered_steps_regression_count") or 0)
        if count <= 0:
            return []
        return [self._pattern(
            state,
            "ordered_step_regression",
            "high",
            {"ordered_steps_regression_count": count},
            "Ordered-step progress showed a possible regression.",
            "Keep completed ordered steps stable; prefer candidates that continue the current step instead of revisiting earlier steps.",
            0.8,
        )]

    def _reached_but_left_window(self, state: AgentState, goal_summary: dict[str, Any]) -> list[FailurePattern]:
        hold_count = int(goal_summary.get("hold_candidate_generated_count") or 0)
        selected = state.selected_candidate
        if hold_count <= 0 or selected is None:
            return []
        if selected.facts.get("step_type") == "hold_location_until_time":
            return []
        return [self._pattern(
            state,
            "reached_but_left_window",
            "medium",
            {"hold_candidate_generated_count": hold_count},
            "A hold-location candidate existed but another candidate was selected.",
            "When a hold-location candidate is active near a deadline window, account for the penalty of leaving early.",
            0.65,
        )]

    def _specific_cargo_unavailable(self, state: AgentState, goal_summary: dict[str, Any]) -> list[FailurePattern]:
        failures = goal_summary.get("goal_materialization_failures")
        if not isinstance(failures, dict) or int(failures.get("target_cargo_not_visible") or 0) <= 0:
            return []
        return [self._pattern(
            state,
            "specific_cargo_unavailable",
            "medium",
            {"target_cargo_not_visible_count": int(failures.get("target_cargo_not_visible") or 0)},
            "A specific-cargo goal was active but the target cargo was not visible.",
            "Do not assume the specific cargo can be executed until a full visible cargo candidate exists.",
            0.7,
        )]

    def _pattern(
        self,
        state: AgentState,
        failure_type: str,
        severity: str,
        evidence: dict[str, Any],
        summary: str,
        suggested_hint: str,
        confidence: float,
    ) -> FailurePattern:
        selected = state.selected_candidate
        goal_id = str(selected.facts.get("goal_id")) if selected and selected.facts.get("goal_id") else None
        goal_type = str(selected.facts.get("goal_type")) if selected and selected.facts.get("goal_type") else None
        pattern_id = _pattern_id(state.driver_id, state.step_id, failure_type, goal_type)
        return FailurePattern(
            pattern_id=pattern_id,
            driver_id=state.driver_id,
            day_index=state.current_day,
            goal_id=goal_id,
            goal_type=goal_type,
            failure_type=failure_type,
            severity=severity,
            evidence=evidence,
            summary=summary,
            suggested_hint=suggested_hint,
            confidence=confidence,
        )


def _pattern_id(driver_id: str, step_id: int | None, failure_type: str, goal_type: str | None) -> str:
    raw = f"{driver_id}:{step_id}:{failure_type}:{goal_type or ''}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
