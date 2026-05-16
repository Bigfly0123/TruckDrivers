from __future__ import annotations

import math
from typing import Any

from agent.phase3.candidates.cargo_reachability import (
    evaluate_cargo_reachability,
)
from agent.phase3.domain.agent_models import Candidate, DecisionState, PreferenceRule
from agent.phase3.domain.geo_utils import distance_to_minutes, haversine_km

DEFAULT_COST_PER_KM = 1.5
REPOSITION_SPEED_KM_PER_HOUR = 60.0
CARGO_VIEW_BATCH_SIZE = 10
MARKET_PROBE_MAX_CANDIDATES = 3
MARKET_PROBE_RADIUS_KM = 80.0
MARKET_PROBE_MIN_DISTANCE_KM = 15.0
MARKET_PROBE_MAX_DISTANCE_KM = 260.0


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
    def build_candidates(
        self,
        state: DecisionState,
        rules: tuple[PreferenceRule, ...],
        items: list[dict[str, Any]],
        constraints: tuple[Any, ...] = (),
        runtime: Any | None = None,
    ) -> list[Candidate]:
        candidates: list[Candidate] = []
        observed_minute = max(0, state.current_minute - estimate_scan_cost(len(items)))

        candidates.append(Candidate(
            candidate_id="wait_30",
            action="wait",
            params={"duration_minutes": 30},
            source="system",
            facts={"duration_minutes": 30, "decision_effective_minute": state.current_minute},
        ))
        candidates.append(Candidate(
            candidate_id="wait_60",
            action="wait",
            params={"duration_minutes": 60},
            source="system",
            facts={"duration_minutes": 60, "decision_effective_minute": state.current_minute},
        ))

        cargo_candidates: list[Candidate] = []
        for item in items[:100]:
            cargo = item.get("cargo") if isinstance(item.get("cargo"), dict) else {}
            cargo_id = str(cargo.get("cargo_id") or "").strip()
            if not cargo_id:
                continue
            candidate = self._build_cargo_candidate(
                state,
                rules,
                item,
                cargo,
                cargo_id,
                observed_minute=observed_minute,
            )
            if candidate is not None:
                cargo_candidates.append(candidate)
                candidates.append(candidate)

        candidates.extend(self._generate_market_probe_candidates(state, cargo_candidates))
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
        *,
        observed_minute: int,
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
        reachability = evaluate_cargo_reachability(
            cargo=cargo,
            observed_minute=observed_minute,
            decision_effective_minute=state.current_minute,
            pickup_minutes=pickup_minutes,
            finish_minute=finish_minute,
            simulation_horizon_minute=state.simulation_duration_days * 1440,
        )

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
            "current_minute": state.current_minute,
            "finish_minute": finish_minute,
            "start": start,
            "end": end,
            **reachability.facts(),
        }

        hard_invalid: list[str] = list(reachability.hard_invalid_reasons)
        soft_risk: list[str] = []

        return Candidate(
            candidate_id=f"take_order_{cargo_id}",
            action="take_order",
            params={"cargo_id": cargo_id},
            source="cargo",
            facts=facts,
            hard_invalid_reasons=tuple(hard_invalid),
            soft_risk_reasons=tuple(soft_risk),
        )

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
                            "penalty_if_missed": _penalty_hint(c, hard_default=500.0),
                        },
                    ))

            elif ct == "continuous_rest":
                required = c.required_minutes or 480
                current_streak = 0
                max_streak = 0
                if runtime is not None and hasattr(runtime, "rest"):
                    current_streak = runtime.rest.current_rest_streak_minutes
                    max_streak = runtime.rest.max_rest_streak_today
                if max_streak < required:
                    rest_streak_after_wait = current_streak + 60
                    max_streak_after_wait = max(max_streak, rest_streak_after_wait)
                    remaining_after = max(0, required - max_streak_after_wait)
                    completes = max_streak_after_wait >= required
                    prefix = "continue_rest_60" if current_streak > 0 else "start_rest_60"
                    candidate_id = f"{prefix}_{c.constraint_id}"
                    if candidate_id not in existing_ids:
                        existing_ids.add(candidate_id)
                        penalty = _penalty_hint(c, hard_default=100.0)
                        candidates.append(Candidate(
                            candidate_id=candidate_id,
                            action="wait",
                            params={"duration_minutes": 60},
                            source="constraint_satisfy",
                            facts={
                                "satisfies_constraint_type": "continuous_rest",
                                "satisfy_status": "complete" if completes else "progress",
                                "constraint_id": c.constraint_id,
                                "current_rest_streak_minutes": current_streak,
                                "max_rest_streak_today": max_streak,
                                "required_minutes": required,
                                "adds_rest_minutes": 60,
                                "rest_streak_after_wait": rest_streak_after_wait,
                                "remaining_rest_minutes_after_wait": remaining_after,
                                "actually_satisfies_after_this_wait": completes,
                                "avoids_estimated_penalty": penalty if completes else 0.0,
                                "penalty_if_rest_not_completed": penalty,
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
                            "penalty_if_missed": _penalty_hint(c, hard_default=500.0),
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
                                        "penalty_if_missed": _penalty_hint(c, hard_default=500.0),
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
                                        "penalty_if_missed": _penalty_hint(c, hard_default=500.0),
                                    },
                                ))

        return candidates

    def estimate_scan_cost(self, items_count: int) -> int:
        return math.ceil(items_count / 10) if items_count > 0 else 0

    def _generate_market_probe_candidates(
        self,
        state: DecisionState,
        cargo_candidates: list[Candidate],
    ) -> list[Candidate]:
        if not _market_probe_needed(cargo_candidates):
            return []
        scored_targets = _rank_market_probe_targets(state, cargo_candidates)
        candidates: list[Candidate] = []
        seen: set[tuple[float, float]] = set()
        for index, target in enumerate(scored_targets[:MARKET_PROBE_MAX_CANDIDATES]):
            lat, lng = target["point"]
            key = (round(lat, 2), round(lng, 2))
            if key in seen:
                continue
            seen.add(key)
            distance_km = float(target["distance_km"])
            duration = distance_to_minutes(distance_km, REPOSITION_SPEED_KM_PER_HOUR)
            travel_cost = round(distance_km * DEFAULT_COST_PER_KM, 1)
            lat_key = abs(int(round(lat * 1000)))
            lng_key = abs(int(round(lng * 1000)))
            candidates.append(Candidate(
                candidate_id=f"market_probe_{index}_{lat_key}_{lng_key}",
                action="reposition",
                params={"latitude": round(lat, 6), "longitude": round(lng, 6)},
                source="market_probe",
                facts={
                    "estimated_cost": travel_cost,
                    "estimated_net": -travel_cost,
                    "estimated_duration_minutes": duration,
                    "market_probe_score": round(float(target["score"]), 3),
                    "market_probe_density": int(target["density"]),
                    "market_probe_avg_net": round(float(target["avg_net"]), 2),
                    "market_probe_positive_count": int(target["positive_count"]),
                    "market_probe_distance_km": round(distance_km, 1),
                    "market_probe_reason": target["reason"],
                    "destination": (round(lat, 6), round(lng, 6)),
                },
            ))
        return candidates


