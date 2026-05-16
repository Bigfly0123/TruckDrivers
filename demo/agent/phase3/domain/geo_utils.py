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
