from __future__ import annotations

import json
import logging
import re
from typing import Any

from agent.phase3.agent_state import AgentState
from agent.phase3.planning.day_plan import DayPlan
from agent.phase3.utils.summaries import hard_invalid_reason_counts
from simkit.ports import SimulationApiPort


class StrategicPlannerAgent:
    """Creates day-level guidance without choosing executable actions."""

    def __init__(self, api: SimulationApiPort | None = None) -> None:
        self._api = api
        self._logger = logging.getLogger("agent.phase3.strategic_planner")

    def plan_day(self, state: AgentState) -> DayPlan:
        if self._api is None:
            return self._fallback_plan(state, "planner_api_unavailable")
        try:
            payload = self._build_payload(state)
            response = self._api.model_chat_completion(payload)
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "{}")
            data = json.loads(_extract_json(content))
            return self._parse_plan(state, data)
        except Exception as exc:
            self._logger.warning("strategic planner failed: %s", exc)
            return self._fallback_plan(state, "planner_parse_or_api_error")

    def _build_payload(self, state: AgentState) -> dict[str, Any]:
        system_prompt = (
            "You are the StrategicPlannerAgent for a truck driver decision graph.\n"
            "Create a compact day-level strategy plan. Do not choose cargo_id, "
            "candidate_id, or any executable action.\n\n"
            "BOUNDARIES:\n"
            "1. You only provide strategic guidance for the Advisor.\n"
            "2. The Advisor must still choose an existing candidate_id.\n"
            "3. Hard constraints and SafetyGate override this plan.\n"
            "4. Do not invent facts, cargos, coordinates, or rules.\n"
            "5. Keep text short and generalizable.\n\n"
            "OUTPUT FORMAT: Strict JSON with keys: strategy_summary, primary_goal, "
            "secondary_goals, risk_focus, constraint_priorities, rest_strategy, "
            "work_window_strategy, location_strategy, cargo_strategy, avoid_behaviors, "
            "advisor_guidance, confidence, reason."
        )
        user_content = self._build_summary(state)
        return {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_content, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
        }

    def _build_summary(self, state: AgentState) -> dict[str, Any]:
        constraint_summary = state.debug.get("constraint_summary", {})
        runtime_summary = state.debug.get("runtime_summary", {})
        diagnosis = state.debug.get("decision_diagnosis", {})
        hard_counts = hard_invalid_reason_counts(state.hard_invalid_candidates)
        return {
            "driver_id": state.driver_id,
            "day": state.current_day,
            "current_time": state.current_time,
            "minute_of_day": state.current_time % 1440 if state.current_time is not None else None,
            "current_location": state.current_location,
            "preference_summary": [str(p) for p in list(state.raw_preferences or [])[:8]],
            "constraint_types": sorted({getattr(c, "kind", "") for c in state.constraints if getattr(c, "kind", "")}),
            "runtime_summary": runtime_summary,
            "recent_action_summary": _recent_action_summary(state),
            "candidate_summary": {
                "visible_cargo_count": len(state.visible_cargo),
                "raw_candidate_count": len(state.raw_candidates),
                "valid_count": len(state.valid_candidates),
                "soft_risk_count": len(state.soft_risk_candidates),
                "hard_invalid_count": len(state.hard_invalid_candidates),
                "valid_order_count": constraint_summary.get("valid_order_count"),
                "valid_profitable_order_count": constraint_summary.get("valid_profitable_order_count"),
                "best_valid_order_net": constraint_summary.get("best_valid_order_net"),
                "dominant_hard_invalid_reason": constraint_summary.get("dominant_hard_invalid_reason"),
                "top_hard_invalid_reasons": hard_counts,
            },
            "diagnostic_summary": {
                "advisor_chose_wait_despite_profitable_order": diagnosis.get("advisor_chose_wait_despite_profitable_order"),
                "candidate_pool_empty": diagnosis.get("candidate_pool_empty"),
                "only_wait_candidates_available": diagnosis.get("only_wait_candidates_available"),
            },
        }

    def _parse_plan(self, state: AgentState, data: dict[str, Any]) -> DayPlan:
        return DayPlan(
            driver_id=state.driver_id,
            day=int(state.current_day or 0),
            strategy_summary=_string(data.get("strategy_summary"), "Balance income with hard constraints."),
            primary_goal=_string(data.get("primary_goal"), "balance_income_and_constraints"),
            secondary_goals=_string_list(data.get("secondary_goals")),
            risk_focus=_string_list(data.get("risk_focus")),
            constraint_priorities=_string_list(data.get("constraint_priorities")),
            rest_strategy=_optional_string(data.get("rest_strategy")),
            work_window_strategy=_optional_string(data.get("work_window_strategy")),
            location_strategy=_optional_string(data.get("location_strategy")),
            cargo_strategy=_optional_string(data.get("cargo_strategy")),
            avoid_behaviors=_string_list(data.get("avoid_behaviors")),
            advisor_guidance=_string_list(data.get("advisor_guidance")),
            confidence=_confidence(data.get("confidence")),
            reason=_optional_string(data.get("reason")),
            raw_response=data,
        )

    def _fallback_plan(self, state: AgentState, reason: str) -> DayPlan:
        return DayPlan(
            driver_id=state.driver_id,
            day=int(state.current_day or 0),
            strategy_summary="Use profitable legal candidates while preserving recovery paths for active constraints.",
            primary_goal="balance_income_and_constraints",
            secondary_goals=["avoid_hard_constraint_violation", "reduce_unnecessary_wait"],
            risk_focus=_fallback_risk_focus(state),
            constraint_priorities=["hard_constraints_first", "compare_profit_against_penalty_exposure"],
            rest_strategy="Prefer profitable valid orders over partial rest while rest remains feasible later.",
            work_window_strategy="Avoid candidates that enter prohibited work windows.",
            location_strategy="Prefer candidates that keep future legal options available.",
            cargo_strategy="Prefer profitable valid cargo candidates over idle actions when constraints allow.",
            avoid_behaviors=["do_not_wait_when_profitable_valid_orders_exist_without_reason"],
            advisor_guidance=[
                "Choose only from the provided candidate_id list.",
                "Prefer profitable valid orders when hard constraints and penalty exposure allow.",
                "Choose wait when no profitable acceptable order exists or a wait candidate clearly avoids penalty.",
            ],
            confidence=0.35,
            reason=reason,
            raw_response=None,
            fallback_used=True,
        )


def _extract_json(content: str) -> str:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    return text or "{}"


def _recent_action_summary(state: AgentState) -> list[dict[str, Any]]:
    if state.decision_state is None:
        return []
    result: list[dict[str, Any]] = []
    for record in state.decision_state.history_records[-5:]:
        result.append({
            "action": str(record.get("action") or record.get("action_name") or ""),
            "minute": record.get("minute") or record.get("simulation_minute"),
        })
    return result


def _fallback_risk_focus(state: AgentState) -> list[str]:
    risks = [getattr(c, "kind", "") for c in state.constraints if getattr(c, "kind", "")]
    return sorted({str(r) for r in risks})[:5]


def _string(value: Any, default: str) -> str:
    text = str(value or "").strip()
    return text[:500] if text else default


def _optional_string(value: Any) -> str | None:
    text = str(value or "").strip()
    return text[:500] if text else None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:8]:
        text = str(item or "").strip()
        if text:
            result.append(text[:300])
    return result


def _confidence(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, number))
