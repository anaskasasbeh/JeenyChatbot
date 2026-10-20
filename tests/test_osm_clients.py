"""The OSM clients, tested against a mocked HTTP transport (no network)."""

import httpx
import pytest

from jeenychatbot.geocoding import GeocoderUnavailable, OSMGeocoder
from jeenychatbot.routing import OSRMRouter


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_nominatim_result_is_used_and_cached():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        return httpx.Response(200, json=[{"lat": "31.95", "lon": "35.91", "name": "عمان"}])

    geo = OSMGeocoder("test-agent", client=_client(handler))
    geo._gate.seconds = 0
    first = geo.geocode("عمان")
    second = geo.geocode("عمّان")  # same after normalization -> served from cache
    assert (first.lat, first.lng, first.provider) == (31.95, 35.91, "nominatim")
    assert second == first and calls == ["nominatim.openstreetmap.org"]


def test_photon_is_the_fallback():
    def handler(request: httpx.Request) -> httpx.Response:
        if "nominatim" in request.url.host:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={"features": [{"geometry": {"coordinates": [35.85, 32.55]}, "properties": {"name": "Irbid", "countrycode": "JO"}}]},
        )

    geo = OSMGeocoder("test-agent", client=_client(handler))
    geo._gate.seconds = 0
    result = geo.geocode("Irbid", "en")
    assert (result.lat, result.lng, result.provider) == (32.55, 35.85, "photon")


def test_results_outside_jordan_are_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        if "nominatim" in request.url.host:
            return httpx.Response(200, json=[{"lat": "48.85", "lon": "2.35"}])
        return httpx.Response(200, json={"features": []})

    geo = OSMGeocoder("test-agent", client=_client(handler))
    geo._gate.seconds = 0
    assert geo.geocode("Paris") is None


def test_osrm_route_is_parsed():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/route/v1/driving/35.85,32.55;35.91,31.95" in str(request.url)
        return httpx.Response(
            200,
            json={"code": "Ok", "routes": [{"distance": 85400, "duration": 4560,
                                            "geometry": {"coordinates": [[35.85, 32.55], [35.91, 31.95]]}}]},
        )

    route = OSRMRouter("https://osrm.test", "test-agent", client=_client(handler)).route((32.55, 35.85), (31.95, 35.91))
    assert (route.distance_km, route.duration_min, route.source) == (85.4, 76.0, "osrm")
    assert route.geometry == [(32.55, 35.85), (31.95, 35.91)]


def test_osrm_failure_falls_back_to_estimate():
    router = OSRMRouter("https://osrm.test", "test-agent", client=_client(lambda r: httpx.Response(502)))
    route = router.route((32.55, 35.85), (31.95, 35.91))
    assert route.source == "estimate" and route.distance_km > 60
    assert router.snap((32.55, 35.85)) == (32.55, 35.85)


