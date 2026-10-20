"""Turn a place name into coordinates using free OpenStreetMap services.

Providers are tried in order: Nominatim, then Photon. Both are free and keyless, and
both have usage policies we must respect:

* Nominatim (https://operations.osmfoundation.org/policies/nominatim/):
  max 1 request/second, an identifying User-Agent, cache results, no autocomplete,
  show "© OpenStreetMap contributors". We only geocode when a user asks for a trip.
* Photon (https://photon.komoot.io): fair use, same courtesy rules.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Protocol

import httpx
from rapidfuzz import fuzz

from .geo import JORDAN_BBOX, in_jordan
from .text import contains_arabic, normalize

logger = logging.getLogger(__name__)

NEAR_DEG = 0.35  # half-size of the 'near the user' search box (~40 km)


# ------------------------------------------------------------ relevance check
# The map services return their *closest* match, even a poor one: "شركة مينا ديفز" came back
# as "شارع مينا", a street that only shares one word. So each result gets a score:
#   strong  -> used as is,
#   partial -> used, but the user is asked to check it on the map (a typo or a dialect word
#              such as "الشط" for "الشاطئ" must not end in "not found"),
#   zero    -> rejected (e.g. only the city of "Mena Devs, Amman" matched).
def _tokens(text: str) -> list[str]:
    result = []
    for tok in normalize(text).split():
        # "الملك" ~ "ملك", "بالعقبة" ~ "عقبة", "والتكنولوجيا" ~ "تكنولوجيا"
        for prefix in ("بال", "وال", "لل", "ال"):
            if tok.startswith(prefix) and len(tok) - len(prefix) >= 3:
                tok = tok[len(prefix):]
                break
        if len(tok) > 1:
            result.append(tok)
    return result


def _token_set(words: str) -> set[str]:
    return {tok for word in words.split() for tok in _tokens(word)}


# Words that say what kind of place it is, not which one.
_KIND_WORDS = _token_set(
    "شركة مكتب محل مؤسسة مول مطعم مستشفى صيدلية فندق مدرسة جامعة كلية بنك مسجد جامع نادي كافيه قهوة "
    "company co ltd office shop store mall restaurant hospital pharmacy hotel school university college "
    "bank mosque club cafe coffee the al el of في عند"
)
# Asking for a road (or a roundabout, bridge...) is the only reason to accept a road as the answer.
_ROAD_WORDS = _token_set(
    "شارع طريق اوتوستراد اتوستراد بوليفارد دوار اشارة اشارات جسر نفق تقاطع مثلث "
    "street st road rd avenue ave highway hwy boulevard circle roundabout bridge tunnel interchange junction"
)
MIN_TOKEN_SCORE = 80  # how close two words must be ("hawwara" ~ "huwwara", "عبدالل" ~ "عبدالله")
STRONG_MATCH = 0.6  # share of the asked words the result's name must contain to be used without a check
UNVERIFIED = 0.5  # what we can't verify word by word counts as a partial match


def match_score(query: str, names: list[str], category: str = "") -> float:
    """0 = not what was asked, below STRONG_MATCH = partial (ask the user to check), else strong."""
    main = re.split(r"[,،]", query)[0]  # "Mena Devs, Amman" -> "Mena Devs" (the city is only context)
    wanted = [tok for tok in _tokens(main) if tok not in _KIND_WORDS]
    comparable = [n for n in names if n and contains_arabic(n) == contains_arabic(main)]
    if not wanted:
        score = 1.0  # only kind words ("المستشفى"): any match of that kind will do
    elif not comparable:
        score = UNVERIFIED  # an Arabic name vs an English query can't be compared word by word
    else:
        score = 0.0
        for name in comparable:
            have = _tokens(name)
            hits = sum(1 for tok in wanted if any(fuzz.ratio(tok, other) >= MIN_TOKEN_SCORE for other in have))
            score = max(score, hits / len(wanted))
    if category == "highway" and not _ROAD_WORDS.intersection(_tokens(query)):
        score = min(score, UNVERIFIED)  # a road, but the user didn't ask for a road
    return score


def _best(candidates: list[tuple[float, GeocodeResult]]) -> GeocodeResult | None:
    """The first strong match, else the first partial one (marked as needing a check)."""
    for score, result in candidates:
        if score >= STRONG_MATCH:
            return result
    for score, result in candidates:
        if score > 0:
            return GeocodeResult(result.lat, result.lng, result.label, result.provider, exact=False)
    return None


@dataclass(frozen=True)
class GeocodeResult:
    lat: float
    lng: float
    label: str
    provider: str
    exact: bool = True  # False: a partial match the user should double-check on the map


class GeocoderUnavailable(Exception):
    """Every provider failed (network/outage), as opposed to "no such place"."""


class Geocoder(Protocol):
    def geocode(
        self, query: str, lang: str = "ar", feature_type: str | None = None, near: tuple[float, float] | None = None
    ) -> GeocodeResult | None: ...


class _MinInterval:
    """Thread-safe 'at most one call per N seconds' gate (Nominatim allows 1 req/s)."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            delay = self._last + self.seconds - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


