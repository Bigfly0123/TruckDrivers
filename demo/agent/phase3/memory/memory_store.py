from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from agent.phase3.memory.memory_schema import DriverMemory, FailurePattern, ReflectionHint


class MemoryStore:
    """Small run-local memory with optional JSONL audit output."""

    def __init__(self, log_dir: Path | None = None) -> None:
        self._failures: dict[str, list[FailurePattern]] = {}
        self._hints: dict[str, list[ReflectionHint]] = {}
        self._seen_failures: set[str] = set()
        self._seen_hints: set[str] = set()
        self._log_dir = log_dir or Path(__file__).resolve().parents[3] / "results" / "logs"
        self._failure_path = self._log_dir / "memory_store.jsonl"
        self._hint_path = self._log_dir / "reflection_hints.jsonl"

    def add_failure(self, pattern: FailurePattern) -> bool:
        if pattern.pattern_id in self._seen_failures:
            return False
        self._seen_failures.add(pattern.pattern_id)
        self._failures.setdefault(pattern.driver_id, []).append(pattern)
        self._write_jsonl(self._failure_path, asdict(pattern))
        return True

    def add_hint(self, hint: ReflectionHint) -> bool:
        if hint.hint_id in self._seen_hints:
            return False
        self._seen_hints.add(hint.hint_id)
        self._hints.setdefault(hint.driver_id, []).append(hint)
        self._write_jsonl(self._hint_path, asdict(hint))
        return True

    def get_driver_memory(self, driver_id: str) -> DriverMemory:
        failures = tuple(self._failures.get(driver_id, ())[-20:])
        hints = tuple(self._hints.get(driver_id, ())[-10:])
        last_day = None
        if failures:
            last_day = failures[-1].day_index
        return DriverMemory(driver_id=driver_id, recent_failures=failures, active_hints=hints, last_updated_day=last_day)

    def get_active_hints(self, driver_id: str, day_index: int | None, limit: int = 5) -> list[ReflectionHint]:
        hints = self._hints.get(driver_id, [])
        active: list[ReflectionHint] = []
        for hint in reversed(hints):
            if day_index is not None and hint.expires_after_day is not None and day_index > hint.expires_after_day:
                continue
            active.append(hint)
            if len(active) >= limit:
                break
        return list(reversed(active))

    def expire_old_hints(self, day_index: int | None) -> None:
        if day_index is None:
            return
        for driver_id, hints in list(self._hints.items()):
            self._hints[driver_id] = [
                hint for hint in hints
                if hint.expires_after_day is None or day_index <= hint.expires_after_day
            ]

    def save(self) -> None:
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> None:
        return None

    def _write_jsonl(self, path: Path, payload: dict[str, object]) -> None:
        try:
            self._log_dir.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as file:
                file.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        except Exception:
            return
