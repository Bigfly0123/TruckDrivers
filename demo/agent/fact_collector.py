from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.agent_models import CandidateScore, DecisionState, PreferenceRule
from agent.candidate_pool import CandidatePool
from agent.mission_models import MissionPlan, mission_is_complex, mission_in_countdown
from agent.state_tracker import history_action_name, longest_wait_for_day


@dataclass(frozen=True)
class SituationFacts:
    current_minute: int
    current_day: int
    minute_of_day: int
    remaining_days: float
    location: tuple[float, float]

    wait_streak: int
    recent_wait_count: int
    recent_take_count: int
    recent_reposition_count: int
    orders_today: int
    recent_profit_estimate: float

    daily_rest_required: int
    daily_rest_longest: int
    daily_rest_missing: int
    monthly_deadhead_km: float
    completed_order_count: int

    has_active_mission: bool
    has_complex_mission: bool
    has_hard_lock: bool
    mission_countdown_minutes: int | None
    active_mission_ids: tuple[str, ...]
    active_mission_step_types: tuple[str, ...]
    nearest_deadline_minutes: int | None

    cargo_item_count: int
    candidate_count: int
    safe_take_count: int
    risky_take_count: int
    positive_take_count: int
    top_score: float | None
    top_profit: float | None

    home_pressure: str
    rest_pressure: str
    budget_pressure: str
    unknown_preference_pressure: bool
    likely_wait_deadlock: bool
    likely_over_conservative: bool

    filter_stats: dict[str, int]
    blocked_count: int

    raw_preferences: tuple[str, ...]
    rule_kinds: tuple[str, ...]

    def to_log_dict(self) -> dict[str, Any]:
        return {
            "day": self.current_day,
            "mod": self.minute_of_day,
            "rem_d": round(self.remaining_days, 1),
            "w_streak": self.wait_streak,
            "w_recent": self.recent_wait_count,
            "t_recent": self.recent_take_count,
            "r_recent": self.recent_reposition_count,
            "orders_today": self.orders_today,
            "items": self.cargo_item_count,
            "cands": self.candidate_count,
            "safe": self.safe_take_count,
            "risky": self.risky_take_count,
            "pos": self.positive_take_count,
            "top_score": self.top_score,
            "has_mission": self.has_active_mission,
            "complex": self.has_complex_mission,
            "hard_lock": self.has_hard_lock,
            "cd_min": self.mission_countdown_minutes,
            "dl_min": self.nearest_deadline_minutes,
            "h_press": self.home_pressure,
            "r_press": self.rest_pressure,
            "b_press": self.budget_pressure,
            "unk_pref": self.unknown_preference_pressure,
            "deadlock": self.likely_wait_deadlock,
            "over_cons": self.likely_over_conservative,
            "blocked": self.blocked_count,
            "filters": self.filter_stats,
        }

    def to_llm_summary(self) -> str:
        lines = [
            f"Time: day {self.current_day}, {self.minute_of_day // 60:02d}:{self.minute_of_day % 60:02d}, {self.remaining_days:.1f} days remaining",
            f"Location: ({self.location[0]:.3f}, {self.location[1]:.3f})",
            f"Recent actions (last 20 steps): wait={self.recent_wait_count}, take_order={self.recent_take_count}, reposition={self.recent_reposition_count}, wait_streak={self.wait_streak}",
            f"Orders today: {self.orders_today}, total completed: {self.completed_order_count}",
            f"Daily rest: required={self.daily_rest_required}min, longest={self.daily_rest_longest}min, missing={self.daily_rest_missing}min",
            f"Monthly deadhead: {self.monthly_deadhead_km:.1f}km",
            f"Cargo visible: {self.cargo_item_count} items, candidates: {self.candidate_count} (safe={self.safe_take_count}, risky={self.risky_take_count}, positive_profit={self.positive_take_count})",
            f"Top candidate: score={self.top_score}, profit={self.top_profit}",
            f"Missions: active={self.has_active_mission}, complex={self.has_complex_mission}, hard_lock={self.has_hard_lock}, countdown_min={self.mission_countdown_minutes}, nearest_deadline_min={self.nearest_deadline_minutes}",
            f"Active mission IDs: {', '.join(self.active_mission_ids) if self.active_mission_ids else 'none'}",
            f"Active step types: {', '.join(self.active_mission_step_types) if self.active_mission_step_types else 'none'}",
            f"Home pressure: {self.home_pressure}",
            f"Rest pressure: {self.rest_pressure}",
            f"Budget pressure: {self.budget_pressure}",
            f"Unknown preference types: {self.unknown_preference_pressure}",
            f"Likely wait deadlock: {self.likely_wait_deadlock}",
            f"Likely over-conservative: {self.likely_over_conservative}",
            f"Blocked candidates: {self.blocked_count}, filter reasons: {self.filter_stats}",
            f"Rule kinds: {', '.join(self.rule_kinds)}",
        ]
        if self.raw_preferences:
            lines.append("Raw preferences:")
            for p in self.raw_preferences[:5]:
                lines.append(f"  - {p[:120]}")
        return "\n".join(lines)


