from __future__ import annotations

import math
from datetime import datetime


SIMULATION_EPOCH = datetime(2026, 3, 1, 0, 0, 0)
WALL_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius_km = 6371.0
    p1 = math.radians(float(lat1))
    l1 = math.radians(float(lng1))
    p2 = math.radians(float(lat2))
    l2 = math.radians(float(lng2))
    dp = p2 - p1
    dl = l2 - l1
    h = math.sin(dp * 0.5) ** 2 + math.cos(p1) * math.cos(p2) * (math.sin(dl * 0.5) ** 2)
    return 2.0 * radius_km * math.asin(math.sqrt(min(1.0, max(0.0, h))))


def distance_to_minutes(distance_km: float, speed_km_per_hour: float = 60.0) -> int:
    if distance_km <= 0:
        return 1
    return max(1, math.ceil((distance_km / speed_km_per_hour) * 60.0))


def parse_wall_time_to_minute(value: object) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in WALL_TIME_FORMATS:
        try:
            return int((datetime.strptime(text, fmt) - SIMULATION_EPOCH).total_seconds() // 60)
        except ValueError:
            continue
    return None


def interval_overlap(start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
    return int(start_a) < int(end_b) and int(start_b) < int(end_a)


def merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    cleaned = sorted((int(a), int(b)) for a, b in intervals if int(b) > int(a))
    merged: list[tuple[int, int]] = []
    for start, end in cleaned:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            prev_start, prev_end = merged[-1]
            merged[-1] = (prev_start, max(prev_end, end))
    return merged


def longest_span(intervals: list[tuple[int, int]]) -> int:
    merged = merge_intervals(intervals)
    if not merged:
        return 0
    return max(end - start for start, end in merged)


def split_window_for_day(day: int, start_minute_of_day: int, end_minute_of_day: int) -> list[tuple[int, int]]:
    base = int(day) * 1440
    start = base + int(start_minute_of_day)
    end = base + int(end_minute_of_day)
    if end_minute_of_day > start_minute_of_day:
        return [(start, end)]
    return [(start, base + 1440), (base + 1440, base + 1440 + int(end_minute_of_day))]
