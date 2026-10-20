"""Known places: public landmarks shipped with the project + the user's own saved places.

Lookup order (most trusted first):
1. exact match on the user's saved places ("الدار"),
2. exact match on landmark names/aliases ("الجامعة الأردنية"),
3. a strict fuzzy match for typos ("اليرموكك"), only for longer names.

The old version used substring matching, so "الجامعة الأردنية" matched the saved
place "الجامعة" (Yarmouk). Exact-then-strict-fuzzy matching fixes that.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz, process

from .config import DATA_DIR
from .models import SavedPlace
from .text import name_variants

logger = logging.getLogger(__name__)

PLACES_FILE = DATA_DIR / "places.json"
FUZZY_MIN_CHARS = 6
FUZZY_MIN_SCORE = 88


@dataclass(frozen=True)
class Landmark:
    id: str
    kind: str
    name_ar: str
    name_en: str
    query: str
    aliases: tuple[str, ...] = ()
    lat: float | None = None
    lng: float | None = None

    @property
    def has_coordinates(self) -> bool:
        return self.lat is not None and self.lng is not None

    def display_name(self, lang: str) -> str:
        return self.name_en if lang == "en" else self.name_ar


@dataclass(frozen=True)
class PlaceMatch:
    """Result of a lookup. Coordinates may be missing for a landmark not yet geocoded."""

    name: str
    source: str  # "saved" or "landmark"
    lat: float | None = None
    lng: float | None = None
    query: str | None = None  # what to send to the geocoder when coordinates are missing


@dataclass
class PlaceBook:
    landmarks: list[Landmark]
    saved_places: list[SavedPlace] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._saved_index: dict[str, SavedPlace] = {}
        for place in self.saved_places:
            for name in (place.name, *place.aliases):
                for key in name_variants(name)[:1]:  # saved places: exact normalized form only
                    self._saved_index.setdefault(key, place)
        self._landmark_index: dict[str, Landmark] = {}
        self._city_index: dict[str, Landmark] = {}
        for lm in self.landmarks:
            for name in (lm.name_ar, lm.name_en, *lm.aliases):
                for key in name_variants(name):
                    self._landmark_index.setdefault(key, lm)
                    if lm.kind == "city" and lm.has_coordinates:
                        self._city_index.setdefault(key, lm)

    def city_point(self, text: str) -> tuple[float, float] | None:
        """Coordinates of a known city named exactly by `text` ("Irbid", "باربد"), else None."""
        for key in name_variants(text):
            lm = self._city_index.get(key)
            if lm is not None:
                return lm.lat, lm.lng  # type: ignore[return-value]
        return None

    # ------------------------------------------------------------------ lookup
    def lookup(self, text: str, lang: str = "ar") -> PlaceMatch | None:
        """Find a known place for free text, or None if it should go to the geocoder."""
        variants = name_variants(text)
        for key in variants:
            if key in self._saved_index:
                return self._from_saved(self._saved_index[key])
        for key in variants:
            if key in self._landmark_index:
                return self._from_landmark(self._landmark_index[key], lang)
        return self._fuzzy(variants, lang)

    def _fuzzy(self, variants: list[str], lang: str) -> PlaceMatch | None:
        query = variants[0] if variants else ""
        if len(query) < FUZZY_MIN_CHARS:
            return None
        choices = [k for k in self._landmark_index if len(k) >= FUZZY_MIN_CHARS]
        best = process.extractOne(query, choices, scorer=fuzz.ratio, score_cutoff=FUZZY_MIN_SCORE)
        if not best:
            return None
        key, score, _ = best
        logger.info("Fuzzy place match %r -> %r (score %.0f)", query, key, score)
        return self._from_landmark(self._landmark_index[key], lang)

    @staticmethod
    def _from_saved(place: SavedPlace) -> PlaceMatch:
        return PlaceMatch(name=place.name, source="saved", lat=place.lat, lng=place.lng)

    @staticmethod
    def _from_landmark(lm: Landmark, lang: str) -> PlaceMatch:
        return PlaceMatch(
            name=lm.display_name(lang),
            source="landmark",
            lat=lm.lat,
            lng=lm.lng,
            query=lm.query,
        )

    def saved_names(self) -> list[str]:
        return [p.name for p in self.saved_places]


# ---------------------------------------------------------------------- loading
def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_landmarks(path: Path = PLACES_FILE) -> tuple[Landmark, ...]:
    """Load landmarks once per process."""
    try:
        data = _read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Could not read %s: %s", path, exc)
        return ()
    landmarks = tuple(
        Landmark(
            id=item["id"],
            kind=item.get("kind", "landmark"),
            name_ar=item["name_ar"],
            name_en=item["name_en"],
            query=item["query"],
            aliases=tuple(item.get("aliases", [])),
            lat=item.get("lat"),
            lng=item.get("lng"),
        )
        for item in data.get("landmarks", [])
    )
    missing = sum(1 for lm in landmarks if not lm.has_coordinates)
    logger.info("Loaded %d landmarks (%d without coordinates yet)", len(landmarks), missing)
    return landmarks


def load_demo_saved_places(path: Path = PLACES_FILE) -> list[dict]:
    """Demo "saved places" the frontend pre-fills on a first visit (with coordinates if known)."""
    data = _read_json(path)
    by_id = {lm.id: lm for lm in load_landmarks(path)}
    result = []
    for item in data.get("demo_saved_places", []):
        lat, lng = item.get("lat"), item.get("lng")
        landmark = by_id.get(item.get("landmark", ""))
        if (lat is None or lng is None) and landmark and landmark.has_coordinates:
            lat, lng = landmark.lat, landmark.lng
        result.append(
            {
                "name": item["name"],
                "aliases": item.get("aliases", []),
                "lat": lat,
                "lng": lng,
                "query": item.get("query") or (landmark.query if landmark else None),
            }
        )
    return result


def build_place_book(saved_places: list[SavedPlace] | None = None) -> PlaceBook:
    return PlaceBook(landmarks=list(load_landmarks()), saved_places=list(saved_places or []))


__all__ = [
    "Landmark",
    "PlaceBook",
    "PlaceMatch",
    "build_place_book",
    "load_demo_saved_places",
    "load_landmarks",
]
