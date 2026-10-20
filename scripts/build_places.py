"""Fill in missing coordinates in data/places.json from OpenStreetMap (run once, then commit the file).

Respects the Nominatim usage policy (https://operations.osmfoundation.org/policies/nominatim/):
one request per second, an identifying User-Agent, and each place is looked up once.

Quality checks:
* city names are searched with Nominatim's featureType=city (so "Irbid" can't match the Jordan River),
* a place tagged with "near": "<city id>" is rejected if it lands more than 30 km from that city,
* each place may list "alt_queries" that are tried in order until one passes.

Usage:
    python scripts/build_places.py                    # only places without coordinates
    python scripts/build_places.py --only irbid,kauh  # re-geocode specific places
    python scripts/build_places.py --force            # re-geocode everything
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jeenychatbot.config import get_settings, setup_logging  # noqa: E402
from jeenychatbot.geo import haversine_km  # noqa: E402
from jeenychatbot.geocoding import GeocoderUnavailable, OSMGeocoder  # noqa: E402

PLACES_FILE = ROOT / "data" / "places.json"
MAX_KM_FROM_CITY = 30.0


def _dump(data: dict) -> str:
    """Write one place per line so diffs stay readable."""
    lines = ["{", f'  "_meta": {json.dumps(data["_meta"], ensure_ascii=False)},', '  "landmarks": [']
    lines += [f"    {json.dumps(x, ensure_ascii=False)}," for x in data["landmarks"]]
    lines[-1] = lines[-1].rstrip(",")
    lines += ["  ],", '  "demo_saved_places": [']
    lines += [f"    {json.dumps(x, ensure_ascii=False)}," for x in data["demo_saved_places"]]
    lines[-1] = lines[-1].rstrip(",")
    lines += ["  ]", "}"]
    return "\n".join(lines) + "\n"


def _km_from_city(item: dict, by_id: dict, lat: float, lng: float) -> float | None:
    city = by_id.get(item.get("near", ""))
    if not city or city.get("lat") is None:
        return None
    return haversine_km(lat, lng, city["lat"], city["lng"])


def _geocode(geocoder: OSMGeocoder, item: dict, by_id: dict) -> tuple[dict | None, str]:
    """Try the main query and the alternatives; return (result, note)."""
    feature_type = "city" if item.get("kind") == "city" else None
    notes = []
    for query in [item["query"], *item.get("alt_queries", [])]:
        result = geocoder.geocode(query, "ar", feature_type)
        if result is None:
            notes.append(f"'{query}': not found")
            continue
        km = _km_from_city(item, by_id, result.lat, result.lng)
        if km is not None and km > MAX_KM_FROM_CITY:
            notes.append(f"'{query}': rejected, {km:.0f} km from {item['near']} ({result.label})")
            continue
        return {"lat": round(result.lat, 6), "lng": round(result.lng, 6), "provider": result.provider, "label": result.label}, ""
    return None, "; ".join(notes)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="re-geocode places that already have coordinates")
    parser.add_argument("--only", default="", help="comma-separated ids to re-geocode, e.g. irbid,kauh")
    args = parser.parse_args()
    only = {x.strip() for x in args.only.split(",") if x.strip()}

    setup_logging("WARNING")
    settings = get_settings()
    geocoder = OSMGeocoder(settings.user_agent, settings.nominatim_url, settings.photon_url, settings.http_timeout_s)
    data = json.loads(PLACES_FILE.read_text(encoding="utf-8"))
    by_id = {lm["id"]: lm for lm in data["landmarks"]}

    missing = []
    print(f"{'id':28s} {'lat':>10s} {'lng':>10s}  provider   OSM name")
    # Cities come first in the file, so their coordinates exist before the "near" checks need them.
    for item in data["landmarks"]:
        wanted = item["id"] in only if only else (args.force or item.get("lat") is None)
        if not wanted:
            continue
        try:
            found, note = _geocode(geocoder, item, by_id)
        except GeocoderUnavailable:
            sys.exit("OpenStreetMap geocoding is unreachable right now. Check your internet connection and try again.")
        if found is None:
            item["lat"], item["lng"] = None, None
            missing.append(item["id"])
            print(f"{item['id']:28s} {'-':>10s} {'-':>10s}  NOT FOUND  {note}")
            continue
        item["lat"], item["lng"] = found["lat"], found["lng"]
        print(f"{item['id']:28s} {item['lat']:>10.5f} {item['lng']:>10.5f}  {found['provider']:9s}  {found['label']}")

    for item in data["demo_saved_places"]:
        landmark = by_id.get(item.get("landmark", ""))
        if landmark and landmark.get("lat") is not None:
            item["lat"], item["lng"] = landmark["lat"], landmark["lng"]

    PLACES_FILE.write_text(_dump(data), encoding="utf-8")

    # Sanity report over the whole file, not only the places geocoded in this run.
    far = []
    for item in data["landmarks"]:
        if item.get("lat") is None:
            continue
        km = _km_from_city(item, by_id, item["lat"], item["lng"])
        if km is not None and km > MAX_KM_FROM_CITY:
            far.append(f"{item['id']} is {km:.0f} km from {item['near']}")

    total = len(data["landmarks"])
    with_coords = sum(1 for lm in data["landmarks"] if lm.get("lat") is not None)
    print(f"\nDone: {with_coords}/{total} landmarks have coordinates. Saved {PLACES_FILE.relative_to(ROOT)}")
    if missing:
        print("Not found (edit their 'query' / 'alt_queries' in data/places.json and run again):", ", ".join(missing))
    if far:
        print("Check these (far from their city):", "; ".join(far))


if __name__ == "__main__":
    main()
