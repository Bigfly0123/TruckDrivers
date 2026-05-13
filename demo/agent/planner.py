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
    "remove_time",
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

        constraint_candidates = self._generate_constraint_candidates(state, constraints)
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
    ) -> list[Candidate]:
        candidates: list[Candidate] = []
        existing_ids: set[str] = set()
        for idx, c in enumerate(constraints):
            if not hasattr(c, "constraint_type"):
                continue
            ct = c.constraint_type
            if ct == "specific_cargo" and c.cargo_ids:
                for cid in c.cargo_ids:
                    candidate_id = f"specific_cargo_{cid}"
                    if candidate_id in existing_ids:
                        continue
                    existing_ids.add(candidate_id)
                    candidates.append(Candidate(
                        candidate_id=candidate_id,
                        action="take_order",
                        params={"cargo_id": cid},
                        source="constraint",
                        facts={"constraint_type": ct, "constraint_id": c.constraint_id},
                    ))
            elif ct == "continuous_rest":
                candidate_id = f"wait_rest_{c.required_minutes or 480}"
                if candidate_id not in existing_ids:
                    existing_ids.add(candidate_id)
                    minutes = c.required_minutes or 480
                    candidates.append(Candidate(
                        candidate_id=candidate_id,
                        action="wait",
                        params={"duration_minutes": min(minutes, 60)},
                        source="constraint",
                        facts={"constraint_type": ct, "satisfies_continuous_rest": True, "required_minutes": minutes},
                    ))
            elif ct == "be_at_location_by_deadline" and c.point is not None:
                candidate_id = f"go_to_{c.constraint_id}"
                if candidate_id not in existing_ids:
                    existing_ids.add(candidate_id)
                    candidates.append(Candidate(
                        candidate_id=candidate_id,
                        action="reposition",
                        params={"latitude": c.point.latitude, "longitude": c.point.longitude},
                        source="constraint",
                        facts={"constraint_type": ct, "target_point": (c.point.latitude, c.point.longitude)},
                    ))
        return candidates

    def estimate_scan_cost(self, items_count: int) -> int:
        return math.ceil(items_count / 10) if items_count > 0 else 0
