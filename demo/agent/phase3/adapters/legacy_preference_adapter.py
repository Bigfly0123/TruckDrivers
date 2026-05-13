from __future__ import annotations

from typing import Any

from agent.agent_models import PreferenceRule
from agent.preference_compiler import PreferenceCompiler
from agent.preference_constraints import ConstraintSpec, compile_constraints
from simkit.ports import SimulationApiPort


class LegacyPreferenceAdapter:
    def __init__(self, api: SimulationApiPort) -> None:
        self._compiler = PreferenceCompiler(api)

    def compile(self, raw_preferences: list[Any]) -> tuple[tuple[PreferenceRule, ...], tuple[ConstraintSpec, ...]]:
        rules = self._compiler.compile(raw_preferences)
        return rules, compile_constraints(rules)
