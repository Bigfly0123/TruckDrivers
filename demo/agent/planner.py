from __future__ import annotations

import math
from typing import Any

from agent.agent_models import Candidate, DecisionState, PreferenceRule
from agent.geo_utils import distance_to_minutes, haversine_km, parse_wall_time_to_minute

DEFAULT_COST_PER_KM = 1.5
REPOSITION_SPEED_KM_PER_HOUR = 60.0
CARGO_VIEW_BATCH_SIZE = 10
LOAD_WINDOW_BUFFER_MINUTES = 5
_DEADLINE_KEYS = (
    "load_time_window_end",
    "load_end_time",
    "loading_end_time",
    "load_deadline",
    "pickup_deadline",
    "latest_load_time",
)


def estimate_scan_cost(items_count: int) -> int:
    return math.ceil(items_count / CARGO_VIEW_BATCH_SIZE) if items_count > 0 else 0


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _point_from_payload(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, dict):
        return None
    if "lat" not in value or "lng" not in value:
        return None
    return _safe_float(value.get("lat")), _safe_float(value.get("lng"))


class CandidateFactBuilder:
    def build_candidate_pool(
        self,
        state: DecisionState,
        rules: tuple[PreferenceRule, ...],
        items: list[dict[str, Any]],
        constraints: tuple[Any, ...] = (),
        runtime: Any | None = None,
    ) -> list[Candidate]:
        candidates: list[Candidate] = []

        candidates.append(Candidate(
            candidate_id="wait_30",
            action="wait",
            params={"duration_minutes": 30},
            source="system",
            facts={"duration_minutes": 30},
        ))
        candidates.append(Candidate(
            candidate_id="wait_60",
            action="wait",
            params={"duration_minutes": 60},
            source="system",
            facts={"duration_minutes": 60},
        ))

        for item in items[:100]:
            cargo = item.get("cargo") if isinstance(item.get("cargo"), dict) else {}
            cargo_id = str(cargo.get("cargo_id") or "").strip()
            if not cargo_id:
                continue
            candidate = self._build_cargo_candidate(state, rules, item, cargo, cargo_id)
            if candidate is not None:
                candidates.append(candidate)

        constraint_candidates = self._generate_constraint_candidates(state, constraints, runtime, items)
        candidates.extend(constraint_candidates)

        return candidates

    def _build_cargo_candidate(
        self,
        state: DecisionState,
        rules: tuple[PreferenceRule, ...],
        item: dict[str, Any],
        cargo: dict[str, Any],
        cargo_id: str,
    ) -> Candidate | None:
        start = _point_from_payload(cargo.get("start"))
        end = _point_from_payload(cargo.get("end"))
        if start is None or end is None:
            return Candidate(
                candidate_id=f"take_order_{cargo_id}",
                action="take_order",
                params={"cargo_id": cargo_id},
                source="cargo",
                facts={},
                hard_invalid_reasons=("invalid_cargo_geometry",),
            )

        pickup_km = _safe_float(item.get("distance_km"))
        haul_km = haversine_km(start[0], start[1], end[0], end[1])
        pickup_minutes = 0 if pickup_km <= 1e-6 else distance_to_minutes(pickup_km, 60.0)
        arrival_minute = state.current_minute + pickup_minutes
        duration_minutes = max(1, int(_safe_float(cargo.get("cost_time_minutes"), 1.0)))
        price = _safe_float(cargo.get("price"))
        estimated_cost = (pickup_km + haul_km) * 1.5
        estimated_profit = price - estimated_cost
        finish_minute = arrival_minute + duration_minutes

        facts: dict[str, Any] = {
            "cargo_id": cargo_id,
            "cargo_name": str(cargo.get("cargo_name") or ""),
            "price": price,
            "estimated_cost": round(estimated_cost, 1),
            "estimated_net": round(estimated_profit, 1),
            "pickup_deadhead_km": round(pickup_km, 1),
            "haul_distance_km": round(haul_km, 1),
            "estimated_duration_minutes": duration_minutes,
            "pickup_minutes": pickup_minutes,
            "finish_minute": finish_minute,
            "start": start,
            "end": end,
        }

        hard_invalid: list[str] = []
        soft_risk: list[str] = []

        deadline_minute, deadline_source = self._parse_cargo_deadline_minute(cargo)
        facts["pickup_arrival_minute"] = arrival_minute
        facts["cargo_deadline_minute"] = deadline_minute
        facts["deadline_source"] = deadline_source
        facts["load_window_buffer_minutes"] = LOAD_WINDOW_BUFFER_MINUTES

        if deadline_minute is not None:
            if state.current_minute >= deadline_minute:
                hard_invalid.append("load_time_window_expired")
            elif arrival_minute + LOAD_WINDOW_BUFFER_MINUTES > deadline_minute:
                hard_invalid.append("load_time_window_unreachable")

        if finish_minute > state.simulation_duration_days * 1440:
            hard_invalid.append("end_month_unreachable")

        return Candidate(
            candidate_id=f"take_order_{cargo_id}",
            action="take_order",
            params={"cargo_id": cargo_id},
            source="cargo",
            facts=facts,
            hard_invalid_reasons=tuple(hard_invalid),
            soft_risk_reasons=tuple(soft_risk),
        )

    def _parse_cargo_deadline_minute(self, cargo: dict[str, Any]) -> tuple[int | None, str]:
        load_time = cargo.get("load_time")
        if isinstance(load_time, (list, tuple)) and len(load_time) == 2:
            parsed = parse_wall_time_to_minute(load_time[1])
            if parsed is not None:
                return parsed, "load_time"
        for key in _DEADLINE_KEYS:
            value = cargo.get(key)
            if value is None or value == "":
                continue
            try:
                parsed = parse_wall_time_to_minute(value)
            except Exception:
                parsed = None
            if parsed is not None:
                return parsed, key
        return None, ""

    def _generate_constraint_candidates(
        self,
        state: DecisionState,
        constraints: tuple[Any, ...],
        runtime: Any | None = None,
        items: list[dict[str, Any]] | None = None,
    ) -> list[Candidate]:
        candidates: list[Candidate] = []
        existing_ids: set[str] = set()
        visible_cargo_ids: set[str] = set()
        if items:
            for item in items:
                cargo = item.get("cargo") if isinstance(item.get("cargo"), dict) else {}
                cid = str(cargo.get("cargo_id") or "").strip()
                if cid:
                    visible_cargo_ids.add(cid)

        for c in constraints:
            if not hasattr(c, "constraint_type"):
                continue
            ct = c.constraint_type

            if ct == "specific_cargo" and c.cargo_ids:
                for cid in c.cargo_ids:
                    if cid not in visible_cargo_ids:
                        continue
                    candidate_id = f"specific_cargo_{cid}"
                    if candidate_id in existing_ids:
                        continue
                    existing_ids.add(candidate_id)
                    candidates.append(Candidate(
                        candidate_id=candidate_id,
                        action="take_order",
                        params={"cargo_id": cid},
                        source="constraint_satisfy",
                        facts={
                            "constraint_type": ct,
                            "constraint_id": c.constraint_id,
                            "penalty_if_missed": max(c.penalty_amount, 500.0),
                        },
                    ))

            elif ct == "continuous_rest":
                remaining = c.required_minutes or 480
                current_streak = 0
                if runtime is not None and hasattr(runtime, "rest"):
                    remaining = runtime.rest.remaining_rest_minutes_by_constraint.get(c.constraint_id, remaining)
                    current_streak = runtime.rest.current_rest_streak_minutes
                if remaining > 0:
                    candidate_id = f"continue_rest_{c.constraint_id}"
                    if candidate_id not in existing_ids:
                        existing_ids.add(candidate_id)
                        duration = min(60, max(1, remaining))
                        remaining_after = max(0, remaining - duration)
                        completes = remaining_after == 0
                        penalty = max(c.penalty_amount, 100.0) * max(1, remaining / 60)
                        candidates.append(Candidate(
                            candidate_id=candidate_id,
                            action="wait",
                            params={"duration_minutes": duration},
                            source="constraint_satisfy",
                            facts={
                                "satisfies_constraint_type": "continuous_rest",
                                "satisfy_status": "complete" if completes else "progress",
                                "constraint_id": c.constraint_id,
                                "current_rest_streak_minutes": current_streak,
                                "required_minutes": c.required_minutes or 480,
                                "remaining_rest_minutes": remaining,
                                "adds_rest_minutes": duration,
                                "remaining_rest_minutes_after_wait": remaining_after,
                                "completes_continuous_rest": completes,
                                "avoids_estimated_penalty": penalty if completes else 0.0,
                                "penalty_if_rest_not_completed": penalty,
                            },
                        ))

            elif ct == "forbid_action_in_time_window":
                if runtime is not None and hasattr(runtime, "time_windows"):
                    tw_state = runtime.time_windows
                    if tw_state.active_forbidden_windows:
                        for win in tw_state.active_forbidden_windows:
                            end_minute = win.get("end_minute_of_day")
                            if end_minute is None:
                                continue
                            if c.time_window is not None and c.time_window.start_minute_of_day > c.time_window.end_minute_of_day:
                                if state.minute_of_day >= c.time_window.start_minute_of_day:
                                    end_abs = state.current_minute - state.minute_of_day + end_minute + 1440
                                else:
                                    end_abs = state.current_minute - state.minute_of_day + end_minute
                            else:
                                end_abs = state.current_minute - state.minute_of_day + end_minute
                            wait_duration = max(1, min(60, end_abs - state.current_minute))
                            candidate_id = f"wait_until_window_end_{c.constraint_id}"
                            if candidate_id in existing_ids:
                                continue
                            existing_ids.add(candidate_id)
                            candidates.append(Candidate(
                                candidate_id=candidate_id,
                                action="wait",
                                params={"duration_minutes": wait_duration},
                                source="constraint_satisfy",
                                facts={
                                    "satisfies_constraint_type": "forbid_action_in_time_window",
                                    "constraint_id": c.constraint_id,
                                    "window_end_minute": end_abs,
                                    "avoids_estimated_penalty": max(c.penalty_amount, 200.0),
                                },
                            ))

            elif ct == "be_at_location_by_deadline" and c.point is not None:
                candidate_id = f"go_to_location_by_deadline_{c.constraint_id}"
                if candidate_id not in existing_ids:
                    existing_ids.add(candidate_id)
                    candidates.append(Candidate(
                        candidate_id=candidate_id,
                        action="reposition",
                        params={"latitude": c.point.latitude, "longitude": c.point.longitude},
                        source="constraint_satisfy",
                        facts={
                            "satisfies_constraint_type": "be_at_location_by_deadline",
                            "constraint_id": c.constraint_id,
                            "deadline_minute": c.deadline_minute,
                            "penalty_if_missed": max(c.penalty_amount, 500.0),
                        },
                    ))

            elif ct == "ordered_steps":
                steps = c.metadata.get("steps") if c.metadata else None
                if steps:
                    next_step = steps[0] if isinstance(steps, (tuple, list)) else None
                    if next_step is not None:
                        step_action = getattr(next_step, "action", "visit")
                        if step_action == "visit" and hasattr(next_step, "point") and next_step.point is not None:
                            candidate_id = f"ordered_step_visit_{c.constraint_id}_0"
                            if candidate_id not in existing_ids:
                                existing_ids.add(candidate_id)
                                candidates.append(Candidate(
                                    candidate_id=candidate_id,
                                    action="reposition",
                                    params={"latitude": next_step.point.latitude, "longitude": next_step.point.longitude},
                                    source="constraint_satisfy",
                                    facts={
                                        "satisfies_constraint_type": "ordered_steps",
                                        "constraint_id": c.constraint_id,
                                        "step_type": "visit_location",
                                        "step_index": 0,
                                        "penalty_if_missed": max(c.penalty_amount, 500.0),
                                    },
                                ))
                        elif step_action in {"wait", "stay"} and hasattr(next_step, "stay_minutes"):
                            candidate_id = f"ordered_step_stay_{c.constraint_id}_0"
                            if candidate_id not in existing_ids:
                                existing_ids.add(candidate_id)
                                duration = min(60, max(1, next_step.stay_minutes or 60))
                                candidates.append(Candidate(
                                    candidate_id=candidate_id,
                                    action="wait",
                                    params={"duration_minutes": duration},
                                    source="constraint_satisfy",
                                    facts={
                                        "satisfies_constraint_type": "ordered_steps",
                                        "constraint_id": c.constraint_id,
                                        "step_type": "stay_duration",
                                        "step_index": 0,
                                        "penalty_if_missed": max(c.penalty_amount, 500.0),
                                    },
                                ))

        return candidates

    def estimate_scan_cost(self, items_count: int) -> int:
        return math.ceil(items_count / 10) if items_count > 0 else 0
