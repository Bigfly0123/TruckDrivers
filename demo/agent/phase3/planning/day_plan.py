from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

DEFAULT_STRATEGY_SUMMARY_CN = "今天在严格遵守硬约束和 SafetyGate 的前提下，优先选择有利润的合法候选，并避免不必要的等待。"
DEFAULT_PRIMARY_GOAL_CN = "在满足硬约束的前提下提升当日收益"
DEFAULT_RISK_FOCUS_CN = ["硬约束", "候选可行性", "收益与等待权衡"]
DEFAULT_REST_STRATEGY_CN = "部分休息只是进度，不等于已经避免罚金；如果存在有利润的合法订单且后续仍可完成必要休息，不应机械优先部分休息。"
DEFAULT_ADVISOR_GUIDANCE_CN = [
    "最终动作必须从候选 candidate_id 中选择，不能发明动作。",
    "如果存在有利润的合法订单，且接单后仍可满足关键约束，应优先考虑订单而不是等待或部分休息。",
    "只有当没有有利润的可接受订单，或接单会导致关键约束无法完成时，才优先选择等待或休息。",
    "任何情况下都不能为了收益违反硬约束或绕过 SafetyGate。",
]

RISK_LABELS_CN = {
    "continuous_rest": "连续休息",
    "operate_within_area": "硬约束区域",
    "be_at_location_by_deadline": "按时到达指定地点",
    "forbid_action_in_time_window": "时间窗口",
    "constraint_forbid_action_in_time_window": "时间窗口",
    "forbid_cargo_category": "禁运品类",
    "specific_cargo": "指定货源",
    "max_distance": "最大距离",
    "constraint_max_distance": "最大距离",
    "load_time_window": "装货时间窗",
    "load_time_window_expired": "装货时间窗",
    "load_time_window_unreachable": "装货时间窗",
    "end_month_unreachable": "月底可达性",
}


