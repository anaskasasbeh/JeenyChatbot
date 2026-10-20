"""Pydantic data models shared by the planner, the agent, the API and the frontend."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CarType = Literal["economy", "taxi", "family", "vip"]
Lang = Literal["ar", "en"]
PlaceSource = Literal["saved", "landmark", "geocoder", "current_location", "coordinates", "pinned"]
TripStatus = Literal["draft", "confirmed"]
Action = Literal[
    "new_trip", "car_changed", "trip_modified", "trip_confirmed", "trip_cancelled", "message", "error"
]
TripAction = Literal["car", "confirm", "cancel", "pickup_here", "pin"]
Mode = Literal["ai", "rules"]

MAX_MESSAGE_CHARS = 300
MAX_HISTORY_TURNS = 12
MAX_SAVED_PLACES = 20
MAX_ROUTE_POINTS = 5000


class LatLng(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class SavedPlace(LatLng):
    """A place the user saved in their own browser, e.g. "الدار"."""

    name: str = Field(min_length=1, max_length=40)
    aliases: list[str] = Field(default_factory=list, max_length=5)


class Place(LatLng):
    """A resolved location with a display name and where it came from."""

    name: str
    source: PlaceSource
    # Set when the map only partly matched what the user asked for: the words they used,
    # so the reply can ask them to check the place (and a pin keeps their words).
    asked_as: str | None = Field(default=None, max_length=120)


class RouteInfo(BaseModel):
    distance_km: float = Field(ge=0)
    duration_min: float = Field(ge=0)
    # [[lat, lng], ...] so the frontend can draw it directly with Leaflet.
    geometry: list[tuple[float, float]] = Field(default_factory=list, max_length=MAX_ROUTE_POINTS)
    source: Literal["osrm", "estimate"]


class Driver(LatLng):
    """A simulated driver. Nothing here is a real person."""

    name: str
    name_en: str = ""
    car_model: str
    distance_m: int = Field(ge=0)
    eta_min: int = Field(ge=1)


class Trip(BaseModel):
    """The single source of truth for the current ride. Held by the client between turns.

    A trip starts as a "draft" (route + fares, no driver). The user can change the pickup,
    destination or car type freely; confirming assigns a simulated driver. Any later change
    turns it back into a draft that needs a new confirmation, like a real ride app.
    """

    start: Place
    end: Place
    car_type: CarType = "economy"
    route: RouteInfo
    quotes: dict[CarType, float]
    status: TripStatus = "draft"
    driver: Driver | None = None

    @property
    def price(self) -> float:
        return self.quotes[self.car_type]


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)


class PinRequest(BaseModel):
    """Sent with a reply when a place could not be found: the UI offers to pin it on the map."""

    role: Literal["pickup", "destination"]
    label: str = Field(max_length=80)
    start: Place | None = None  # already-resolved pickup when there is no trip yet
    save: bool = False  # a personal place ("الدار"): the UI also adds it to the saved places
    adjust: bool = False  # the place was found but should be checked: the button offers to adjust it


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    lang: Lang = "ar"
    history: list[ChatTurn] = Field(default_factory=list, max_length=MAX_HISTORY_TURNS)
    trip: Trip | None = None
    saved_places: list[SavedPlace] = Field(default_factory=list, max_length=MAX_SAVED_PLACES)
    current_location: LatLng | None = None
    # The place the bot just said it couldn't find, so "it's near X" can be understood.
    pending_pin: PinRequest | None = None


class ChatResponse(BaseModel):
    reply: str
    action: Action
    mode: Mode
    trip: Trip | None = None
    pin: PinRequest | None = None
    need_location: bool = False  # the UI asks the browser for the location, then sends the message again


class TripActionRequest(BaseModel):
    """Buttons in the UI (car type, confirm, cancel, use my location, pin on map): handled without the LLM."""

    trip: Trip | None = None
    action: TripAction
    car_type: CarType | None = None
    current_location: LatLng | None = None
    pin: PinRequest | None = None
    point: LatLng | None = None
    lang: Lang = "ar"
