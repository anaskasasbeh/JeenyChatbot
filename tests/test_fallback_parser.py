import pytest

from jeenychatbot.fallback_parser import detect_car_type, parse


@pytest.mark.parametrize(
    "text, has_trip, expected",
    [
        ("بدي أروح من إربد إلى عمان", False, ("new_trip", "اربد", "عمان", None)),
        ("من اربد لعمان", False, ("new_trip", "اربد", "عمان", None)),
        ("كم تكلفة الرحلة من الجامعة الأردنية إلى المطار؟", False, ("new_trip", "الجامعة الاردنية", "المطار", None)),
        ("بدي سيارة VIP من وسط البلد إلى العبدلي", False, ("new_trip", "وسط البلد", "العبدلي", "vip")),
        ("بدي تاكسي من الصويفية لتاج مول لو سمحت", False, ("new_trip", "الصويفية", "تاج مول", "taxi")),
        ("مساء الخير بدي انطلق من الدار الى الجامعة", False, ("new_trip", "الدار", "الجامعة", None)),
        ("خذني عالدار", False, ("new_trip", None, "الدار", None)),
        ("بدي اروح عالمطار من الدار", False, ("new_trip", "الدار", "المطار", None)),
        ("from Irbid to Amman", False, ("new_trip", "irbid", "amman", None)),
        ("take me to the airport", False, ("new_trip", None, "airport", None)),
        ("غير الوجهة للسلط", True, ("modify_trip", None, "السلط", None)),
        ("غير البداية لعجلون", True, ("modify_trip", "عجلون", None, None)),
        ("بدي أعدل الرحلة لتصير من الزرقاء إلى السلط", True, ("modify_trip", "الزرقاء", "السلط", None)),
        ("change destination to Salt", True, ("modify_trip", None, "salt", None)),
        ("غير نوع السيارة لـ VIP", True, ("change_car", None, None, "vip")),
        ("خليها عائلية", True, ("change_car", None, None, "family")),
        ("make it VIP", True, ("change_car", None, None, "vip")),
        ("شكرا", True, ("thanks", None, None, None)),
        ("مرحبا", False, ("help", None, None, None)),
    ],
)
def test_parse(text, has_trip, expected):
    intent = parse(text, has_trip)
    assert (intent.action, intent.start, intent.end, intent.car_type) == expected


@pytest.mark.parametrize(
    "text, car",
    [("بدي سيارة فخمة", "vip"), ("سيارة 7 ركاب", "family"), ("تكسي", "taxi"), ("a regular car", "economy"), ("بدي سيارة", None)],
)
def test_detect_car_type(text, car):
    assert detect_car_type(text) == car


def test_answers_to_whats_near_it():
    from jeenychatbot.fallback_parser import parse_nearby

    assert parse_nearby("اسمع قريب مجمع عمان") == "مجمع عمان"
    assert parse_nearby("موجوده بالعبدلي مول") == "العبدلي مول"
    assert parse_nearby("next to the 7th circle") == "7th circle"
    assert parse_nearby("بدي اروح على العقبة") is None  # a new request, not an answer