@dataclass
class DayPlan:
    driver_id: str
    day: int
    strategy_summary: str
    primary_goal: str
    secondary_goals: list[str] = field(default_factory=list)
    risk_focus: list[str] = field(default_factory=list)
    constraint_priorities: list[str] = field(default_factory=list)
    rest_strategy: str | None = None
    work_window_strategy: str | None = None
    location_strategy: str | None = None
    cargo_strategy: str | None = None
    avoid_behaviors: list[str] = field(default_factory=list)
    advisor_guidance: list[str] = field(default_factory=list)
    confidence: float | None = None
    reason: str | None = None
    raw_response: dict[str, Any] | None = None
    fallback_used: bool = False
    language: str = "zh"

    def normalize(self, context: dict[str, Any] | None = None) -> "DayPlan":
        context = context or {}
        self.strategy_summary = _ensure_zh_text(self.strategy_summary, DEFAULT_STRATEGY_SUMMARY_CN)
        self.primary_goal = _ensure_zh_text(self.primary_goal, DEFAULT_PRIMARY_GOAL_CN)
        self.secondary_goals = _normalize_text_list(self.secondary_goals, limit=5)
        self.risk_focus = _normalize_risk_focus(self.risk_focus, context)
        self.constraint_priorities = _normalize_text_list(self.constraint_priorities, limit=5)
        self.rest_strategy = _normalize_optional_text(self.rest_strategy)
        self.work_window_strategy = _normalize_optional_text(self.work_window_strategy)
        self.location_strategy = _normalize_optional_text(self.location_strategy)
        self.cargo_strategy = _normalize_optional_text(self.cargo_strategy)
        self.avoid_behaviors = _normalize_text_list(self.avoid_behaviors, limit=5)
        self.advisor_guidance = _normalize_guidance(self.advisor_guidance)
        if _contains_continuous_rest(self.risk_focus, context):
            self.rest_strategy = _merge_rest_strategy(self.rest_strategy)
        self.reason = _normalize_optional_text(self.reason)
        self.language = "zh"
        return self

    def to_advisor_context(self) -> dict[str, Any]:
        return {
            "strategy_summary": self.strategy_summary,
            "primary_goal": self.primary_goal,
            "risk_focus": list(self.risk_focus),
            "constraint_priorities": list(self.constraint_priorities),
            "rest_strategy": self.rest_strategy,
            "work_window_strategy": self.work_window_strategy,
            "location_strategy": self.location_strategy,
            "cargo_strategy": self.cargo_strategy,
            "avoid_behaviors": list(self.avoid_behaviors),
            "advisor_guidance": list(self.advisor_guidance),
            "confidence": self.confidence,
            "reason": self.reason,
            "fallback_used": self.fallback_used,
            "language": self.language,
        }

    def to_summary(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("raw_response", None)
        return data


def _ensure_zh_text(value: Any, default: str) -> str:
    text = _clean_text(value)
    if not text or not _looks_zh(text):
        return default
    return text


def _normalize_optional_text(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    return text if _looks_zh(text) else None


def _normalize_text_list(values: list[str], limit: int) -> list[str]:
    result: list[str] = []
    for value in values[:limit]:
        text = _clean_text(value)
        if text and _looks_zh(text):
            result.append(text)
    return result


def _normalize_guidance(values: list[str]) -> list[str]:
    result = _normalize_text_list(values, limit=5)
    for default in DEFAULT_ADVISOR_GUIDANCE_CN:
        if len(result) >= 3:
            break
        if default not in result:
            result.append(default)
    return result[:5]


def _normalize_risk_focus(values: list[str], context: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = _risk_label(value)
        if text and text not in result:
            result.append(text)
    for value in _risk_values_from_context(context):
        text = _risk_label(value)
        if text and text not in result:
            result.append(text)
        if len(result) >= 5:
            break
    if not result:
        result = list(DEFAULT_RISK_FOCUS_CN)
    return result[:5]


def _risk_values_from_context(context: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("dominant_hard_invalid_reason", "constraint_types"):
        raw = context.get(key)
        if isinstance(raw, list):
            values.extend(str(v) for v in raw)
        elif raw:
            values.append(str(raw))
    hard_counts = context.get("hard_invalid_reason_counts")
    if isinstance(hard_counts, dict):
        values.extend(str(k) for k in hard_counts)
    runtime = context.get("runtime_summary")
    if isinstance(runtime, dict) and runtime.get("rest_max_streak_today") is not None:
        values.append("continuous_rest")
    diagnostics = context.get("diagnostic_summary")
    if isinstance(diagnostics, dict):
        if diagnostics.get("only_wait_candidates_available"):
            values.append("候选可行性")
        if diagnostics.get("advisor_chose_wait_despite_profitable_order"):
            values.append("收益与等待权衡")
    return values


def _risk_label(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return RISK_LABELS_CN.get(raw, raw if _looks_zh(raw) else "")


def _contains_continuous_rest(risk_focus: list[str], context: dict[str, Any]) -> bool:
    if any("连续休息" in risk for risk in risk_focus):
        return True
    values = _risk_values_from_context(context)
    return any(str(value) == "continuous_rest" for value in values)


def _merge_rest_strategy(value: str | None) -> str:
    if not value:
        return DEFAULT_REST_STRATEGY_CN
    if "部分休息只是进度" in value:
        return value
    return f"{value} {DEFAULT_REST_STRATEGY_CN}"


def _clean_text(value: Any) -> str:
    text = str(value or "").strip()
    text = text.replace("\n", " ")
    text = _strip_identifier_references(text)
    return " ".join(text.split())[:500]


def _strip_identifier_references(text: str) -> str:
    import re

    text = re.sub(r"\b(candidate_id|cargo_id|order_id)\s*[:=]?\s*[A-Za-z0-9_-]+\b", "候选标识", text)
    text = re.sub(r"\b(take_order|wait|reposition)_[A-Za-z0-9_-]+\b", "候选标识", text)
    return text


def _looks_zh(text: str) -> bool:
    cjk_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    latin_count = sum(1 for char in text if ("a" <= char.lower() <= "z"))
    return cjk_count >= 2 and cjk_count >= max(2, latin_count // 2)
