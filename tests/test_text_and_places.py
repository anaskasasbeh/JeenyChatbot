import pytest

from jeenychatbot.models import SavedPlace
from jeenychatbot.places import build_place_book, load_landmarks
from jeenychatbot.text import is_current_location_phrase, name_variants, normalize, parse_coordinates, strip_particles


def test_normalize_folds_arabic_variants():
    assert normalize("الجامعة الأردنية") == normalize("الجامعه الاردنيه")
    assert normalize("إربد") == "اربد"
    assert normalize("  مكّة   مول ") == "مكه مول"


@pytest.mark.parametrize(
    "text, expected",
    [("عالدار", "الدار"), ("للجامعة", "الجامعه"), ("على اربد", "اربد"), ("to Amman", "amman")],
)
def test_strip_particles(text, expected):
    assert strip_particles(text) == expected


def test_name_variants_include_glued_preposition():
    assert "عمان" in name_variants("لعمان")
    assert "اربد" in name_variants("عاربد")


def test_parse_coordinates():
    assert parse_coordinates("32.55, 35.85") == (32.55, 35.85)
    assert parse_coordinates("٣٢.٥, ٣٥.٨") == (32.5, 35.8)
    assert parse_coordinates("Irbid") is None


def test_current_location_phrases():
    assert is_current_location_phrase("موقعي")
    assert is_current_location_phrase("My location")
    assert not is_current_location_phrase("الدار")


def test_landmark_aliases_do_not_collide():
    owner: dict[str, str] = {}
    for lm in load_landmarks():
        for name in (lm.name_ar, lm.name_en, *lm.aliases):
            for key in name_variants(name):
                assert owner.setdefault(key, lm.id) == lm.id, f"{key!r} used by {owner[key]} and {lm.id}"


@pytest.fixture
def book():
    saved = [SavedPlace(name="الجامعة", aliases=["uni"], lat=32.53, lng=35.85)]
    return build_place_book(saved)


@pytest.mark.parametrize(
    "query, expected_name, source",
    [
        # A substring matcher would send these three to the wrong place.
        ("الجامعة الأردنية", "الجامعة الأردنية", "landmark"),
        ("تاج مول", "تاج مول", "landmark"),
        ("مكة مول", "مكة مول", "landmark"),
        # Saved places win and accept prepositions.
        ("الجامعة", "الجامعة", "saved"),
        ("عالجامعة", "الجامعة", "saved"),
        ("uni", "الجامعة", "saved"),
        # Spelling variants and a typo.
        ("الجامعه الاردنيه", "الجامعة الأردنية", "landmark"),
        ("جامعة اليرموكك", "جامعة اليرموك", "landmark"),
        ("the airport", "مطار الملكة علياء الدولي", "landmark"),
    ],
)
def test_lookup(book, query, expected_name, source):
    match = book.lookup(query)
    assert match is not None
    assert (match.name, match.source) == (expected_name, source)


def test_lookup_english_names(book):
    assert book.lookup("Irbid", lang="en").name == "Irbid"


@pytest.mark.parametrize("query", ["الدوار", "مكان غريب جدا", "الدار"])
def test_unknown_places_go_to_geocoder(book, query):
    assert book.lookup(query) is None


def test_personal_places():
    from jeenychatbot.text import is_personal_place

    for text in ["الدار", "عالدار", "للبيت", "بيتي", "الشغل", "Home", "my work"]:
        assert is_personal_place(text), text
    for text in ["دار الأوبرا", "مول العرب", "اربد", "home center"]:
        assert not is_personal_place(text), text


def test_role_words_are_not_part_of_the_place():
    from jeenychatbot.text import clean_place_text

    assert clean_place_text("الوجهة الزرقاء") == "الزرقاء"  # eval #26
    assert clean_place_text("نقطة الانطلاق الجامعة الأردنية") == "الجامعة الأردنية"
    assert clean_place_text("وجهتي هي العقبة") == "العقبة"
