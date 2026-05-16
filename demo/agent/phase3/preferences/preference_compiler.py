from __future__ import annotations

import logging
from typing import Any

from agent.phase3.domain.agent_models import PreferenceRule
from agent.phase3.domain.geo_utils import parse_wall_time_to_minute
from agent.phase3.preferences.llm_preference_agent import LlmPreferenceAgent


class PreferenceCompiler:
    """LLM-first preference compiler.

    The compiler deliberately avoids dataset-shaped regex recovery. If the LLM
    cannot parse a preference, the rest of the agent receives an explicit
    unknown rule plus the raw text, so the decision advisor can reason
    conservatively instead of a hidden Python branch inventing a task type.
    """

    def __init__(self, api: Any | None = None) -> None:
        self._llm_agent = LlmPreferenceAgent(api)
        self._cache: dict[str, tuple[PreferenceRule, ...]] = {}
        self._logger = logging.getLogger("agent.phase3.preferences.preference_compiler")

    def compile(self, preferences: list[Any]) -> tuple[PreferenceRule, ...]:
        rules: list[PreferenceRule] = []
        for entry in preferences or []:
            text = self._entry_text(entry)
            if not text:
                continue
            if text not in self._cache:
                parsed = tuple(self._llm_agent.parse(entry))
                if not parsed:
                    self._logger.warning("preference parsed as unknown: %s", text[:120])
                    parsed = (self._unknown_rule(entry, text),)
                self._cache[text] = parsed
            rules.extend(self._cache[text])
        return tuple(rules)

    def _entry_text(self, entry: Any) -> str:
        if isinstance(entry, str):
            return entry.strip()
        if isinstance(entry, dict):
            return str(entry.get("content") or entry.get("text") or "").strip()
        return ""

    def _base_kwargs(self, entry: Any, text: str) -> dict[str, Any]:
        amount = 0.0
        cap = None
        start = None
        end = None
        if isinstance(entry, dict):
            amount = float(entry.get("penalty_amount", 0.0) or 0.0)
            cap_raw = entry.get("penalty_cap")
            cap = None if cap_raw is None else float(cap_raw)
            start = parse_wall_time_to_minute(entry.get("start_time"))
            end = parse_wall_time_to_minute(entry.get("end_time"))
        return {
            "penalty_amount": amount,
            "penalty_cap": cap,
            "active_start_minute": start,
            "active_end_minute": end,
            "raw_text": text,
        }

    def _unknown_rule(self, entry: Any, text: str) -> PreferenceRule:
        return PreferenceRule(kind="unknown", priority="soft", **self._base_kwargs(entry, text))
