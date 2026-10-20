from conftest import scripted_model, tool_call
from langchain_core.messages import AIMessage

from jeenychatbot.models import ChatRequest, LatLng, SavedPlace, TripActionRequest
from jeenychatbot.service import ChatService

HERE = LatLng(lat=32.50, lng=35.86)  # a shared "my location" near Irbid (test fixture)


def test_one_model_call_per_trip_request(planner):
    model = scripted_model(tool_call("request_trip", destination="عمان", pickup="اربد", car_type="vip"))
    resp = ChatService(planner, [model]).handle(ChatRequest(message="بدي VIP من اربد لعمان"))
    assert resp.mode == "ai" and resp.action == "new_trip"
    assert resp.trip.car_type == "vip" and resp.trip.status == "draft"
    assert model.calls == 1  # the tool reply ends the turn (return_direct)


def test_plain_answer_without_tool(planner):
    model = scripted_model(AIMessage(content="أهلين! لوين حابب تروح؟"))
    resp = ChatService(planner, [model]).handle(ChatRequest(message="مرحبا"))
    assert resp.action == "message" and "لوين" in resp.reply


def test_fallback_model_takes_over(planner):
    primary = scripted_model(fail=True)
    backup = scripted_model(tool_call("request_trip", destination="عمان", pickup="اربد"))
    resp = ChatService(planner, [primary, backup]).handle(ChatRequest(message="من اربد لعمان"))
    assert resp.mode == "ai" and resp.action == "new_trip"
    assert primary.calls == 1 and backup.calls == 1


def test_all_models_down_uses_rules(planner):
    resp = ChatService(planner, [scripted_model(fail=True)]).handle(ChatRequest(message="من اربد لعمان"))
    assert resp.mode == "rules" and resp.action == "new_trip"


def test_no_keys_uses_rules(planner):
    resp = ChatService(planner, []).handle(ChatRequest(message="from Irbid to Amman"))
    assert resp.mode == "rules" and resp.reply.startswith("Your ride from Irbid to Amman")


def test_default_car_is_not_named_in_the_reply(planner):
    """Feedback: "جهّزتلك رحلة عادية" sounded odd; the default car is not mentioned."""
    resp = ChatService(planner, []).handle(ChatRequest(message="بدي أروح من إربد لعمان"))
    assert "عادية" not in resp.reply and resp.reply.startswith("تمام، جهّزتلك رحلة من إربد إلى عمان")


def test_modified_destination_is_kept_for_next_turn(planner):
    """Regression: the old sync_trip_data() restored the previous destination after a modification."""
    svc = ChatService(planner, [])
    first = svc.handle(ChatRequest(message="من اربد لعمان"))
    second = svc.handle(ChatRequest(message="غير الوجهة للسلط", trip=first.trip))
    third = svc.handle(ChatRequest(message="خليها VIP", trip=second.trip))
    assert second.trip.end.name == "السلط"
    assert third.trip.end.name == "السلط" and third.trip.car_type == "vip"


def test_new_pickup_keeps_the_destination(planner):
    """Feedback: after "بدي تاخذني من موقعي" the bot asked for the destination again."""
    svc = ChatService(planner, [])
    trip = svc.handle(ChatRequest(message="من اربد للمطار")).trip
    resp = svc.handle(ChatRequest(message="بدي تاخذني من موقعي", trip=trip, current_location=HERE))
    assert resp.action == "trip_modified"
    assert resp.trip.start.source == "current_location" and resp.trip.end.name == trip.end.name


def test_llm_request_without_destination_is_treated_as_a_pickup_change(planner):
    model = scripted_model(tool_call("request_trip", destination="", pickup="موقعي"))
    trip = ChatService(planner, []).handle(ChatRequest(message="من اربد لعمان")).trip
    resp = ChatService(planner, [model]).handle(ChatRequest(message="من موقعي", trip=trip, current_location=HERE))
    assert resp.action == "trip_modified" and resp.trip.end.name == "عمان"


def test_destination_only_keeps_the_known_pickup(planner):
    svc = ChatService(planner, [])
    trip = svc.handle(ChatRequest(message="من اربد لعمان")).trip
    resp = svc.handle(ChatRequest(message="خذني على السلط", trip=trip))
    assert resp.trip.start.name == "إربد" and resp.trip.end.name == "السلط"


def test_nickname_is_understood_through_the_llm_hint_not_a_hand_made_list(planner):
    """Feedback: "البزنس بارك" must work without adding it to any file.

    The LLM passes the official name it knows; the planner searches with it.
    """
    from jeenychatbot.places import build_place_book

    assert build_place_book().lookup("البزنس بارك") is None  # not in any list
    trip = ChatService(planner, []).handle(ChatRequest(message="من اربد لعمان")).trip
    model = scripted_model(tool_call(
        "modify_trip", new_destination="البزنس بارك", new_destination_full_name="King Hussein Business Park, Amman"
    ))
    resp = ChatService(planner, [model]).handle(ChatRequest(message="بدي اغير الوجهة للبزنس بارك", trip=trip))
    assert resp.action == "trip_modified" and resp.trip.end.name == "مجمع الملك حسين للأعمال"


