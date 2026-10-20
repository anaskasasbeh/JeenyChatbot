"""The one fare formula, used by the planner, the trip panel and the replies alike.

Prices are a simulated tariff for the demo, not real Jeeny prices.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import CarType, RouteInfo

BASE_FARE_JOD = 0.50
PER_KM_JOD = 0.25
PER_MIN_JOD = 0.05


@dataclass(frozen=True)
class CarOption:
    id: CarType
    label_ar: str
    label_en: str
    seats: int
    multiplier: float

    def label(self, lang: str) -> str:
        return self.label_en if lang == "en" else self.label_ar


CAR_OPTIONS: dict[CarType, CarOption] = {
    "economy": CarOption("economy", "عادية", "Economy", 4, 1.00),
    "taxi": CarOption("taxi", "تاكسي", "Taxi", 4, 1.15),
    "family": CarOption("family", "عائلية", "Family", 7, 1.30),
    "vip": CarOption("vip", "VIP", "VIP", 4, 1.50),
}


def fare(route: RouteInfo, car_type: CarType) -> float:
    """Fare in Jordanian dinars, rounded to 2 decimals."""
    base = BASE_FARE_JOD + route.distance_km * PER_KM_JOD + route.duration_min * PER_MIN_JOD
    return round(base * CAR_OPTIONS[car_type].multiplier, 2)


def all_fares(route: RouteInfo) -> dict[CarType, float]:
    """Fares for every car type, so the UI can switch car type instantly without an LLM call."""
    return {car: fare(route, car) for car in CAR_OPTIONS}
