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
class AdvisorContext:
    state: DecisionState
    rules: tuple[PreferenceRule, ...]
    valid_candidates: list[Candidate]
    soft_risk_candidates: list[Candidate]
    raw_preferences: list[str]
    recent_actions: list[dict[str, Any]] = field(default_factory=list)
    trigger_reason: str = "normal_candidate_decision"


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
            "OUTPUT FORMAT: Strict JSON:\n"
            '{\n'
            '  "selected_candidate_id": "string",\n'
            '  "reason": "string",\n'
            '  "accepted_risks": ["string"]\n'
            '}\n'
        )

        state = context.state

        valid_desc = []
        for c in context.valid_candidates:
            desc: dict[str, Any] = {
                "candidate_id": c.candidate_id,
                "action": c.action,
            }
            if c.action == "take_order":
                desc["cargo_id"] = c.params.get("cargo_id", "")
                desc["price"] = c.facts.get("price", 0)
                desc["estimated_net"] = c.facts.get("estimated_net", 0)
                desc["pickup_deadhead_km"] = c.facts.get("pickup_deadhead_km", 0)
                desc["haul_distance_km"] = c.facts.get("haul_distance_km", 0)
            elif c.action == "wait":
                desc["duration_minutes"] = c.params.get("duration_minutes", 0)
            valid_desc.append(desc)

        soft_desc = []
        for c in context.soft_risk_candidates:
            desc = {
                "candidate_id": c.candidate_id,
                "action": c.action,
                "risk_reasons": list(c.soft_risk_reasons),
            }
            if c.action == "take_order":
                desc["cargo_id"] = c.params.get("cargo_id", "")
                desc["price"] = c.facts.get("price", 0)
                desc["estimated_net"] = c.facts.get("estimated_net", 0)
            elif c.action == "wait":
                desc["duration_minutes"] = c.params.get("duration_minutes", 0)
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
