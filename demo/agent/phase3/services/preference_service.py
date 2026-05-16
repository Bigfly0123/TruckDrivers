from __future__ import annotations

from typing import Any

from agent.phase3.domain.agent_models import PreferenceRule
from agent.phase3.preferences.preference_compiler import PreferenceCompiler
from agent.phase3.preferences.preference_constraints import ConstraintSpec, compile_constraints
from simkit.ports import SimulationApiPort


class PreferenceService:
    """Compile raw driver preferences into general rules and constraints."""

    def __init__(self, api: SimulationApiPort) -> None:
        self._compiler = PreferenceCompiler(api)

    def compile(self, raw_preferences: list[Any]) -> tuple[tuple[PreferenceRule, ...], tuple[ConstraintSpec, ...]]:
        rules = self._compiler.compile(raw_preferences)
        return rules, compile_constraints(rules)

