from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.agent_models import CandidateScore


@dataclass(frozen=True)
class BlockedCandidate:
    cargo_id: str
    estimated_profit: float
    pickup_deadhead_km: float
    estimated_duration_minutes: int
    block_reasons: tuple[str, ...]
    hard_block: bool
    earliest_possible_minute: int | None
    explanation: str


@dataclass(frozen=True)
class RecoveryCandidate:
    action: dict[str, Any]
    recovery_type: str
    expected_effect: str
    estimated_cost: float
    unlock_reason: str
    safety_prechecked: bool


@dataclass(frozen=True)
class CandidatePool:
    executable: tuple[CandidateScore, ...]
    risky: tuple[CandidateScore, ...]
    blocked: tuple[BlockedCandidate, ...]
    recovery: tuple[RecoveryCandidate, ...]
    filter_stats: dict[str, int]
    total_visible_items: int

    @property
    def has_executable_take(self) -> bool:
        return any(c.action == "take_order" for c in self.executable)

    @property
    def has_risky_take(self) -> bool:
        return any(c.action == "take_order" for c in self.risky)

    @property
    def top_executable(self) -> CandidateScore | None:
        takes = [c for c in self.executable if c.action == "take_order"]
        return takes[0] if takes else None

    @property
    def top_risky(self) -> CandidateScore | None:
        takes = [c for c in self.risky if c.action == "take_order"]
        return takes[0] if takes else None

    @property
    def dominant_block_reasons(self) -> list[str]:
        if not self.filter_stats:
            return []
        total = sum(self.filter_stats.values())
        if total == 0:
            return []
        return sorted(self.filter_stats.keys(), key=lambda k: self.filter_stats[k], reverse=True)[:3]

    def to_log_dict(self) -> dict[str, Any]:
        return {
            "exec": len(self.executable),
            "risky": len(self.risky),
            "blocked": len(self.blocked),
            "recovery": len(self.recovery),
            "filters": self.filter_stats,
            "visible": self.total_visible_items,
        }