class FactCollector:
    def collect(
        self,
        state: DecisionState,
        rules: tuple[PreferenceRule, ...],
        missions: tuple[MissionPlan, ...],
        items: list[dict[str, Any]],
        candidates: list[CandidateScore],
        raw_preferences: list[str],
        candidate_pool: CandidatePool | None = None,
    ) -> SituationFacts:
        history = state.history_records[-20:]

        wait_streak = 0
        for rec in reversed(history):
            if history_action_name(rec) == "wait":
                wait_streak += 1
            else:
                break

        recent_wait_count = sum(1 for rec in history if history_action_name(rec) == "wait")
        recent_take_count = sum(1 for rec in history if history_action_name(rec) == "take_order")
        recent_reposition_count = sum(1 for rec in history if history_action_name(rec) == "reposition")

        orders_today = 0
        recent_profit = 0.0
        for rec in history:
            if history_action_name(rec) == "take_order":
                orders_today += 1
                result = rec.get("result") if isinstance(rec.get("result"), dict) else {}
                recent_profit += float(result.get("income", 0))

        take_candidates = [c for c in candidates if c.action == "take_order"]
        safe_take_count = sum(1 for c in take_candidates if not c.risk_level and not c.risk_reason)
        risky_take_count = sum(1 for c in take_candidates if c.risk_level or c.risk_reason)
        positive_take_count = sum(1 for c in take_candidates if c.estimated_profit > 0)
        top_score = take_candidates[0].score if take_candidates else None
        top_profit = take_candidates[0].estimated_profit if take_candidates else None

        active_missions = [m for m in missions if m.status == "active"]
        has_active_mission = len(active_missions) > 0
        has_complex_mission = any(mission_is_complex(m) for m in active_missions)
        has_hard_lock = any(
            any(s.lock_mode in ("hard_stay", "deadline_target") for s in m.steps)
            for m in active_missions
        )

        countdown_minutes_list = []
        deadline_list = []
        active_mission_ids = []
        active_step_types = []
        for m in active_missions:
            active_mission_ids.append(m.mission_id)
            if mission_in_countdown(m, state.current_minute):
                for s in m.steps:
                    if s.deadline_minute is not None and s.deadline_minute > state.current_minute:
                        remaining = s.deadline_minute - state.current_minute
                        countdown_minutes_list.append(remaining)
            for s in m.steps:
                if s.step_id not in (s2.step_id for s2 in m.steps if s2 is s):
                    pass
                active_step_types.append(s.action_type)
            for s in m.steps:
                if s.deadline_minute is not None and s.deadline_minute > state.current_minute:
                    deadline_list.append(s.deadline_minute - state.current_minute)

        mission_countdown_minutes = min(countdown_minutes_list) if countdown_minutes_list else None
        nearest_deadline_minutes = min(deadline_list) if deadline_list else None

        daily_rest_required = 0
        for rule in rules:
            if rule.kind in ("daily_rest", "weekday_rest") and rule.required_minutes:
                daily_rest_required = max(daily_rest_required, rule.required_minutes)
        daily_rest_longest = longest_wait_for_day(state, state.current_day)
        daily_rest_missing = max(0, daily_rest_required - daily_rest_longest)

        home_pressure = self._assess_home_pressure(state, rules, active_missions)
        rest_pressure = self._assess_rest_pressure(state, rules)
        budget_pressure = self._assess_budget_pressure(state, rules)
        unknown_preference_pressure = any((not r.kind) or r.kind == "unknown" for r in rules)

        mission_urgent = (
            has_hard_lock
            or (mission_countdown_minutes is not None and mission_countdown_minutes <= 240)
        )

        likely_wait_deadlock = (
            wait_streak >= 6
            and len(items) > 0
            and positive_take_count > 0
            and not has_hard_lock
            and not mission_urgent
        )

        likely_over_conservative = (
            recent_wait_count >= 10
            and len(take_candidates) > 0
            and safe_take_count == 0
            and risky_take_count > 0
            and not has_hard_lock
        )

        remaining_days = max(0.0, (state.simulation_duration_days * 1440 - state.current_minute) / 1440.0)
        rule_kinds = tuple(sorted(set(r.kind for r in rules)))

        return SituationFacts(
            current_minute=state.current_minute,
            current_day=state.current_day,
            minute_of_day=state.minute_of_day,
            remaining_days=remaining_days,
            location=(round(state.current_latitude, 4), round(state.current_longitude, 4)),
            wait_streak=wait_streak,
            recent_wait_count=recent_wait_count,
            recent_take_count=recent_take_count,
            recent_reposition_count=recent_reposition_count,
            orders_today=orders_today,
            recent_profit_estimate=recent_profit,
            daily_rest_required=daily_rest_required,
            daily_rest_longest=daily_rest_longest,
            daily_rest_missing=daily_rest_missing,
            monthly_deadhead_km=round(state.monthly_deadhead_km, 1),
            completed_order_count=state.completed_order_count,
            has_active_mission=has_active_mission,
            has_complex_mission=has_complex_mission,
            has_hard_lock=has_hard_lock,
            mission_countdown_minutes=mission_countdown_minutes,
            active_mission_ids=tuple(active_mission_ids),
            active_mission_step_types=tuple(dict.fromkeys(active_step_types)),
            nearest_deadline_minutes=nearest_deadline_minutes,
            cargo_item_count=len(items),
            candidate_count=len(candidates),
            safe_take_count=safe_take_count,
            risky_take_count=risky_take_count,
            positive_take_count=positive_take_count,
            top_score=top_score,
            top_profit=top_profit,
            home_pressure=home_pressure,
            rest_pressure=rest_pressure,
            budget_pressure=budget_pressure,
            unknown_preference_pressure=unknown_preference_pressure,
            likely_wait_deadlock=likely_wait_deadlock,
            likely_over_conservative=likely_over_conservative,
            filter_stats=dict(candidate_pool.filter_stats) if candidate_pool else {},
            blocked_count=len(candidate_pool.blocked) if candidate_pool else 0,
            raw_preferences=tuple(raw_preferences),
            rule_kinds=rule_kinds,
        )

    def _assess_rest_pressure(self, state: DecisionState, rules: tuple[PreferenceRule, ...]) -> str:
        required = 0
        for rule in rules:
            if rule.kind in ("daily_rest", "weekday_rest") and rule.required_minutes:
                required = max(required, rule.required_minutes)
        if required <= 0:
            return "none"
        longest = longest_wait_for_day(state, state.current_day)
        missing = max(0, required - longest)
        if missing <= 0:
            return "none"
        remaining_today = 1440 - state.minute_of_day
        if state.minute_of_day >= 17 * 60 and missing > required * 0.5:
            return "urgent"
        if remaining_today <= missing + 120:
            return "urgent"
        return "soft"

    def _assess_budget_pressure(self, state: DecisionState, rules: tuple[PreferenceRule, ...]) -> str:
        for rule in rules:
            if rule.kind == "max_monthly_deadhead" and rule.distance_limit_km:
                if state.monthly_deadhead_km > rule.distance_limit_km * 0.8:
                    return "urgent"
                if state.monthly_deadhead_km > rule.distance_limit_km * 0.6:
                    return "soft"
        return "none"

    def _assess_home_pressure(self, state: DecisionState, rules: tuple[PreferenceRule, ...], active_missions: list[MissionPlan]) -> str:
        for rule in rules:
            if rule.point is not None and rule.priority == "hard" and rule.time_window:
                window_start = rule.time_window.start_minute_of_day
                curfew = state.current_day * 1440 + window_start
                if state.current_minute >= curfew:
                    return "hard"
                time_to_curfew = curfew - state.current_minute
                if time_to_curfew <= 180:
                    return "urgent"
                if time_to_curfew <= 360:
                    return "soft"
        for m in active_missions:
            for s in m.steps:
                if s.lock_mode == "periodic_home" and s.deadline_minute is not None:
                    remaining = s.deadline_minute - state.current_minute
                    if remaining <= 0:
                        return "hard"
                    if remaining <= 120:
                        return "urgent"
        return "none"