def test_unknown_place_found_by_its_official_name(planner, geocoder):
    model = scripted_model(tool_call(
        "request_trip", destination="الشط الجنوبي", pickup="اربد", destination_full_name="South Beach, Aqaba"
    ))
    resp = ChatService(planner, [model]).handle(ChatRequest(message="بدي اروح من اربد للشط الجنوبي"))
    assert resp.action == "new_trip" and geocoder.calls[-2:] == ["الشط الجنوبي", "South Beach, Aqaba"]


def test_place_missing_from_the_map_can_be_pinned(planner):
    """Feedback: "اربد سيتي سنتر" isn't in OpenStreetMap; the user can pin it, like Jeeny's "Set on Map"."""
    svc = ChatService(planner, [])
    trip = svc.handle(ChatRequest(message="من اربد لعمان")).trip
    resp = svc.handle(ChatRequest(message="غير الوجهة لمول النجمة", trip=trip))
    assert resp.action == "message" and resp.pin.role == "destination" and resp.pin.label == "مول النجمة"
    pinned = svc.trip_action(TripActionRequest(trip=trip, action="pin", pin=resp.pin, point=LatLng(lat=32.54, lng=35.86)))
    assert pinned.action == "trip_modified"
    assert pinned.trip.end.name == "مول النجمة" and pinned.trip.end.source == "pinned"


def test_pin_without_a_trip_uses_the_resolved_pickup(planner):
    svc = ChatService(planner, [])
    resp = svc.handle(ChatRequest(message="من اربد لمول ما حدا بيعرفه"))
    assert resp.pin.role == "destination" and resp.pin.start.name == "إربد"
    pinned = svc.trip_action(TripActionRequest(action="pin", pin=resp.pin, point=LatLng(lat=32.54, lng=35.86)))
    assert pinned.action == "new_trip" and pinned.trip.start.name == "إربد"


def test_price_is_only_mentioned_on_confirmation(planner):
    """Feedback: the price changes with the car, so it is said only when the ride is confirmed."""
    svc = ChatService(planner, [])
    draft = svc.handle(ChatRequest(message="من اربد لعمان"))
    assert "د.أ" not in draft.reply
    vip = svc.handle(ChatRequest(message="خليها VIP", trip=draft.trip))
    assert "د.أ" not in vip.reply
    booked = svc.handle(ChatRequest(message="أكد", trip=vip.trip))
    assert f"{vip.trip.quotes['vip']:.2f} د.أ" in booked.reply and "VIP" in booked.reply


def test_confirm_and_cancel_by_chat(planner):
    svc = ChatService(planner, [])
    trip = svc.handle(ChatRequest(message="من اربد لعمان")).trip
    booked = svc.handle(ChatRequest(message="تمام اطلبها", trip=trip))
    assert booked.action == "trip_confirmed" and booked.trip.driver is not None
    assert booked.reply.startswith("تم تأكيد رحلتك")
    again = svc.handle(ChatRequest(message="أكد", trip=booked.trip))
    assert again.trip.status == "confirmed" and "مؤكدة" in again.reply
    cancelled = svc.handle(ChatRequest(message="الغي الرحلة", trip=booked.trip))
    assert cancelled.action == "trip_cancelled" and cancelled.trip is None


def test_confirm_tool_from_the_llm(planner):
    trip = ChatService(planner, []).handle(ChatRequest(message="من اربد لعمان")).trip
    model = scripted_model(tool_call("confirm_trip"))
    resp = ChatService(planner, [model]).handle(ChatRequest(message="yes, book it", trip=trip))
    assert resp.action == "trip_confirmed" and resp.trip.status == "confirmed"


def test_change_without_trip_asks_for_one(planner):
    model = scripted_model(tool_call("change_car_type", car_type="vip"))
    resp = ChatService(planner, [model]).handle(ChatRequest(message="خليها VIP"))
    assert resp.action == "message" and resp.trip is None


def test_trip_panel_buttons_need_no_llm(planner):
    svc = ChatService(planner, [])
    trip = svc.handle(ChatRequest(message="من اربد لعمان")).trip

    car = svc.trip_action(TripActionRequest(trip=trip, action="car", car_type="family", lang="en"))
    assert car.action == "car_changed" and car.trip.price == trip.quotes["family"]

    here = svc.trip_action(TripActionRequest(trip=car.trip, action="pickup_here", current_location=HERE))
    assert here.trip.start.source == "current_location" and here.trip.end.name == "عمان"
    assert here.trip.car_type == "family"

    booked = svc.trip_action(TripActionRequest(trip=here.trip, action="confirm"))
    assert booked.trip.status == "confirmed" and booked.trip.driver is not None

    cancelled = svc.trip_action(TripActionRequest(trip=booked.trip, action="cancel"))
    assert cancelled.action == "trip_cancelled" and cancelled.trip is None


