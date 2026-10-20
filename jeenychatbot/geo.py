"""Small geometry helpers (no external dependencies)."""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088

# Generous bounding box around Jordan (south, west, north, east).
JORDAN_BBOX = (29.0, 34.8, 33.5, 39.5)


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two points, in kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def destination_point(lat: float, lng: float, distance_m: float, bearing_deg: float) -> tuple[float, float]:
    """Point reached by travelling `distance_m` from (lat, lng) on a given compass bearing."""
    d = distance_m / 1000 / EARTH_RADIUS_KM
    b = math.radians(bearing_deg)
    p1, l1 = math.radians(lat), math.radians(lng)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


def in_jordan(lat: float, lng: float) -> bool:
    south, west, north, east = JORDAN_BBOX
    return south <= lat <= north and west <= lng <= east
