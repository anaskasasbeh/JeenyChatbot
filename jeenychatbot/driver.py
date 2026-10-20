"""A simulated driver near the pickup point. Names and cars are invented for the demo."""

from __future__ import annotations

import random

from .geo import destination_point, haversine_km
from .models import CarType, Driver, Place

CITY_SPEED_KMH = 25.0

_NAMES = [
    ("أبو أحمد", "Abu Ahmad"),
    ("أبو خالد", "Abu Khaled"),
    ("أبو محمد", "Abu Mohammad"),
    ("أبو علي", "Abu Ali"),
    ("أبو يزن", "Abu Yazan"),
    ("أبو سامر", "Abu Samer"),
    ("أبو رامي", "Abu Rami"),
    ("أبو فادي", "Abu Fadi"),
]
_CARS: dict[CarType, list[str]] = {
    "economy": ["Hyundai Elantra", "Kia Cerato", "Toyota Corolla"],
    "taxi": ["Hyundai Elantra", "Toyota Corolla"],
    "family": ["Kia Carnival", "Hyundai H-1", "Toyota Innova"],
    "vip": ["Mercedes E-Class", "BMW 5 Series", "Lexus ES"],
}


def simulate_driver(pickup: Place, car_type: CarType, snap=None, rng: random.Random | None = None) -> Driver:
    """Place a driver 300-1500 m from the pickup, optionally snapped to the nearest road."""
    rng = rng or random.Random()
    lat, lng = destination_point(pickup.lat, pickup.lng, rng.uniform(300, 1500), rng.uniform(0, 360))
    if snap is not None:
        lat, lng = snap((lat, lng))
    distance_m = int(haversine_km(pickup.lat, pickup.lng, lat, lng) * 1000)
    eta_min = max(1, round(distance_m * 1.3 / 1000 / CITY_SPEED_KMH * 60))
    name_ar, name_en = rng.choice(_NAMES)
    return Driver(
        name=name_ar,
        name_en=name_en,
        car_model=rng.choice(_CARS[car_type]),
        lat=round(lat, 6),
        lng=round(lng, 6),
        distance_m=distance_m,
        eta_min=eta_min,
    )
