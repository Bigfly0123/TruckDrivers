from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.phase3.domain.geo_utils import parse_wall_time_to_minute


LOAD_WINDOW_BUFFER_MINUTES = 5


@dataclass(frozen=True)
class CargoReachability:
    observed_minute: int
    decision_effective_minute: int
    online_until_minute: int | None
    pickup_arrival_minute: int
    load_window_start_minute: int | None
    load_window_end_minute: int | None
    load_window_status: str
    end_month_reachable: bool
    simulator_executable: bool
    hard_invalid_reasons: tuple[str, ...]

    def facts(self) -> dict[str, Any]:
        return {
            "observed_minute": self.observed_minute,
            "decision_effective_minute": self.decision_effective_minute,
            "online_until_minute": self.online_until_minute,
            "pickup_arrival_minute": self.pickup_arrival_minute,
            "cargo_deadline_minute": self.load_window_end_minute,
            "load_window_start_minute": self.load_window_start_minute,
            "load_window_end_minute": self.load_window_end_minute,
            "load_window_buffer_minutes": LOAD_WINDOW_BUFFER_MINUTES,
            "load_window_status": self.load_window_status,
            "end_month_reachable": self.end_month_reachable,
            "simulator_executable": self.simulator_executable,
            "reachability_layer": "cargo_time_window",
            "load_window_audit": {
                "reason_class": self.load_window_status,
                "observed_minute": self.observed_minute,
                "decision_effective_minute": self.decision_effective_minute,
                "online_until_minute": self.online_until_minute,
                "pickup_arrival_minute": self.pickup_arrival_minute,
                "load_window_start_minute": self.load_window_start_minute,
                "deadline_minute": self.load_window_end_minute,
                "expired_by_minutes": _positive_delta(self.decision_effective_minute, self.load_window_end_minute),
                "unreachable_by_minutes": _positive_delta(
                    self.pickup_arrival_minute + LOAD_WINDOW_BUFFER_MINUTES,
                    self.load_window_end_minute,
                ),
                "buffer_minutes": LOAD_WINDOW_BUFFER_MINUTES,
                "online_expired_by_minutes": _positive_delta(self.decision_effective_minute, self.online_until_minute),
            },
        }


def evaluate_cargo_reachability(
    *,
    cargo: dict[str, Any],
    observed_minute: int,
    decision_effective_minute: int,
    pickup_minutes: int,
    finish_minute: int,
    simulation_horizon_minute: int,
) -> CargoReachability:
    load_start, load_end = _parse_load_window(cargo)
    online_until = _parse_online_until(cargo)
    pickup_arrival = int(decision_effective_minute) + int(pickup_minutes)
    hard: list[str] = []
    if online_until is not None and int(decision_effective_minute) > online_until:
        hard.append("cargo_online_expired")
    if load_end is None:
        status = "no_load_window_deadline"
    elif decision_effective_minute >= load_end:
        status = "pickup_window_expired"
        hard.append("load_time_window_expired")
    elif pickup_arrival + LOAD_WINDOW_BUFFER_MINUTES > load_end:
        status = "pickup_window_unreachable"
        hard.append("load_time_window_unreachable")
    else:
        status = "pickup_window_reachable"

    end_reachable = int(finish_minute) <= int(simulation_horizon_minute)
    if not end_reachable:
        hard.append("end_month_unreachable")

    return CargoReachability(
        observed_minute=int(observed_minute),
        decision_effective_minute=int(decision_effective_minute),
        online_until_minute=online_until,
        pickup_arrival_minute=pickup_arrival,
        load_window_start_minute=load_start,
        load_window_end_minute=load_end,
        load_window_status=status,
        end_month_reachable=end_reachable,
        simulator_executable=not hard,
        hard_invalid_reasons=tuple(hard),
    )


def _parse_load_window(cargo: dict[str, Any]) -> tuple[int | None, int | None]:
    load_time = cargo.get("load_time")
    if isinstance(load_time, (list, tuple)) and len(load_time) == 2:
        return parse_wall_time_to_minute(load_time[0]), parse_wall_time_to_minute(load_time[1])
    return None, _parse_deadline(cargo)


def _parse_deadline(cargo: dict[str, Any]) -> int | None:
    for key in (
        "load_time_window_end",
        "load_end_time",
        "loading_end_time",
        "load_deadline",
        "pickup_deadline",
        "latest_load_time",
    ):
        value = cargo.get(key)
        if value is None or value == "":
            continue
        parsed = parse_wall_time_to_minute(value)
        if parsed is not None:
            return parsed
    return None


def _parse_online_until(cargo: dict[str, Any]) -> int | None:
    value = cargo.get("remove_time")
    if value is None or value == "":
        return None
    return parse_wall_time_to_minute(value)


def _positive_delta(value: int, reference: int | None) -> int | None:
    if reference is None:
        return None
    return max(0, int(value) - int(reference))
