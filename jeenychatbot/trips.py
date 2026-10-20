"""Trip planning: resolve places -> route -> fares; confirming assigns a simulated driver.

This module is deterministic (no LLM). The agent and the rule-based parser both
call it, so a ride is always computed the same way.
"""

from __future__ import annotations

import logging
import random
import re

from .driver import simulate_driver
from .geo import haversine_km, in_jordan
from .geocoding import Geocoder, GeocoderUnavailable
from .models import CarType, LatLng, Place, Trip
from .places import PlaceBook
from .pricing import all_fares
from .routing import Router
from .text import clean_place_text, is_current_location_phrase, is_personal_place, parse_coordinates

logger = logging.getLogger(__name__)

MIN_TRIP_KM = 0.05
CITY_RADIUS_KM = 30  # a result said to be "in Irbid" must be within this distance of Irbid

# The city a query is placed in: "Irbid City Center, Irbid" or "... باربد" / "... في اربد" / "... in Irbid".
_TRAILING_CITY = re.compile(r"(?:^|\s)(?:ب|في\s+|in\s+)(?P<city>\S+)$", flags=re.IGNORECASE)


class PlanningError(Exception):
    """A user-facing problem (place not found, same start and end, ...).

    `code` maps to a localized message in `messages.py`.
    """

    def __init__(self, code: str, **details: str) -> None:
        super().__init__(code)
        self.code = code
        self.details = details
        self.role: str | None = None  # "pickup" / "destination" when we know which end failed
        self.start: Place | None = None  # the resolved pickup, if the destination failed


def _point(place: Place | LatLng | None) -> tuple[float, float] | None:
    return (place.lat, place.lng) if place is not None else None


