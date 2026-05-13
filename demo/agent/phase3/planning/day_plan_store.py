from __future__ import annotations

from agent.phase3.planning.day_plan import DayPlan


class DayPlanStore:
    def __init__(self) -> None:
        self._plans: dict[tuple[str, int], DayPlan] = {}

    def get(self, driver_id: str, day: int) -> DayPlan | None:
        return self._plans.get((driver_id, day))

    def set(self, plan: DayPlan) -> None:
        self._plans[(plan.driver_id, plan.day)] = plan

    def clear_driver(self, driver_id: str) -> None:
        for key in [key for key in self._plans if key[0] == driver_id]:
            self._plans.pop(key, None)
