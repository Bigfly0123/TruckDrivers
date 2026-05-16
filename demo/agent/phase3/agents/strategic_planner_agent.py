from __future__ import annotations

import json
import logging
from typing import Any

from agent.phase3.agent_state import AgentState
from agent.phase3.planning.day_plan import (
    DEFAULT_ADVISOR_GUIDANCE_CN,
    DEFAULT_PRIMARY_GOAL_CN,
    DEFAULT_REST_STRATEGY_CN,
    DEFAULT_STRATEGY_SUMMARY_CN,
    DayPlan,
)
from agent.phase3.utils.summaries import hard_invalid_reason_counts
from agent.phase3.utils.json_cleaner import loads_json_object
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
            data = self._load_or_repair_plan_json(content, state)
            return self._parse_plan(state, data).normalize(_normalization_context(state))
        except Exception as exc:
            self._logger.warning("strategic planner failed: %s", exc)
            return self._fallback_plan(state, "planner_parse_or_api_error")

    def _build_payload(self, state: AgentState) -> dict[str, Any]:
        system_prompt = (
            "你是货运司机的日级策略规划 Agent。你的任务不是选择具体订单，"
            "而是生成今天给 Advisor 使用的策略指导。\n\n"
            "必须遵守：\n"
            "1. 只输出 JSON，不输出 Markdown 或解释文字。\n"
            "2. JSON 字段名必须使用英文。\n"
            "3. 所有自然语言字段内容必须使用中文。\n"
            "4. 不要输出 candidate_id、cargo_id、order_id 或 final action。\n"
            "5. 不要绕过候选池、硬约束或 SafetyGate。\n"
            "6. advisor_guidance 必须包含 3-5 条具体指导，帮助 Advisor 在候选 candidate_id 之间做取舍。\n"
            "7. risk_focus 必须包含 1-5 个今日主要风险，可来自硬约束、软偏好、候选诊断、主要 hard_invalid 原因或 runtime state。\n"
            "8. 如果存在有利润的合法订单，且接单后仍可满足关键约束，不要建议机械等待或过早部分休息。\n"
            "9. 部分休息只是进度，不等于已经避免罚金。\n"
            "10. 指导必须通用，不得指定具体 candidate_id、cargo_id、order_id 或动作编号。\n\n"
            "输出 JSON keys: strategy_summary, primary_goal, secondary_goals, risk_focus, "
            "constraint_priorities, rest_strategy, work_window_strategy, location_strategy, "
            "cargo_strategy, avoid_behaviors, advisor_guidance, confidence, reason."
        )
        user_content = self._build_summary(state)
        return {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_content, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
        }

    def _load_or_repair_plan_json(self, content: str, state: AgentState) -> dict[str, Any]:
        try:
            return loads_json_object(content)
        except Exception as first_exc:
            self._logger.warning("strategic planner json parse failed, retrying repair: %s", first_exc)
            repair_payload = {
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Repair the malformed planner response into one valid JSON object only. "
                            "Do not add markdown or commentary. Use these keys only: "
                            "strategy_summary, primary_goal, secondary_goals, risk_focus, "
                            "constraint_priorities, rest_strategy, work_window_strategy, "
                            "location_strategy, cargo_strategy, avoid_behaviors, "
                            "advisor_guidance, confidence, reason."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps({
                            "malformed_response": str(content or "")[:4000],
                            "fallback_context": self._build_summary(state),
                        }, ensure_ascii=False),
                    },
                ],
                "response_format": {"type": "json_object"},
            }
            repaired = self._api.model_chat_completion(repair_payload)
            repaired_content = repaired.get("choices", [{}])[0].get("message", {}).get("content", "{}")
            return loads_json_object(repaired_content)

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
                "candidate_generation_empty": diagnosis.get("candidate_generation_empty"),
                "only_wait_candidates_available": diagnosis.get("only_wait_candidates_available"),
            },
        }

    def _parse_plan(self, state: AgentState, data: dict[str, Any]) -> DayPlan:
        return DayPlan(
            driver_id=state.driver_id,
            day=int(state.current_day or 0),
            strategy_summary=_string(data.get("strategy_summary"), DEFAULT_STRATEGY_SUMMARY_CN),
            primary_goal=_string(data.get("primary_goal"), DEFAULT_PRIMARY_GOAL_CN),
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
        plan = DayPlan(
            driver_id=state.driver_id,
            day=int(state.current_day or 0),
            strategy_summary=DEFAULT_STRATEGY_SUMMARY_CN,
            primary_goal=DEFAULT_PRIMARY_GOAL_CN,
            secondary_goals=["避免硬约束违规", "减少不必要等待"],
            risk_focus=_fallback_risk_focus(state),
            constraint_priorities=["硬约束优先", "比较收益与潜在罚分暴露"],
            rest_strategy=DEFAULT_REST_STRATEGY_CN,
            work_window_strategy="避免选择会进入禁行或禁止作业时间窗口的候选。",
            location_strategy="优先保留后续仍可满足位置类约束的候选。",
            cargo_strategy="在约束允许时，优先考虑有利润的合法货源候选。",
            avoid_behaviors=["不要在存在有利润合法订单时无理由等待"],
            advisor_guidance=list(DEFAULT_ADVISOR_GUIDANCE_CN),
            confidence=0.35,
            reason=f"{reason}，使用默认日级策略计划。",
            raw_response=None,
            fallback_used=True,
        )
        return plan.normalize(_normalization_context(state))


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


def _normalization_context(state: AgentState) -> dict[str, Any]:
    constraint_summary = state.debug.get("constraint_summary", {})
    runtime_summary = state.debug.get("runtime_summary", {})
    diagnosis = state.debug.get("decision_diagnosis", {})
    return {
        "constraint_types": sorted({getattr(c, "kind", "") for c in state.constraints if getattr(c, "kind", "")}),
        "dominant_hard_invalid_reason": constraint_summary.get("dominant_hard_invalid_reason"),
        "hard_invalid_reason_counts": constraint_summary.get("hard_invalid_reason_counts") or hard_invalid_reason_counts(state.hard_invalid_candidates),
        "runtime_summary": runtime_summary,
        "diagnostic_summary": diagnosis,
    }


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
