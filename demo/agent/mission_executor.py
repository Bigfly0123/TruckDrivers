from __future__ import annotations

"""
LEGACY MODULE.

Not used by the default Phase 3 graph workflow. Kept for rollback,
comparison, and historical reference. Do not reintroduce it as a
decision-control component.
"""

import logging
from typing import Any

from agent.agent_models import CandidateScore, DecisionState, GeoPoint, PreferenceRule
from agent.geo_utils import distance_to_minutes, haversine_km, parse_wall_time_to_minute
from agent.mission_models import MissionPlan, MissionProgress, MissionStep
from agent.mission_replanner import MissionReplanner
from agent.state_tracker import build_mission_progress

REPOSITION_SPEED_KM_PER_HOUR = 60.0
MAX_CONTINUOUS_WAIT_MINUTES = 12 * 60
STUCK_WAIT_THRESHOLD = 20


class MissionCandidateBuilder:
    """Phase 1.5: Mission actions become candidates, never final actions.

    This module replaces MissionExecutor. It must NOT:
    - return final action dicts
    - bypass Advisor
    - force reposition or take_order
    """

    def __init__(self, replanner: MissionReplanner | None = None) -> None:
        self._logger = logging.getLogger("agent.mission_candidate_builder")
        self._replanner = replanner
        self._mission_wait_tracker: dict[str, int] = {}
        self._completed_missions: set[str] = set()
        self._expired_missions: set[str] = set()
        self._last_missions: tuple[MissionPlan, ...] = ()

    def decide(
        self,
        state: DecisionState,
        rules: tuple[PreferenceRule, ...],
        missions: tuple[MissionPlan, ...],
        items: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Deprecated: returns None. Mission candidates are built via build_candidates()."""
        return None

    def build_candidates(
        self,
        state: DecisionState,
        rules: tuple[PreferenceRule, ...],
        missions: tuple[MissionPlan, ...],
        items: list[dict[str, Any]],
    ) -> list[CandidateScore]:
        """Generate mission candidates for the Advisor to choose from."""
        if not missions:
            return []
        self._last_missions = missions
        progresses = build_mission_progress(missions, state)
        mission_progress_map = {p.mission_id: p for p in progresses}

        for mission in missions:
            if mission.status != "active":
                continue
            progress = mission_progress_map.get(mission.mission_id)
            if progress is None:
                continue
            self._update_lifecycle(mission, progress, state)

        active_missions = sorted(
            [m for m in missions if m.status == "active" and m.mission_id not in self._completed_missions and m.mission_id not in self._expired_missions],
            key=lambda m: m.priority,
            reverse=True,
        )

        candidates: list[CandidateScore] = []
        for mission in active_missions:
            progress = mission_progress_map.get(mission.mission_id)
            if progress is None or not progress.active_step_id:
                continue
            if self._is_mission_stuck(mission.mission_id):
                self._logger.info("mission=%s stuck too long, marking expired", mission.mission_id)
                self._expired_missions.add(mission.mission_id)
                continue
            for step in mission.steps:
                if step.step_id == progress.active_step_id:
                    candidate = self._build_step_candidate(state, step, items, mission, progress)
                    if candidate is not None:
                        candidates.append(candidate)
                    break
        return candidates

    def get_locked_missions(
        self,
        missions: tuple[MissionPlan, ...],
        state: DecisionState,
    ) -> list[tuple[MissionPlan, MissionStep]]:
        locked: list[tuple[MissionPlan, MissionStep]] = []
        progresses = build_mission_progress(missions, state)
        progress_map = {p.mission_id: p for p in progresses}
        for mission in missions:
            if mission.mission_id in self._completed_missions or mission.mission_id in self._expired_missions:
                continue
            if mission.status != "active":
                continue
            progress = progress_map.get(mission.mission_id)
            if progress is None or not progress.active_step_id:
                continue
            for step in mission.steps:
                if step.step_id == progress.active_step_id:
                    if step.action_type == "stay_within_radius" and step.deadline_minute is not None:
                        if state.current_minute < step.deadline_minute:
                            if step.lock_mode == "hard_stay":
                                locked.append((mission, step))
                            elif step.lock_mode == "periodic_home":
                                start, end = self._periodic_window(mission)
                                in_nightly = self._minute_in_periodic_window(state.minute_of_day, start, end)
                                if in_nightly:
                                    locked.append((mission, step))
                    break
        return locked

    def _update_lifecycle(
        self,
        mission: MissionPlan,
        progress: MissionProgress,
        state: DecisionState,
    ) -> None:
        mid = mission.mission_id
        if mid in self._completed_missions or mid in self._expired_missions:
            return
        if progress.is_completed:
            self._completed_missions.add(mid)
            self._mission_wait_tracker.pop(mid, None)
            self._logger.info("mission completed: %s (steps=%d)", mid, len(progress.completed_step_ids))
            return
        if self._check_all_steps_expired(mission, progress, state):
            self._expired_missions.add(mid)
            self._mission_wait_tracker.pop(mid, None)
            self._logger.info("mission expired: %s", mid)
            return

    def _check_all_steps_expired(
        self,
        mission: MissionPlan,
        progress: MissionProgress,
        state: DecisionState,
    ) -> bool:
        if progress.active_step_id is None:
            return False
        for step in mission.steps:
            if step.step_id == progress.active_step_id:
                if step.deadline_minute is not None and state.current_minute > step.deadline_minute + 60:
                    return True
                break
        return False

    def _is_mission_stuck(self, mission_id: str) -> bool:
        if self._mission_wait_tracker.get(mission_id, 0) < STUCK_WAIT_THRESHOLD:
            return False
        for m in self._last_missions:
            if m.mission_id == mission_id:
                for s in m.steps:
                    if s.action_type == "take_specific_cargo":
                        return False
                break
        return True

    def _build_step_candidate(
        self,
        state: DecisionState,
        step: MissionStep,
        items: list[dict[str, Any]],
        mission: MissionPlan,
        progress: MissionProgress,
    ) -> CandidateScore | None:
        """Build a CandidateScore from a mission step, never a final action dict."""
        if step.action_type == "go_to_point":
            return self._build_go_to_point_candidate(state, step, mission)
        if step.action_type == "wait_duration":
            return self._build_wait_duration_candidate(state, step, mission)
        if step.action_type == "take_specific_cargo":
            return self._build_take_specific_cargo_candidate(state, step, items, mission)
        if step.action_type == "stay_within_radius":
            return self._build_stay_within_radius_candidate(state, step, mission)
        return None

    def _build_go_to_point_candidate(self, state: DecisionState, step: MissionStep, mission: MissionPlan) -> CandidateScore | None:
        if step.point is None:
            return None
        dist = haversine_km(state.current_latitude, state.current_longitude, step.point.latitude, step.point.longitude)
        if dist <= step.point.radius_km:
            return None
        return CandidateScore(
            action="reposition",
            params={
                "latitude": step.point.latitude,
                "longitude": step.point.longitude,
                "_mission_id": mission.mission_id,
                "_mission_priority": mission.priority,
                "_mission_group_key": mission.mission_group_key,
            },
            score=0.0,
            estimated_profit=0.0,
            reason=f"mission_reposition:{mission.mission_id}:{step.step_id}",
        )

    def _build_wait_duration_candidate(self, state: DecisionState, step: MissionStep, mission: MissionPlan) -> CandidateScore | None:
        if step.point is None or step.duration_minutes is None:
            return None
        dist = haversine_km(state.current_latitude, state.current_longitude, step.point.latitude, step.point.longitude)
        if dist > step.point.radius_km:
            return CandidateScore(
                action="reposition",
                params={
                    "latitude": step.point.latitude,
                    "longitude": step.point.longitude,
                    "_mission_id": mission.mission_id,
                },
                score=0.0,
                estimated_profit=0.0,
                reason=f"mission_reposition_to_wait:{mission.mission_id}:{step.step_id}",
            )
        duration = min(step.duration_minutes, MAX_CONTINUOUS_WAIT_MINUTES)
        return CandidateScore(
            action="wait",
            params={
                "duration_minutes": duration,
                "_mission_id": mission.mission_id,
            },
            score=0.0,
            estimated_profit=0.0,
            reason=f"mission_wait:{mission.mission_id}:{step.step_id}",
        )

    def _build_take_specific_cargo_candidate(self, state: DecisionState, step: MissionStep, items: list[dict[str, Any]], mission: MissionPlan) -> CandidateScore | None:
        if step.cargo_id is None:
            return None
        for item in items:
            cargo = item.get("cargo") if isinstance(item.get("cargo"), dict) else {}
            cargo_id = str(cargo.get("cargo_id") or "").strip()
            if cargo_id == step.cargo_id:
                start = self._point_from_cargo(cargo.get("start"))
                end = self._point_from_cargo(cargo.get("end"))
                if start is None or end is None:
                    return None
                pickup_km = float(item.get("distance_km") or haversine_km(state.current_latitude, state.current_longitude, start[0], start[1]))
                haul_duration = max(1, int(float(cargo.get("cost_time_minutes", 120))))
                return CandidateScore(
                    action="take_order",
                    params={
                        "cargo_id": step.cargo_id,
                        "_mission_id": mission.mission_id,
                        "_estimated_duration_minutes": haul_duration,
                    },
                    score=0.0,
                    estimated_profit=_safe_float(cargo.get("price")),
                    reason=f"mission_take_specific_cargo:{mission.mission_id}:{step.cargo_id}",
                )
        return None

    def _build_stay_within_radius_candidate(self, state: DecisionState, step: MissionStep, mission: MissionPlan) -> CandidateScore | None:
        if step.point is None:
            return None
        if step.deadline_minute is not None and state.current_minute >= step.deadline_minute:
            return None
        dist = haversine_km(state.current_latitude, state.current_longitude, step.point.latitude, step.point.longitude)
        if dist > step.point.radius_km:
            return CandidateScore(
                action="reposition",
                params={
                    "latitude": step.point.latitude,
                    "longitude": step.point.longitude,
                    "_mission_id": mission.mission_id,
                },
                score=0.0,
                estimated_profit=0.0,
                reason=f"mission_return_to_radius:{mission.mission_id}:{step.step_id}",
            )
        if step.deadline_minute is not None:
            wait_duration = step.deadline_minute - state.current_minute
            wait_duration = min(wait_duration, MAX_CONTINUOUS_WAIT_MINUTES)
            return CandidateScore(
                action="wait",
                params={
                    "duration_minutes": wait_duration,
                    "_mission_id": mission.mission_id,
                },
                score=0.0,
                estimated_profit=0.0,
                reason=f"mission_stay_wait:{mission.mission_id}:{step.step_id}",
            )
        return None

    def _point_from_cargo(self, value: Any) -> tuple[float, float] | None:
        if not isinstance(value, dict):
            return None
        lat_raw = value.get("lat", value.get("latitude"))
        lng_raw = value.get("lng", value.get("longitude"))
        if lat_raw is None or lng_raw is None:
            return None
        try:
            return float(lat_raw), float(lng_raw)
        except (TypeError, ValueError):
            return None

    def _periodic_window(self, mission: MissionPlan) -> tuple[int, int]:
        return (
            int(mission.metadata.get("window_start_minute_of_day", 21 * 60)),
            int(mission.metadata.get("window_end_minute_of_day", 8 * 60)),
        )

    def _minute_in_periodic_window(self, minute_of_day: int, start: int, end: int) -> bool:
        if end <= start:
            return minute_of_day >= start or minute_of_day < end
        return start <= minute_of_day < end


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
