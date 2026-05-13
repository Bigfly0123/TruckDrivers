from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from agent.agent_models import Candidate, DecisionState, PreferenceRule

_SIMULATION_EPOCH = datetime(2026, 3, 1, 0, 0, 0)


def _minute_to_wall_time(minute: int) -> str:
    dt = _SIMULATION_EPOCH + timedelta(minutes=int(minute))
    return dt.strftime("%Y-%m-%d %H:%M")


@dataclass(frozen=True)
class CandidateSummary:
    candidate_id: str
    action: str
    estimated_net: float = 0.0
    estimated_penalty_exposure: float = 0.0
    estimated_net_after_penalty: float = 0.0
    satisfies_constraints: bool = True
    soft_risk_reasons: tuple[str, ...] = ()
    constraint_impacts: tuple[dict[str, Any], ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdvisorContext:
    state: DecisionState
    rules: tuple[PreferenceRule, ...]
    valid_candidates: list[Candidate]
    soft_risk_candidates: list[Candidate]
    raw_preferences: list[str]
    recent_actions: list[dict[str, Any]] = field(default_factory=list)
    trigger_reason: str = "normal_candidate_decision"
    candidate_summaries: dict[str, CandidateSummary] = field(default_factory=dict)


@dataclass(frozen=True)
class AdvisorDecision:
    selected_candidate_id: str
    reason: str = ""
    accepted_risks: tuple[str, ...] = ()


class LlmDecisionAdvisor:
    def __init__(self, api: Any | None) -> None:
        self._api = api
        self._logger = logging.getLogger("agent.llm_decision_advisor")

    def advise(self, context: AdvisorContext) -> AdvisorDecision | None:
        if self._api is None:
            return None
        try:
            return self._call_llm(context)
        except Exception as exc:
            self._logger.warning("LLM advisor failed: %s", exc)
            return None

    def _call_llm(self, context: AdvisorContext) -> AdvisorDecision | None:
        payload = self._build_payload(context)
        response = self._api.model_chat_completion(payload)
        content = response.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        data = json.loads(self._extract_json(content))
        return self._parse_decision(data, context)

    def _build_payload(self, context: AdvisorContext) -> dict[str, Any]:
        system_prompt = (
            "You are a logistics decision advisor for a truck driver simulator.\n\n"
            "ROLE: Choose exactly one candidate_id from the provided list.\n\n"
            "CRITICAL RULES:\n"
            "1. You MUST select a candidate_id from the candidates list.\n"
            "2. Do NOT invent candidate_ids that are not in the list.\n"
            "3. valid_candidates are safe to choose.\n"
            "4. soft_risk_candidates have preference risks but may still be profitable.\n"
            "5. You may choose a soft_risk candidate if the profit justifies the risk.\n"
            "6. If no profitable option exists, choose a wait candidate.\n"
            "7. Active missions with high penalties should influence your decision.\n"
            "8. Keep reason under 100 characters.\n\n"
            "CONSTRAINT-AWARENESS:\n"
            "- Each candidate may have constraint_impacts showing which preferences it affects.\n"
            "- estimated_net_after_penalty = profit minus potential penalty exposure.\n"
            "- penalty_exposure is the total potential cost from violating soft preferences.\n"
            "- satisfies_constraints=false means at least one preference is at risk.\n"
            "- Candidates with source='constraint_satisfy' are generated to satisfy specific preferences.\n"
            "- Some wait/reposition candidates are NOT idle actions; they may satisfy constraints and avoid penalties.\n"
            "- Compare order profit against penalty exposure and penalty avoidance.\n"
            "- Choose the candidate with the best expected net outcome, not simply the highest immediate freight income.\n"
            "- Prefer candidates with lower penalty_exposure when profits are similar.\n\n"
            "CONTINUOUS REST:\n"
            "- A rest candidate may be partial progress, not full satisfaction.\n"
            "- actually_satisfies_after_this_wait=false means this wait extends the streak but does not satisfy the full continuous-rest requirement yet.\n"
            "- Compare remaining rest need against cargo opportunity cost.\n\n"
            "OUTPUT FORMAT: Strict JSON:\n"
            '{\n'
            '  "selected_candidate_id": "string",\n'
            '  "reason": "string",\n'
            '  "accepted_risks": ["string"]\n'
            '}\n'
        )

        state = context.state

        def _build_desc(c: Candidate) -> dict[str, Any]:
            desc: dict[str, Any] = {
                "candidate_id": c.candidate_id,
                "action": c.action,
                "source": c.source,
            }
            summary = context.candidate_summaries.get(c.candidate_id)
            if summary:
                desc["estimated_net_after_penalty"] = summary.estimated_net_after_penalty
                desc["penalty_exposure"] = summary.estimated_penalty_exposure
                desc["satisfies_constraints"] = summary.satisfies_constraints
                if summary.constraint_impacts:
                    desc["constraint_impacts"] = list(summary.constraint_impacts)
            if c.action == "take_order":
                desc["cargo_id"] = c.params.get("cargo_id", "")
                desc["price"] = c.facts.get("price", 0)
                desc["estimated_net"] = c.facts.get("estimated_net", 0)
                desc["pickup_deadhead_km"] = c.facts.get("pickup_deadhead_km", 0)
                desc["haul_distance_km"] = c.facts.get("haul_distance_km", 0)
            elif c.action == "wait":
                desc["duration_minutes"] = c.params.get("duration_minutes", 0)
                if c.facts.get("satisfies_constraint_type") == "continuous_rest":
                    desc["satisfies_constraint_type"] = "continuous_rest"
                    desc["satisfy_status"] = c.facts.get("satisfy_status")
                    desc["current_rest_streak_minutes"] = c.facts.get("current_rest_streak_minutes", 0)
                    desc["max_rest_streak_today"] = c.facts.get("max_rest_streak_today", 0)
                    desc["required_rest_minutes"] = c.facts.get("required_minutes", 0)
                    desc["rest_streak_after_wait"] = c.facts.get("rest_streak_after_wait", 0)
                    desc["remaining_rest_minutes_after_wait"] = c.facts.get("remaining_rest_minutes_after_wait", 0)
                    desc["actually_satisfies_after_this_wait"] = bool(c.facts.get("actually_satisfies_after_this_wait"))
                    desc["penalty_if_rest_not_completed"] = c.facts.get("penalty_if_rest_not_completed", 0)
                if c.facts.get("avoids_estimated_penalty"):
                    desc["avoids_estimated_penalty"] = c.facts.get("avoids_estimated_penalty")
                if c.facts.get("remaining_rest_minutes") is not None:
                    desc["remaining_rest_minutes"] = c.facts.get("remaining_rest_minutes")
                if c.facts.get("window_end_minute") is not None:
                    desc["window_end_minute"] = c.facts.get("window_end_minute")
            elif c.action == "reposition":
                desc["latitude"] = c.params.get("latitude")
                desc["longitude"] = c.params.get("longitude")
                if c.facts.get("penalty_if_missed"):
                    desc["penalty_if_missed"] = c.facts.get("penalty_if_missed")
                if c.facts.get("deadline_minute"):
                    desc["deadline_minute"] = c.facts.get("deadline_minute")
            if c.facts.get("satisfies_constraint_type"):
                desc["satisfies_constraint_type"] = c.facts.get("satisfies_constraint_type")
            return desc

        valid_desc = [_build_desc(c) for c in context.valid_candidates]
        soft_desc = []
        for c in context.soft_risk_candidates:
            desc = _build_desc(c)
            desc["risk_reasons"] = list(c.soft_risk_reasons)
            soft_desc.append(desc)

        user_content = {
            "trigger_reason": context.trigger_reason,
            "current_time": _minute_to_wall_time(state.current_minute),
            "location": {"lat": round(state.current_latitude, 4), "lng": round(state.current_longitude, 4)},
            "day_of_month": state.current_day + 1,
            "remaining_days": max(0, state.simulation_duration_days - state.current_day),
            "completed_orders": state.completed_order_count,
            "monthly_deadhead_km": round(state.monthly_deadhead_km, 1),
            "preferences": context.raw_preferences,
            "valid_candidates": valid_desc,
            "soft_risk_candidates": soft_desc,
            "recent_actions": context.recent_actions[-5:],
        }

        return {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_content, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
        }

    def _extract_json(self, content: str) -> str:
        text = str(content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text).strip()
            text = re.sub(r"```$", "", text).strip()
        return text or "{}"

    def _parse_decision(self, data: dict[str, Any], context: AdvisorContext) -> AdvisorDecision | None:
        candidate_id = str(data.get("selected_candidate_id") or "").strip()
        if not candidate_id:
            self._logger.warning("advisor returned empty selected_candidate_id")
            return None

        all_ids = {c.candidate_id for c in context.valid_candidates + context.soft_risk_candidates}
        if candidate_id not in all_ids:
            self._logger.warning(
                "advisor selected unknown candidate_id=%s, known=%s",
                candidate_id,
                sorted(all_ids)[:10],
            )
            return None

        reason = str(data.get("reason") or "").strip()
        accepted_risks_raw = data.get("accepted_risks") or []
        accepted_risks = tuple(str(r) for r in accepted_risks_raw) if isinstance(accepted_risks_raw, list) else ()

        self._logger.info(
            "advisor chose candidate_id=%s reason=%s",
            candidate_id,
            reason,
        )

        return AdvisorDecision(
            selected_candidate_id=candidate_id,
            reason=reason,
            accepted_risks=accepted_risks,
        )