def _market_probe_needed(cargo_candidates: list[Candidate]) -> bool:
    if len(cargo_candidates) < 20:
        return False
    reachable_profitable = [
        c for c in cargo_candidates
        if not c.hard_invalid_reasons and float(c.facts.get("estimated_net", 0) or 0) > 0
    ]
    expired_or_unreachable = [
        c for c in cargo_candidates
        if any(str(reason).startswith("load_time_window_") for reason in c.hard_invalid_reasons)
    ]
    stale_ratio = len(expired_or_unreachable) / max(1, len(cargo_candidates))
    return len(reachable_profitable) < 3 or stale_ratio >= 0.55


def _rank_market_probe_targets(state: DecisionState, cargo_candidates: list[Candidate]) -> list[dict[str, Any]]:
    viable_candidates = [
        c for c in cargo_candidates
        if _is_market_viable(c)
    ]
    if not viable_candidates:
        return []
    raw_points: list[tuple[float, float, str]] = []
    for candidate in viable_candidates:
        for key, role in (("end", "delivery_cluster"), ("start", "pickup_cluster")):
            point = candidate.facts.get(key)
            if isinstance(point, (tuple, list)) and len(point) >= 2:
                raw_points.append((_safe_float(point[0]), _safe_float(point[1]), role))

    scored: list[dict[str, Any]] = []
    for lat, lng, role in raw_points:
        distance_km = haversine_km(state.current_latitude, state.current_longitude, lat, lng)
        if distance_km < MARKET_PROBE_MIN_DISTANCE_KM or distance_km > MARKET_PROBE_MAX_DISTANCE_KM:
            continue
        nearby_viable = [
            c for c in viable_candidates
            if _candidate_point_near(c, "start", lat, lng) or _candidate_point_near(c, "end", lat, lng)
        ]
        if not nearby_viable:
            continue
        nearby_all = [
            c for c in cargo_candidates
            if _candidate_point_near(c, "start", lat, lng) or _candidate_point_near(c, "end", lat, lng)
        ]
        nets = [float(c.facts.get("estimated_net", 0) or 0) for c in nearby_viable]
        positive = [net for net in nets if net > 0]
        density = len(nearby_viable)
        avg_net = sum(positive) / len(positive) if positive else sum(nets) / len(nets)
        stale = sum(1 for c in nearby_all if c.hard_invalid_reasons) / max(1, len(nearby_all))
        density_score = min(1.0, density / 12.0)
        net_score = min(1.0, max(0.0, avg_net) / 900.0)
        distance_penalty = min(0.35, distance_km / 800.0)
        stale_penalty = min(0.25, stale * 0.25)
        role_bonus = 0.08 if role == "delivery_cluster" else 0.03
        score = density_score * 0.45 + net_score * 0.42 + role_bonus - distance_penalty - stale_penalty
        if score <= 0.12:
            continue
        scored.append({
            "point": (lat, lng),
            "score": score,
            "density": density,
            "avg_net": avg_net,
            "positive_count": len(positive),
            "distance_km": distance_km,
            "reason": f"{role}:density={density},positive={len(positive)},stale={round(stale,2)}",
        })
    scored.sort(key=lambda item: float(item["score"]), reverse=True)
    return _dedupe_probe_targets(scored)