class TripPlanner:
    def __init__(self, geocoder: Geocoder, router: Router, rng: random.Random | None = None) -> None:
        self.geocoder = geocoder
        self.router = router
        self.rng = rng or random.Random()

    # ---------------------------------------------------------------- places
    def resolve(
        self,
        text: str,
        book: PlaceBook,
        current_location: LatLng | None,
        lang: str = "ar",
        near: tuple[float, float] | None = None,
        hint: str | None = None,
    ) -> Place:
        """Turn what the user said ("الدار", "اللي عند دوار الشعب", "البزنس بارك", "موقعي") into a Place.

        `hint` is the LLM's guess of the official name ("King Hussein Business Park, Amman"), so
        nicknames work without listing them anywhere. `near` is the user's area; the geocoder prefers
        matches around it.
        """
        text = clean_place_text(text)
        if not text:
            raise PlanningError("missing_place")

        if is_current_location_phrase(text):
            if current_location is None:
                raise PlanningError("no_current_location")
            name = "موقعي الحالي" if lang == "ar" else "My location"
            return Place(name=name, lat=current_location.lat, lng=current_location.lng, source="current_location")

        coords = parse_coordinates(text)
        if coords:
            place = Place(name=text, lat=coords[0], lng=coords[1], source="coordinates")
        else:
            place = self._resolve_name(text, clean_place_text(hint or ""), book, lang, near or _point(current_location))

        if not in_jordan(place.lat, place.lng):
            raise PlanningError("outside_jordan", place=text)
        return place

    def _resolve_name(self, text: str, hint: str, book: PlaceBook, lang: str, near: tuple[float, float] | None) -> Place:
        candidates = [text] + ([hint] if hint and hint != text else [])

        # 1) Known places (the user's saved places + a small built-in list): instant, works offline.
        for candidate in candidates:
            match = book.lookup(candidate, lang)
            if match and match.lat is not None and match.lng is not None:
                return Place(name=match.name, lat=match.lat, lng=match.lng, source=match.source)  # type: ignore[arg-type]

        # "الدار" / "الشغل" that isn't saved: ask the user, never guess it from the map.
        if is_personal_place(text):
            raise PlanningError("not_saved", place=text)

        # 2) OpenStreetMap search: what the user typed first, then the AI's official name.
        #    A strong match wins at once; a partial one is kept in case nothing better turns up.
        unavailable, partial = False, None
        for candidate in candidates:
            match = book.lookup(candidate, lang)
            query = match.query if match and match.query else candidate
            try:
                result = self.geocoder.geocode(query, lang, near=near)
            except GeocoderUnavailable:
                unavailable = True
                continue
            if result is None or self._outside_named_city(candidate, result, book):
                continue
            if match:
                return Place(name=match.name, lat=result.lat, lng=result.lng, source="landmark")
            if result.exact:
                # Found via the user's words -> keep them; found via the hint -> use the map's name.
                name = text if candidate == text else (result.label or candidate)
                return Place(name=name, lat=result.lat, lng=result.lng, source="geocoder")
            # Partial: show the map's own name, so the user can see what was found and check it.
            partial = partial or Place(
                name=result.label or text, lat=result.lat, lng=result.lng, source="geocoder", asked_as=text
            )
        if partial:
            return partial
        if unavailable:
            raise PlanningError("geo_unavailable", place=text)
        raise PlanningError("not_found", place=text)

    @staticmethod
    def _outside_named_city(query: str, result, book: PlaceBook) -> bool:
        """Real case: "Irbid City Center, Irbid" came back as a "City Center" 97 km away, in another city."""
        parts = [p.strip() for p in re.split(r"[,،]", query)[1:] if p.strip()]
        trailing = _TRAILING_CITY.search(query)
        if trailing:
            parts.append(trailing.group("city"))
        for part in parts:
            city = book.city_point(part)
            if city is not None:
                far = haversine_km(city[0], city[1], result.lat, result.lng) > CITY_RADIUS_KM
                if far:
                    logger.info("Skipping %r for %r: more than %d km from %s", result.label, query, CITY_RADIUS_KM, part)
                return far
        return False

    # ----------------------------------------------------------------- trips
    def plan_trip(
        self,
        start_text: str | None,
        end_text: str | None,
        car_type: CarType,
        book: PlaceBook,
        current_location: LatLng | None = None,
        lang: str = "ar",
        start_hint: str | None = None,
        end_hint: str | None = None,
    ) -> Trip:
        """A new draft trip. Without a pickup, the user's shared location is used (like the real apps)."""
        if not end_text:
            raise PlanningError("missing_end")
        if not start_text:
            if current_location is None:
                raise PlanningError("missing_start")
            start_text = "موقعي"
        start = _tagged(lambda: self.resolve(start_text, book, current_location, lang, hint=start_hint), "pickup")
        end = _tagged(
            lambda: self.resolve(end_text, book, current_location, lang, near=_point(start), hint=end_hint),
            "destination",
            start=start,
        )
        return self._build(start, end, car_type)

    def plan_from(
        self,
        start: Place,
        end_text: str | None,
        car_type: CarType,
        book: PlaceBook,
        current_location: LatLng | None = None,
        lang: str = "ar",
        end_hint: str | None = None,
    ) -> Trip:
        """A new draft trip from an already known pickup (e.g. the previous ride's pickup)."""
        if not end_text:
            raise PlanningError("missing_end")
        end = _tagged(
            lambda: self.resolve(end_text, book, current_location, lang, near=_point(start), hint=end_hint),
            "destination",
            start=start,
        )
        return self._build(start, end, car_type)

    def modify_trip(
        self,
        trip: Trip,
        new_start_text: str | None,
        new_end_text: str | None,
        book: PlaceBook,
        current_location: LatLng | None = None,
        lang: str = "ar",
        start_hint: str | None = None,
        end_hint: str | None = None,
    ) -> Trip:
        """Change only what the user asked for; everything else (including the car type) is kept."""
        if not new_start_text and not new_end_text:
            raise PlanningError("nothing_to_change")
        start = trip.start
        if new_start_text:
            near = _point(current_location) or _point(trip.start)
            start = _tagged(
                lambda: self.resolve(new_start_text, book, current_location, lang, near=near, hint=start_hint), "pickup"
            )
        end = trip.end
        if new_end_text:
            end = _tagged(
                lambda: self.resolve(new_end_text, book, current_location, lang, near=_point(start), hint=end_hint),
                "destination",
            )
        return self._build(start, end, trip.car_type)

    def set_pickup(self, trip: Trip, location: LatLng, lang: str = "ar") -> Trip:
        """The user shared their location: start the ride from there, keep the destination."""
        name = "موقعي الحالي" if lang == "ar" else "My location"
        start = Place(name=name, lat=location.lat, lng=location.lng, source="current_location")
        return self._build(start, trip.end, trip.car_type)

    def pin(self, trip: Trip | None, role: str, place: Place, start: Place | None, car_type: CarType = "economy") -> Trip:
        """The user pinned a point on the map for the pickup or destination (Jeeny's "Set on Map")."""
        if not in_jordan(place.lat, place.lng):
            raise PlanningError("outside_jordan", place=place.name)
        if trip is not None:
            if role == "pickup":
                return self._build(place, trip.end, trip.car_type)
            return self._build(trip.start, place, trip.car_type)
        if role == "destination" and start is not None:
            return self._build(start, place, car_type)
        raise PlanningError("missing_start" if role == "destination" else "missing_end")

    def change_car_type(self, trip: Trip, car_type: CarType) -> Trip:
        """Same route and fares; a confirmed ride goes back to draft (a new car needs a new confirmation)."""
        return trip.model_copy(update={"car_type": car_type, "status": "draft", "driver": None})

    def confirm(self, trip: Trip) -> Trip:
        """Book the ride: assign a simulated driver near the pickup."""
        driver = simulate_driver(trip.start, trip.car_type, snap=self.router.snap, rng=self.rng)
        return trip.model_copy(update={"status": "confirmed", "driver": driver})

    def _build(self, start: Place, end: Place, car_type: CarType) -> Trip:
        if haversine_km(start.lat, start.lng, end.lat, end.lng) < MIN_TRIP_KM:
            raise PlanningError("same_place")
        route = self.router.route((start.lat, start.lng), (end.lat, end.lng))
        logger.info(
            "Trip %s -> %s | %.1f km, %.0f min (%s) | %s",
            start.name, end.name, route.distance_km, route.duration_min, route.source, car_type,
        )
        return Trip(start=start, end=end, car_type=car_type, route=route, quotes=all_fares(route))


def _tagged(resolve, role: str, start: Place | None = None) -> Place:
    """Run a resolve() call and remember which end of the trip failed (so the UI can offer "pin on map")."""
    try:
        return resolve()
    except PlanningError as err:
        err.role = role
        err.start = start
        raise
