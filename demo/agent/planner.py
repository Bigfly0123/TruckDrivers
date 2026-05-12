from __future__ import annotations

import math
from typing import Any

from agent.agent_models import Candidate, CandidateScore, DecisionState, GeoPoint, PreferenceRule, TimeWindow, AreaBounds
from agent.geo_utils import distance_to_minutes, haversine_km, parse_wall_time_to_minute
from agent.state_tracker import longest_wait_for_day

DEFAULT_COST_PER_KM = 1.5
REPOSITION_SPEED_KM_PER_HOUR = 60.0
CARGO_VIEW_BATCH_SIZE = 10


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


def _in_area(lat: float, lng: float, area: AreaBounds) -> bool:
    return area.lat_min <= lat <= area.lat_max and area.lng_min <= lng <= area.lng_max


def _near_point(lat: float, lng: float, point: GeoPoint) -> bool:
    return haversine_km(lat, lng, point.latitude, point.longitude) <= point.radius_km


class CandidateFactBuilder:
    def build_candidate_pool(
        self,
        state: DecisionState,
        rules: tuple[PreferenceRule, ...],
        items: list[dict[str, Any]],
        active_missions: tuple[Any, ...] = (),
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

        return candidates

    def _build_cargo_candidate(
        self,
        state: DecisionState,
        rules: tuple[PreferenceRule, ...],
        item: dict[str, Any],
        cargo: dict[str, Any],
        cargo_id: str,
    ) -> Candidate | None:
        from agent.geo_utils import distance_to_minutes, haversine_km

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
            "price": price,
            "estimated_cost": round(estimated_cost, 1),
            "estimated_net": round(estimated_profit, 1),
            "pickup_deadhead_km": round(pickup_km, 1),
            "haul_distance_km": round(haul_km, 1),
            "estimated_duration_minutes": duration_minutes,
            "pickup_minutes": pickup_minutes,
            "finish_minute": finish_minute,
        }

        hard_invalid: list[str] = []
        soft_risk: list[str] = []

        remove_minute = self._parse_remove_time(cargo.get("remove_time"))
        if remove_minute is not None and remove_minute <= state.current_minute + 15:
            hard_invalid.append("remove_time_expired")
        elif remove_minute is not None and remove_minute <= arrival_minute + 5:
            hard_invalid.append("pickup_unreachable")

        if finish_minute > state.simulation_duration_days * 1440:
            hard_invalid.append("end_month_unreachable")

        cargo_name = str(cargo.get("cargo_name") or "")
        hard_risk, hard_reason = self._check_hard_rules(state, rules, cargo_name, start, end, pickup_km, haul_km, arrival_minute, finish_minute)
        if hard_risk >= 1_000_000:
            hard_invalid.append(hard_reason or "hard_rule_violation")

        soft_risk_value = self._check_soft_rules(state, rules, cargo_name, start, end, pickup_km, haul_km)
        if soft_risk_value > 0:
            soft_risk.append("preference_soft_risk")

        return Candidate(
            candidate_id=f"take_order_{cargo_id}",
            action="take_order",
            params={"cargo_id": cargo_id},
            source="cargo",
            facts=facts,
            hard_invalid_reasons=tuple(hard_invalid),
            soft_risk_reasons=tuple(soft_risk),
        )

    def _check_hard_rules(
        self,
        state: DecisionState,
        rules: tuple[PreferenceRule, ...],
        cargo_name: str,
        start: tuple[float, float],
        end: tuple[float, float],
        pickup_km: float,
        haul_km: float,
        action_start: int,
        action_end: int,
    ) -> tuple[float, str]:
        risk = 0.0
        reason = ""
        for rule in rules:
            if rule.kind == "forbidden_cargo" and cargo_name in rule.cargo_names and rule.priority == "hard":
                risk += max(rule.penalty_amount, 1000.0) * 4.0
                reason = reason or "forbidden_cargo"
            if rule.kind == "area_bounds" and rule.area_bounds is not None and rule.priority == "hard":
                if not _in_area(start[0], start[1], rule.area_bounds) or not _in_area(end[0], end[1], rule.area_bounds):
                    risk += max(rule.penalty_amount, 1000.0) * 4.0
                    reason = reason or "area_bounds_hard"
            if rule.kind == "forbidden_zone" and rule.point is not None:
                if _near_point(start[0], start[1], rule.point) or _near_point(end[0], end[1], rule.point):
                    risk += max(rule.penalty_amount, 1000.0) * (4.0 if rule.priority == "hard" else 1.5)
                    if rule.priority == "hard":
                        reason = reason or "forbidden_zone"
            if rule.kind == "max_pickup_deadhead" and rule.distance_limit_km is not None and pickup_km > rule.distance_limit_km:
                if rule.priority == "hard":
                    over_km = pickup_km - rule.distance_limit_km
                    risk += over_km * max(rule.penalty_amount, 200.0)
                    reason = reason or "max_pickup_deadhead"
            if rule.kind == "max_haul_distance" and rule.distance_limit_km is not None and haul_km > rule.distance_limit_km:
                if rule.priority == "hard":
                    over_km = haul_km - rule.distance_limit_km
                    risk += over_km * max(rule.penalty_amount, 100.0)
                    reason = reason or "max_haul_distance"
        return (risk, reason)

    def _check_soft_rules(
        self,
        state: DecisionState,
        rules: tuple[PreferenceRule, ...],
        cargo_name: str,
        start: tuple[float, float],
        end: tuple[float, float],
        pickup_km: float,
        haul_km: float,
    ) -> float:
        risk = 0.0
        for rule in rules:
            amount = max(rule.penalty_amount, 100.0)
            if rule.kind == "forbidden_cargo" and cargo_name in rule.cargo_names and rule.priority != "hard":
                risk += amount * 1.5
            elif rule.kind == "max_pickup_deadhead" and rule.distance_limit_km is not None and pickup_km > rule.distance_limit_km and rule.priority != "hard":
                risk += (pickup_km - rule.distance_limit_km) * amount
            elif rule.kind == "max_haul_distance" and rule.distance_limit_km is not None and haul_km > rule.distance_limit_km and rule.priority != "hard":
                risk += (haul_km - rule.distance_limit_km) * amount
            elif rule.kind == "area_bounds" and rule.area_bounds is not None and rule.priority == "soft":
                if not _in_area(start[0], start[1], rule.area_bounds) or not _in_area(end[0], end[1], rule.area_bounds):
                    risk += amount * 2.0
        return risk

    def _parse_remove_time(self, remove_time: Any) -> int | None:
        if not remove_time:
            return None
        try:
            from agent.geo_utils import parse_wall_time_to_minute
            return parse_wall_time_to_minute(remove_time)
        except Exception:
            return None

    def estimate_scan_cost(self, items_count: int) -> int:
        return math.ceil(items_count / 10) if items_count > 0 else 0