def test_reply_follows_message_language(planner):
    svc = ChatService(planner, [])
    assert svc.handle(ChatRequest(message="from Irbid to Amman", lang="ar")).reply.startswith("Your ride")
    assert svc.handle(ChatRequest(message="من اربد لعمان", lang="en")).reply.startswith("تمام")


def test_unsaved_home_is_never_searched_on_the_map(planner, geocoder):
    """Feedback: "خذني على الدار" with no saved home. A shop called "الدار" is not the user's home."""
    resp = ChatService(planner, []).handle(ChatRequest(message="خذني على الدار", current_location=HERE))
    assert resp.action == "message" and resp.trip is None
    assert resp.pin.label == "الدار" and resp.pin.role == "destination" and resp.pin.save is True
    assert "مش محفوظ" in resp.reply
    assert not any("الدار" in call for call in geocoder.calls)


def test_saved_home_is_used(planner):
    home = SavedPlace(name="الدار", lat=32.51, lng=35.856)
    resp = ChatService(planner, []).handle(
        ChatRequest(message="خذني على الدار", current_location=HERE, saved_places=[home])
    )
    assert resp.action == "new_trip" and resp.trip.end.source == "saved"
    assert resp.trip.start.source == "current_location"  # shared location = pickup


def test_pinned_home_comes_back_as_a_trip(planner):
    svc = ChatService(planner, [])
    resp = svc.handle(ChatRequest(message="خذني على الدار", current_location=HERE))
    pinned = svc.trip_action(
        TripActionRequest(action="pin", pin=resp.pin, point=LatLng(lat=32.51, lng=35.856), current_location=HERE)
    )
    assert pinned.action == "new_trip" and pinned.trip.end.name == "الدار"
    assert pinned.trip.start.source == "current_location"


def test_location_button_on_a_confirmed_ride_asks_to_confirm_again(planner):
    svc = ChatService(planner, [])
    trip = svc.handle(ChatRequest(message="من اربد لعمان")).trip
    booked = svc.trip_action(TripActionRequest(trip=trip, action="confirm")).trip
    moved = svc.trip_action(TripActionRequest(trip=booked, action="pickup_here", current_location=HERE))
    assert moved.trip.status == "draft" and moved.trip.start.source == "current_location"
    assert "أكّد الرحلة من جديد" in moved.reply and moved.trip.end.name == "عمان"


def test_new_destination_keeps_the_typed_pickup_even_with_location_shared(planner):
    svc = ChatService(planner, [])
    trip = svc.handle(ChatRequest(message="من اربد لعمان", current_location=HERE)).trip
    resp = svc.handle(ChatRequest(message="خذني على السلط", trip=trip, current_location=HERE))
    assert resp.trip.start.name == "إربد" and resp.trip.end.name == "السلط"


def test_prompt_carries_the_real_jordan_time(planner):
    """The model invented "10:30" when asked the time; now it gets the real time in the prompt."""
    from datetime import datetime

    from jeenychatbot.actions import TurnContext
    from jeenychatbot.agent import JORDAN_TZ, _system_prompt
    from jeenychatbot.places import build_place_book

    prompt = _system_prompt(TurnContext(planner, build_place_book(), "ar"))
    assert f"{datetime.now(JORDAN_TZ):%Y-%m-%d}" in prompt and "UTC+3" in prompt


class _PartialGeocoder:
    """The map found something that only partly matches ("شركة مينا ديفز" -> "شارع مينا")."""

    def geocode(self, query, lang="ar", feature_type=None, near=None):
        from jeenychatbot.geocoding import GeocodeResult

        return GeocodeResult(31.97, 35.90, "شارع مينا", "fake", exact=False)


def test_a_partial_match_is_booked_but_the_user_is_asked_to_check_it():
    """Feedback: a typo or a different word must not end in "not found"; ask the user to check instead."""
    from conftest import FakeRouter
    from jeenychatbot.trips import TripPlanner

    svc = ChatService(TripPlanner(_PartialGeocoder(), FakeRouter()), [])
    resp = svc.handle(ChatRequest(message="بدي اروح على شركة مينا ديفز", current_location=HERE))
    assert resp.action == "new_trip" and resp.trip.end.name == "شارع مينا"
    assert "اتأكد إن «شارع مينا»" in resp.reply and "د.أ" not in resp.reply
    assert resp.pin.adjust and resp.pin.role == "destination" and resp.pin.label == "شركة مينا ديفز"

    car = svc.trip_action(TripActionRequest(trip=resp.trip, action="car", car_type="vip"))
    assert "اتأكد" not in car.reply  # asked once, not on every change

    fixed = svc.trip_action(TripActionRequest(trip=resp.trip, action="pin", pin=resp.pin, point=LatLng(lat=31.96, lng=35.91)))
    assert fixed.trip.end.name == "شركة مينا ديفز" and fixed.trip.end.asked_as is None