def _is_market_viable(candidate: Candidate) -> bool:
    if candidate.hard_invalid_reasons:
        return False
    if not bool(candidate.facts.get("simulator_executable", True)):
        return False
    if str(candidate.facts.get("load_window_status") or "") not in {"pickup_window_reachable", "no_load_window_deadline"}:
        return False
    return float(candidate.facts.get("estimated_net", 0) or 0) > 0


def _candidate_point_near(candidate: Candidate, key: str, lat: float, lng: float) -> bool:
    point = candidate.facts.get(key)
    if not isinstance(point, (tuple, list)) or len(point) < 2:
        return False
    return haversine_km(lat, lng, _safe_float(point[0]), _safe_float(point[1])) <= MARKET_PROBE_RADIUS_KM


def _dedupe_probe_targets(scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in scored:
        lat, lng = item["point"]
        if any(haversine_km(lat, lng, existing["point"][0], existing["point"][1]) < 35.0 for existing in result):
            continue
        result.append(item)
    return result


def _penalty_hint(constraint: Any, *, hard_default: float) -> float:
    amount = float(getattr(constraint, "penalty_amount", 0.0) or 0.0)
    if amount <= 0:
        amount = hard_default if getattr(constraint, "priority", "soft") == "hard" else 0.0
    cap = getattr(constraint, "penalty_cap", None)
    if cap is not None:
        amount = min(amount, float(cap))
    return round(max(0.0, amount), 2)