def test_outage_is_reported_and_not_cached():
    state = {"up": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if not state["up"]:
            return httpx.Response(503)
        return httpx.Response(200, json=[{"lat": "32.55", "lon": "35.85"}])

    geo = OSMGeocoder("test-agent", client=_client(handler))
    geo._gate.seconds = 0
    with pytest.raises(GeocoderUnavailable):
        geo.geocode("Irbid")
    state["up"] = True
    assert geo.geocode("Irbid").lat == 32.55


def test_photon_results_outside_jordan_are_skipped():
    """Regression: "دوار الشعب" resolved to a place in Palestine because the box around Jordan covers it too."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "nominatim" in request.url.host:
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"features": [
            {"geometry": {"coordinates": [35.10, 31.53]}, "properties": {"name": "دوار الشعب", "countrycode": "PS"}},
            {"geometry": {"coordinates": [35.85, 32.54]}, "properties": {"name": "دوار الشعب", "countrycode": "JO"}},
        ]})

    geo = OSMGeocoder("test-agent", client=_client(handler))
    geo._gate.seconds = 0
    result = geo.geocode("دوار الشعب", near=(32.55, 35.85))
    assert (result.lat, result.lng) == (32.54, 35.85)


def test_near_point_biases_both_providers():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[request.url.host] = dict(request.url.params)
        if "nominatim" in request.url.host:
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"features": []})

    geo = OSMGeocoder("test-agent", client=_client(handler))
    geo._gate.seconds = 0
    assert geo.geocode("مكان", near=(32.55, 35.85)) is None
    nominatim = seen["nominatim.openstreetmap.org"]
    assert nominatim["countrycodes"] == "jo" and nominatim["viewbox"].startswith("35.5")
    assert seen["photon.komoot.io"]["lat"] == "32.55"


def test_long_routes_are_kept_and_downsampled():
    """Regression: Irbid -> Aqaba has thousands of points; it used to fall back to a straight line."""
    coords = [[35.85 - i * 0.0001, 32.55 - i * 0.0003] for i in range(9000)]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "Ok", "routes": [
            {"distance": 463500, "duration": 18000, "geometry": {"coordinates": coords}}]})

    route = OSRMRouter("https://osrm.test", "test-agent", client=_client(handler)).route((32.55, 35.85), (29.85, 34.95))
    assert route.source == "osrm" and route.distance_km == 463.5
    assert 2 <= len(route.geometry) <= 1500 and route.geometry[-1] == (round(coords[-1][1], 5), round(coords[-1][0], 5))


def test_second_routing_server_is_tried():
    hosts = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        if request.url.host == "first.test":
            return httpx.Response(504)
        return httpx.Response(200, json={"code": "Ok", "routes": [
            {"distance": 1000, "duration": 120, "geometry": {"coordinates": [[35.85, 32.55], [35.86, 32.56]]}}]})

    router = OSRMRouter("https://first.test,https://second.test/routed-car", "ua", client=_client(handler))
    assert router.route((32.55, 35.85), (32.56, 35.86)).source == "osrm"
    assert hosts == ["first.test", "second.test"]


def _geo(nominatim_items, photon_features=()):
    def handler(request: httpx.Request) -> httpx.Response:
        if "nominatim" in request.url.host:
            return httpx.Response(200, json=list(nominatim_items))
        return httpx.Response(200, json={"features": list(photon_features)})

    geo = OSMGeocoder("test-agent", client=_client(handler))
    geo._gate.seconds = 0
    return geo


def _photon(name, lat, lng, osm_key="amenity"):
    return {"geometry": {"coordinates": [lng, lat]}, "properties": {"name": name, "countrycode": "JO", "osm_key": osm_key}}


def test_a_street_sharing_one_word_is_only_a_partial_match():
    """Real case: "شركة مينا ديفز" was booked to "شارع مينا" as if it were certain."""
    street = {"lat": "31.97", "lon": "35.90", "name": "شارع مينا", "category": "highway", "namedetails": {"name": "شارع مينا"}}
    geo = _geo([street], [_photon("Mina Street", 31.97, 35.90, "highway")])
    partial = geo.geocode("شركة مينا ديفز بعمان")
    assert partial.label == "شارع مينا" and partial.exact is False  # used, but the user is asked to check
    english_street = _geo([], [_photon("Mina Street", 31.97, 35.90, "highway")])
    assert english_street.geocode("Mena Devs, Amman") is None  # same script, no word in common: rejected


def test_the_city_in_the_hint_is_not_the_answer():
    city = {"lat": "31.95", "lon": "35.91", "name": "عمان", "category": "boundary", "namedetails": {"name": "عمان", "name:en": "Amman"}}
    assert _geo([city]).geocode("Mena Devs, Amman") is None


def test_a_strong_match_further_down_the_list_wins():
    road = _photon("Abdali Boulevard", 31.96, 35.91, "highway")
    mall = _photon("Abdali Mall", 31.962, 35.908, "shop")
    result = _geo([], [road, mall]).geocode("Abdali Mall, Amman", "en")
    assert result.label == "Abdali Mall" and result.exact


def test_real_names_typos_and_spelling_variants_are_strong_matches():
    hospital = {"lat": "32.49", "lon": "35.99", "name": "مستشفى الملك المؤسس عبدالله الجامعي", "category": "amenity"}
    assert _geo([hospital]).geocode("مستشفى الملك عبدالله").exact
    assert _geo([hospital]).geocode("مستشفى الملك عبدالل").exact  # one letter missing
    roundabout = {"lat": "31.95", "lon": "35.86", "name": "الدوار السابع", "category": "highway"}
    assert _geo([roundabout]).geocode("الدوار السابع").exact
    street = {"lat": "31.97", "lon": "35.88", "name": "شارع مكة", "category": "highway"}
    assert _geo([street]).geocode("شارع مكة").exact
    assert _geo([], [_photon("Huwwara", 32.58, 35.88, "place")]).geocode("Hawwara, Irbid").exact


def test_dialect_words_and_other_scripts_are_partial_not_lost():
    beach = {"lat": "29.42", "lon": "34.97", "name": "الشاطئ الجنوبي", "category": "natural"}
    assert _geo([beach]).geocode("الشط الجنوبي بالعقبة").exact is False
    arabic_only = {"lat": "32.54", "lon": "35.85", "name": "جامعة اليرموك", "category": "amenity"}
    assert _geo([arabic_only]).geocode("Yarmouk University, Irbid").exact is False