class _LRU:
    def __init__(self, size: int = 512) -> None:
        self.size = size
        self._data: OrderedDict[str, GeocodeResult | None] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> tuple[bool, GeocodeResult | None]:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                return True, self._data[key]
            return False, None

    def put(self, key: str, value: GeocodeResult | None) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self.size:
                self._data.popitem(last=False)


class OSMGeocoder:
    """Nominatim first, Photon as a fallback. Results are limited to Jordan and cached."""

    def __init__(
        self,
        user_agent: str,
        nominatim_url: str = "https://nominatim.openstreetmap.org",
        photon_url: str = "https://photon.komoot.io",
        timeout_s: float = 8.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.nominatim_url = nominatim_url.rstrip("/")
        self.photon_url = photon_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout_s, headers={"User-Agent": user_agent})
        self._gate = _MinInterval(1.0)
        self._cache = _LRU()

    def geocode(
        self,
        query: str,
        lang: str = "ar",
        feature_type: str | None = None,
        near: tuple[float, float] | None = None,
    ) -> GeocodeResult | None:
        """Look up a place in Jordan.

        feature_type="city" restricts results to towns/cities. `near` (lat, lng) prefers results
        around the user's area, so a common name such as "دوار الشعب" resolves to the local one.
        """
        query = (query or "").strip()
        if not query:
            return None
        near_key = f"{near[0]:.1f},{near[1]:.1f}" if near else "-"
        key = f"{lang}|{feature_type}|{near_key}|{normalize(query)}"
        hit, cached = self._cache.get(key)
        if hit:
            return cached
        best, answered = None, False
        for provider in (self._nominatim, self._photon):
            try:
                result = provider(query, lang, feature_type, near)
                answered = True
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
                logger.warning("%s failed for %r: %s", provider.__name__, query, exc)
                continue
            if result and result.exact:
                best = result
                break
            best = best or result  # a partial match: keep it, but let Photon try for a strong one
        if not answered:
            raise GeocoderUnavailable(query)  # not cached: the service may be back next time
        self._cache.put(key, best)
        return best

    def _nominatim(self, query: str, lang: str, feature_type: str | None = None, near=None) -> GeocodeResult | None:
        if near:  # boost (not restrict) results within ~40 km of the user's area
            south, west, north, east = near[0] - NEAR_DEG, near[1] - NEAR_DEG, near[0] + NEAR_DEG, near[1] + NEAR_DEG
        else:
            south, west, north, east = JORDAN_BBOX
        params = {
            "q": query,
            "format": "jsonv2",
            "limit": 5,
            "countrycodes": "jo",  # hard filter: Jordan only
            "accept-language": lang,
            "namedetails": 1,  # all the names (Arabic, English...) for the relevance check
            "viewbox": f"{west},{north},{east},{south}",
        }
        if feature_type:
            params["featureType"] = feature_type
        self._gate.wait()
        resp = self._client.get(f"{self.nominatim_url}/search", params=params)
        resp.raise_for_status()
        candidates = []
        for item in resp.json():
            lat, lng = float(item["lat"]), float(item["lon"])
            if not in_jordan(lat, lng):
                continue
            label = item.get("name") or item.get("display_name", query).split(",")[0]
            names = [label, *(item.get("namedetails") or {}).values()]
            score = 1.0 if feature_type else match_score(query, names, item.get("category", ""))
            candidates.append((score, GeocodeResult(lat, lng, label, "nominatim")))
        return _best(candidates)

    def _photon(self, query: str, lang: str, feature_type: str | None = None, near=None) -> GeocodeResult | None:
        south, west, north, east = JORDAN_BBOX
        params = {"q": query, "limit": 8, "bbox": f"{west},{south},{east},{north}"}
        if near:
            params["lat"], params["lon"] = near  # location bias
        if feature_type == "city":
            params["layer"] = "city"
        if lang == "en" or not contains_arabic(query):  # English names for English queries
            params["lang"] = "en"
        resp = self._client.get(f"{self.photon_url}/api/", params=params)
        resp.raise_for_status()
        candidates = []
        for feature in resp.json().get("features", []):
            props = feature.get("properties", {})
            # The bounding box also covers Palestine, Israel and parts of Syria: keep Jordan only.
            if str(props.get("countrycode", "")).upper() != "JO":
                continue
            lng, lat = feature["geometry"]["coordinates"][:2]
            if not in_jordan(lat, lng):
                continue
            name = props.get("name") or ""
            score = 1.0 if feature_type else match_score(query, [name], props.get("osm_key", ""))
            candidates.append((score, GeocodeResult(float(lat), float(lng), name or query, "photon")))
        return _best(candidates)
