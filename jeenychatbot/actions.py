"""What the assistant can do, shared by the LLM agent, the rule-based fallback and the UI buttons.

Keeping one implementation means a ride is planned the same way whichever "brain"
understood the message, and the result (reply + updated trip) is recorded in one place.

Context rules (the trip is the memory of the conversation):
* a new pickup keeps the destination, a new destination keeps the pickup,
* the car type is kept unless the user asks for another one,
* any change to a confirmed ride turns it back into a draft that needs confirming,
* a place that can't be found on the map can be pinned by the user instead.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from . import messages
from .models import Action, CarType, LatLng, PinRequest, Place, Trip
from .places import PlaceBook
from .trips import PlanningError, TripPlanner

logger = logging.getLogger(__name__)


@dataclass
class TurnContext:
    """Everything one chat turn needs, plus the outcome it produced."""

    planner: TripPlanner
    book: PlaceBook
    lang: str
    trip: Trip | None = None
    current_location: LatLng | None = None
    action: Action = "message"
    pin: PinRequest | None = None
    pending: PinRequest | None = None  # a place we just couldn't find (the user may now say what's near it)
    need_location: bool = False  # the request needs the user's location, which we don't have
    tool_calls: list[dict] = field(default_factory=list)  # for evaluation / debugging

    # ----------------------------------------------------------------- actions
    def request_trip(
        self,
        destination: str | None,
        pickup: str | None = None,
        car_type: CarType | None = None,
        destination_hint: str | None = None,
        pickup_hint: str | None = None,
    ) -> str:
        self.tool_calls.append({
            "name": "request_trip", "pickup": pickup, "destination": destination, "car_type": car_type,
            "pickup_hint": pickup_hint, "destination_hint": destination_hint,
        })
        current = self.trip
        if current and not destination and pickup:
            # Only a new pickup was given while a ride exists: keep the destination.
            return self._modify(pickup, None, pickup_hint, None)
        car = car_type or (current.car_type if current else "economy")
        # No pickup given while a ride exists: keep its pickup (the 📍 button already moves it when tapped).
        keep_start = not pickup and current is not None

        def compute() -> Trip:
            if keep_start:  # keep the known pickup instead of asking again
                return self.planner.plan_from(
                    current.start, destination, car, self.book, self.current_location, self.lang, end_hint=destination_hint
                )
            return self.planner.plan_trip(
                pickup, destination, car, self.book, self.current_location, self.lang,
                start_hint=pickup_hint, end_hint=destination_hint,
            )

        return self._run(compute, action="new_trip", reply=lambda new: messages.trip_ready(new, self.lang))

    def modify_trip(
        self,
        new_pickup: str | None = None,
        new_destination: str | None = None,
        pickup_hint: str | None = None,
        destination_hint: str | None = None,
    ) -> str:
        self.tool_calls.append({
            "name": "modify_trip", "pickup": new_pickup, "destination": new_destination,
            "pickup_hint": pickup_hint, "destination_hint": destination_hint,
        })
        return self._modify(new_pickup, new_destination, pickup_hint, destination_hint)

    def _modify(self, new_pickup, new_destination, pickup_hint, destination_hint) -> str:
        if self.trip is None:
            if new_destination:  # nothing to modify yet: treat it as a new request
                return self.request_trip(new_destination, new_pickup, None, destination_hint, pickup_hint)
            return self._fail(PlanningError("no_trip"))
        old = self.trip
        return self._run(
            lambda: self.planner.modify_trip(
                old, new_pickup, new_destination, self.book, self.current_location, self.lang,
                start_hint=pickup_hint, end_hint=destination_hint,
            ),
            action="trip_modified",
            reply=lambda new: messages.trip_modified(old, new, old.status == "confirmed", self.lang),
        )

    def change_car_type(self, car_type: CarType) -> str:
        self.tool_calls.append({"name": "change_car_type", "car_type": car_type})
        if self.trip is None:
            return self._fail(PlanningError("no_trip"))
        old = self.trip
        if car_type == old.car_type:
            return messages.car_changed(old, old.car_type, False, self.lang)
        return self._run(
            lambda: self.planner.change_car_type(old, car_type),
            action="car_changed",
            reply=lambda new: messages.car_changed(new, old.car_type, old.status == "confirmed", self.lang),
        )

    def confirm_trip(self) -> str:
        self.tool_calls.append({"name": "confirm_trip"})
        if self.trip is None:
            return self._fail(PlanningError("no_trip"))
        if self.trip.status == "confirmed":
            return messages.already_confirmed(self.lang)
        draft = self.trip
        return self._run(
            lambda: self.planner.confirm(draft),
            action="trip_confirmed",
            reply=lambda new: messages.trip_confirmed(new, self.lang),
        )

    def cancel_trip(self) -> str:
        self.tool_calls.append({"name": "cancel_trip"})
        if self.trip is None:
            return self._fail(PlanningError("no_trip"))
        self.trip = None
        self.action = "trip_cancelled"
        return messages.trip_cancelled(self.lang)

    def use_current_location_as_pickup(self) -> str:
        """UI: the user shared their location while a ride exists."""
        if self.trip is None or self.current_location is None:
            return self._fail(PlanningError("no_trip" if self.trip is None else "no_current_location"))
        old, here = self.trip, self.current_location
        return self._run(
            lambda: self.planner.set_pickup(old, here, self.lang),
            action="trip_modified",
            reply=lambda new: messages.pickup_updated(new, old.status == "confirmed", self.lang),
        )

    def pin_on_map(self, pin: PinRequest, point: LatLng) -> str:
        """UI: the user pinned the place we couldn't find. It keeps the name they used."""
        place = Place(name=pin.label, lat=point.lat, lng=point.lng, source="pinned")
        start = pin.start
        if start is None and self.trip is None and self.current_location is not None:
            here = self.current_location
            start = Place(name="موقعي الحالي" if self.lang == "ar" else "My location",
                          lat=here.lat, lng=here.lng, source="current_location")
        old = self.trip
        action: Action = "trip_modified" if old else "new_trip"
        return self._run(
            lambda: self.planner.pin(old, pin.role, place, start),
            action=action,
            reply=lambda new: messages.trip_modified(old, new, old.status == "confirmed", self.lang)
            if old
            else messages.trip_ready(new, self.lang),
        )

    def place_near(self, nearby: str, hint: str | None = None) -> str:
        """The user answered "what's near it?": put the missing place at that landmark, like a driver would."""
        wanted = self.pending
        if wanted is None:  # nothing was missing: treat it as a destination
            return self.modify_trip(None, nearby, None, hint) if self.trip else self.request_trip(nearby, None, None, hint)
        self.tool_calls.append({"name": "place_near", "nearby": nearby, "hint": hint})
        anchor = wanted.start or (self.trip.start if self.trip else None) or self.current_location
        try:
            spot = self.planner.resolve(
                nearby, self.book, self.current_location, self.lang,
                near=(anchor.lat, anchor.lng) if anchor else None, hint=hint,
            )
        except PlanningError as err:
            return self._fail(err)
        reply = self.pin_on_map(wanted, LatLng(lat=spot.lat, lng=spot.lng))
        if self.action in ("new_trip", "trip_modified") and self.trip:
            start = self.trip.start if wanted.role == "destination" else None
            self.pin = PinRequest(role=wanted.role, label=wanted.label, start=start, save=wanted.save, adjust=True)
            reply += " " + messages.placed_near(wanted.label, spot.name, self.lang)
        return reply

    # ----------------------------------------------------------------- helpers
    def _run(self, compute, action: Action, reply) -> str:
        old = self.trip
        try:
            new_trip = compute()
        except PlanningError as err:
            return self._fail(err)
        except Exception:  # network surprises etc. must not crash the chat
            logger.exception("Unexpected error while planning (%s)", action)
            self.action = "error"
            return messages.error_message("internal", self.lang)
        self.trip = new_trip
        self.action = action
        return reply(new_trip) + self._check_note(old, new_trip)

    def _check_note(self, old: Trip | None, new: Trip) -> str:
        """A place that only partly matched the user's words: ask them to check it, and offer to adjust it."""
        before = {"pickup": old.start, "destination": old.end} if old else {}
        for role, place in (("pickup", new.start), ("destination", new.end)):
            prev = before.get(role)
            if place.asked_as and (prev is None or (prev.lat, prev.lng) != (place.lat, place.lng)):
                self.pin = PinRequest(
                    role=role, label=place.asked_as[:80], start=new.start if role == "destination" else None, adjust=True
                )
                return " " + messages.check_place(place.name, self.lang)
        return ""

    def _fail(self, err: PlanningError) -> str:
        self.action = "message"
        self.need_location = err.code in ("missing_start", "no_current_location") and self.current_location is None
        if err.code in ("not_found", "not_saved") and err.role:
            # Let the user pin it on the map, keeping the name they used.
            self.pin = PinRequest(
                role=err.role, label=err.details.get("place", "")[:80], start=err.start, save=err.code == "not_saved"
            )
            return messages.error_message(f"{err.code}_pin", self.lang, **err.details)
        return messages.error_message(err.code, self.lang, **err.details)
