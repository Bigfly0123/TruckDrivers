from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.agent_models import Candidate, DecisionState, PreferenceRule
from agent.constraint_runtime import ConstraintRuntimeState
from agent.phase3.planning.day_plan import DayPlan
from agent.preference_constraints import ConstraintSpec


@dataclass
class AgentState:
    driver_id: str
    request_id: str = ""
    step_id: int | None = None

    driver_status: dict[str, Any] = field(default_factory=dict)
    current_time: int | None = None
    current_day: int | None = None
    current_location: dict[str, Any] | None = None
    visible_cargo: list[dict[str, Any]] = field(default_factory=list)
    decision_history: list[dict[str, Any]] = field(default_factory=list)
    decision_state: DecisionState | None = None

    raw_preferences: Any = None
    preference_rules: tuple[PreferenceRule, ...] = ()
    constraints: tuple[ConstraintSpec, ...] = ()
    constraint_runtime_state: ConstraintRuntimeState | None = None

    raw_candidates: list[Candidate] = field(default_factory=list)
    evaluated_candidates: list[Candidate] = field(default_factory=list)
    valid_candidates: list[Candidate] = field(default_factory=list)
    soft_risk_candidates: list[Candidate] = field(default_factory=list)
    hard_invalid_candidates: list[Candidate] = field(default_factory=list)

    day_plan: DayPlan | None = None
    day_plan_generated_this_step: bool = False

    advisor_context: dict[str, Any] = field(default_factory=dict)
    advisor_result: dict[str, Any] = field(default_factory=dict)
    selected_candidate_id: str | None = None
    selected_candidate: Candidate | None = None

    safety_result: dict[str, Any] = field(default_factory=dict)
    final_action: dict[str, Any] | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None

    trace: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    tool_summaries: dict[str, dict[str, Any]] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    debug: dict[str, Any] = field(default_factory=dict)

    def mark_fallback(self, reason: str, action: dict[str, Any]) -> None:
        self.fallback_used = True
        self.fallback_reason = reason
        self.final_action = action
