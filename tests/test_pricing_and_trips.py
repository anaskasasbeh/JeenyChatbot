import pytest

from jeenychatbot.models import LatLng, RouteInfo
from jeenychatbot.places import build_place_book
from jeenychatbot.pricing import CAR_OPTIONS, all_fares, fare
from jeenychatbot.trips import PlanningError


def test_fare_formula():
    route = RouteInfo(distance_km=10, duration_min=20, geometry=[], source="osrm")
    # 0.50 + 10*0.25 + 20*0.05 = 4.00
    assert fare(route, "economy") == 4.00
    assert fare(route, "taxi") == 4.60
    assert fare(route, "family") == 5.20
    assert fare(route, "vip") == 6.00
    assert set(all_fares(route)) == set(CAR_OPTIONS)


def test_plan_trip_is_a_draft_until_confirmed(planner):
    trip = planner.plan_trip("اربد", "عمان", "vip", build_place_book())
    assert trip.start.name == "إربد" and trip.end.name == "عمان"
    assert trip.car_type == "vip"
    assert trip.price == trip.quotes["vip"] > trip.quotes["economy"]
    assert trip.status == "draft" and trip.driver is None
    booked = planner.confirm(trip)
    assert booked.status == "confirmed" and booked.driver.eta_min >= 1


def test_any_change_turns_a_confirmed_trip_back_into_a_draft(planner):
    booked = planner.confirm(planner.plan_trip("اربد", "عمان", "economy", build_place_book()))
    assert planner.change_car_type(booked, "vip").status == "draft"
    assert planner.modify_trip(booked, None, "السلط", build_place_book()).driver is None


def test_filler_words_are_removed_before_searching(planner, geocoder):
    trip = planner.plan_trip("اربد", "اللي عند دوار الشعب", "economy", build_place_book())
    assert geocoder.calls[-1] == "دوار الشعب" and trip.end.name == "دوار الشعب"


def test_destination_search_is_biased_near_the_pickup(planner, geocoder):
    trip = planner.plan_trip("اربد", "دوار الشعب", "economy", build_place_book())
    assert geocoder.near[-1] == (trip.start.lat, trip.start.lng)


def test_pickup_defaults_to_current_location(planner):
    here = LatLng(lat=32.55, lng=35.85)
    trip = planner.plan_trip(None, "عمان", "economy", build_place_book(), current_location=here)
    assert trip.start.source == "current_location"


@pytest.mark.parametrize(
    "start, end, code",
    [
        (None, "عمان", "missing_start"),
        ("اربد", None, "missing_end"),
        ("اربد", "اربد", "same_place"),
        ("اربد", "مكان مش موجود", "not_found"),
        ("اربد", "paris", "outside_jordan"),
        ("موقعي", "عمان", "no_current_location"),
    ],
)
def test_planning_errors(planner, start, end, code):
    with pytest.raises(PlanningError) as err:
        planner.plan_trip(start, end, "economy", build_place_book())
    assert err.value.code == code


def test_change_car_type_keeps_route(planner):
    trip = planner.plan_trip("اربد", "عمان", "economy", build_place_book())
    changed = planner.change_car_type(trip, "family")
    assert changed.route == trip.route
    assert changed.price == trip.quotes["family"]


def test_modify_destination_keeps_car_type(planner):
    trip = planner.plan_trip("اربد", "عمان", "taxi", build_place_book())
    changed = planner.modify_trip(trip, None, "السلط", build_place_book())
    assert changed.start == trip.start
    assert changed.end.name == "السلط"
    assert changed.car_type == "taxi"


def test_landmark_without_coordinates_is_geocoded_by_query(planner, geocoder):
    from jeenychatbot.places import Landmark, PlaceBook

    airport = Landmark(id="qaia", kind="airport", name_ar="المطار", name_en="Airport", query="Queen Alia airport")
    trip = planner.plan_trip("Irbid", "المطار", "economy", PlaceBook(landmarks=[airport]))
    assert "Queen Alia airport" in geocoder.calls
    assert trip.end.name == "المطار" and trip.end.source == "landmark"


def test_map_outage_has_its_own_message(planner, geocoder):
    from jeenychatbot.geocoding import GeocoderUnavailable

    def down(query, lang="ar", feature_type=None, near=None):
        raise GeocoderUnavailable(query)

    geocoder.geocode = down
    with pytest.raises(PlanningError) as err:
        planner.plan_trip("اربد", "مكان جديد", "economy", build_place_book())
    assert err.value.code == "geo_unavailable"