def test_answering_whats_near_it_places_the_missing_place_there(planner):
    """Video: "ما لقيت «اربد سيتي سنتر»..." -> "قريب مجمع عمان" got a generic reply. A driver would just go there."""
    svc = ChatService(planner, [])
    trip = svc.handle(ChatRequest(message="من اربد لعمان")).trip
    missing = svc.handle(ChatRequest(message="غير الوجهة لمول النجمة", trip=trip))
    resp = svc.handle(ChatRequest(message="اسمع هو قريب من دوار الشعب", trip=trip, pending_pin=missing.pin))
    assert resp.action == "trip_modified" and resp.trip.end.name == "مول النجمة"
    assert (resp.trip.end.lat, resp.trip.end.lng) == (32.540, 35.850)  # the roundabout's spot
    assert "حطيت «مول النجمة» عند «دوار الشعب»" in resp.reply
    assert resp.pin.adjust and resp.pin.label == "مول النجمة"


def test_place_near_tool_from_the_llm(planner):
    svc = ChatService(planner, [])
    missing = svc.handle(ChatRequest(message="من اربد لمول ما حدا بيعرفه"))
    model = scripted_model(tool_call("place_near", nearby="دوار الشعب"))
    resp = ChatService(planner, [model]).handle(ChatRequest(message="جنب دوار الشعب", pending_pin=missing.pin))
    assert resp.mode == "ai" and resp.action == "new_trip"
    assert resp.trip.start.name == "إربد" and resp.trip.end.name == "مول ما حدا بيعرفه"


def test_a_namesake_in_another_city_is_skipped(planner):
    """Video: "Irbid City Center, Irbid" came back as a "City Center" 97 km away."""
    from conftest import FakeRouter
    from jeenychatbot.geocoding import GeocodeResult
    from jeenychatbot.trips import TripPlanner

    class FarAway:
        def geocode(self, query, lang="ar", feature_type=None, near=None):
            return GeocodeResult(31.95, 35.91, "City Center", "fake") if "City" in query else None

    model = scripted_model(tool_call(
        "request_trip", destination="اربد سيتي سنتر", pickup="اربد", destination_full_name="Irbid City Center, Irbid"
    ))
    resp = ChatService(TripPlanner(FarAway(), FakeRouter()), [model]).handle(ChatRequest(message="بدي اروح على اربد سيتي سنتر"))
    assert resp.trip is None and resp.pin.label == "اربد سيتي سنتر"


def test_empty_model_answer_falls_back_to_rules_for_that_turn(planner):
    model = scripted_model(AIMessage(content=""))
    resp = ChatService(planner, [model]).handle(ChatRequest(message="من اربد لعمان"))
    assert resp.mode == "ai" and resp.action == "new_trip"


def test_missing_location_asks_the_app_to_get_it(planner):
    """Screenshot: "من موقعي" three times, and the bot kept saying "press 📍". Now the app asks the browser itself."""
    svc = ChatService(planner, [])
    for message in ["بدي اروح على جامعة اليرموك", "من موقعي لعمان"]:
        resp = svc.handle(ChatRequest(message=message))
        assert resp.trip is None and resp.need_location, message
    with_location = svc.handle(ChatRequest(message="بدي اروح على جامعة اليرموك", current_location=HERE))
    assert with_location.action == "new_trip" and not with_location.need_location
    assert with_location.trip.start.source == "current_location"
    assert not svc.handle(ChatRequest(message="من اربد لمول ما حدا بيعرفه")).need_location  # a different problem


def test_place_near_without_a_missing_place_is_a_destination_change(planner):
    """Eval #50: the model called place_near when nothing was missing; the provider rejected a tool it wasn't given."""
    from jeenychatbot.agent import build_tools
    from jeenychatbot.actions import TurnContext
    from jeenychatbot.places import build_place_book

    assert "place_near" in {t.name for t in build_tools(TurnContext(planner, build_place_book(), "ar"))}
    trip = ChatService(planner, []).handle(ChatRequest(message="من اربد لعمان")).trip
    model = scripted_model(tool_call("place_near", nearby="دوار الشعب"))
    resp = ChatService(planner, [model]).handle(ChatRequest(message="اللي عند دوار الشعب", trip=trip))
    assert resp.action == "trip_modified" and resp.trip.end.name == "دوار الشعب" and resp.trip.start.name == "إربد"
