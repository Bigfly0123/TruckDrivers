from __future__ import annotations

from typing import Any

from agent.llm_decision_advisor import AdvisorContext, AdvisorDecision, LlmDecisionAdvisor
from simkit.ports import SimulationApiPort


class LegacyAdvisorAdapter:
    def __init__(self, api: SimulationApiPort) -> None:
        self._advisor = LlmDecisionAdvisor(api)

    def advise(self, context: AdvisorContext) -> AdvisorDecision | None:
        return self._advisor.advise(context)


def preference_text(pref: Any) -> str:
    import json

    if isinstance(pref, str):
        return pref
    if isinstance(pref, dict):
        return pref.get("text") or pref.get("raw_text") or json.dumps(pref, ensure_ascii=False)
    return str(pref)
