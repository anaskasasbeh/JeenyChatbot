"""Driving distance, time and route shape between two points.

Uses the free OSRM HTTP API (OpenStreetMap data). The public demo server is
"best effort" with no uptime guarantee (https://github.com/Project-OSRM/osrm-backend/wiki/API%20Usage%20Policy),
so every call has fallbacks: a second OSRM server (FOSSGIS, https://routing.openstreetmap.de),
then a straight-line estimate that is clearly flagged as `source="estimate"`.
"""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

from .geo import haversine_km
from .models import RouteInfo

logger = logging.getLogger(__name__)

ROAD_FACTOR = 1.3  # roads are longer than the straight line between two points
ESTIMATE_SPEED_KMH = 45.0


class Router(Protocol):
    def route(self, start: tuple[float, float], end: tuple[float, float]) -> RouteInfo: ...

    def snap(self, point: tuple[float, float]) -> tuple[float, float]: ...


def estimate_route(start: tuple[float, float], end: tuple[float, float]) -> RouteInfo:
    """Offline estimate used when the routing service is unavailable."""
    km = haversine_km(*start, *end) * ROAD_FACTOR
    return RouteInfo(
        distance_km=round(km, 2),
        duration_min=round(km / ESTIMATE_SPEED_KMH * 60, 1),
        geometry=[start, end],
        source="estimate",
    )


MAX_ROUTE_POINTS = 1500  # enough for a smooth line on the map, small enough to send back with every message


def downsample(points: list[tuple[float, float]], max_points: int = MAX_ROUTE_POINTS) -> list[tuple[float, float]]:
    """Keep every n-th point (and always the last one) so long routes stay light.

    A full Irbid -> Aqaba route has thousands of points: more than the response allows, which
    would otherwise end in a straight-line estimate instead of the real road.
    """
    if len(points) <= max_points:
        return points
    step = -(-(len(points) - 1) // (max_points - 1))  # ceiling division; leaves room for the last point
    sampled = points[::step]
    if sampled[-1] != points[-1]:
        sampled.append(points[-1])
    return sampled


class OSRMRouter:
    """Tries each OSRM server in order (public demo first, then the FOSSGIS mirror)."""

    def __init__(
        self,
        base_urls: str | list[str],
        user_agent: str,
        timeout_s: float = 12.0,
        client: httpx.Client | None = None,
    ) -> None:
        if isinstance(base_urls, str):
            base_urls = [u for u in base_urls.split(",") if u.strip()]
        self.base_urls = [u.strip().rstrip("/") for u in base_urls]
        self._client = client or httpx.Client(timeout=timeout_s, headers={"User-Agent": user_agent})

    def route(self, start: tuple[float, float], end: tuple[float, float]) -> RouteInfo:
        coords = f"{start[1]},{start[0]};{end[1]},{end[0]}"  # OSRM expects lng,lat
        for base_url in self.base_urls:
            try:
                resp = self._client.get(
                    f"{base_url}/route/v1/driving/{coords}",
                    params={"overview": "full", "geometries": "geojson"},
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") != "Ok" or not data.get("routes"):
                    raise ValueError(f"OSRM returned {data.get('code')}")
                best = data["routes"][0]
                geometry = [(round(lat, 5), round(lng, 5)) for lng, lat in best["geometry"]["coordinates"]]
                return RouteInfo(
                    distance_km=round(best["distance"] / 1000, 2),
                    duration_min=round(best["duration"] / 60, 1),
                    geometry=downsample(geometry),
                    source="osrm",
                )
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                logger.warning("Routing via %s failed: %s", base_url, exc)
        logger.warning("All routing servers failed, using a straight-line estimate.")
        return estimate_route(start, end)

    def snap(self, point: tuple[float, float]) -> tuple[float, float]:
        """Move a point onto the nearest road (used to place the simulated driver)."""
        for base_url in self.base_urls:
            try:
                resp = self._client.get(f"{base_url}/nearest/v1/driving/{point[1]},{point[0]}")
                resp.raise_for_status()
                lng, lat = resp.json()["waypoints"][0]["location"]
                return round(lat, 6), round(lng, 6)
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
                logger.info("Snap-to-road via %s unavailable: %s", base_url, exc)
        return point
