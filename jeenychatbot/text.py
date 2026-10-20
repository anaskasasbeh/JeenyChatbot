"""Arabic/English text helpers used to match place names reliably.

Users type the same place many ways ("الجامعة الأردنية", "الجامعه الاردنيه", "عالجامعة").
`normalize` folds those spellings together; `name_variants` also removes leading
particles such as "عال" / "لل" / "على" so "عالدار" can match the saved place "الدار".
"""

from __future__ import annotations

import re

_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")  # tashkeel + tatweel
_PUNCT = re.compile(r"[^\w\s,.\-]", flags=re.UNICODE)
_SPACES = re.compile(r"\s+")
_ARABIC_CHARS = re.compile(r"[؀-ۿ]")
_COORDS = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*[,،]\s*(-?\d{1,3}(?:\.\d+)?)\s*$")

_CHAR_MAP = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ة": "ه",
        "ؤ": "و",
        "ئ": "ي",
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
        "،": ",",
        "ـ": "",
    }
)

# Leading words that are not part of a place name ("to", "on", "from").
_LEADING_WORDS = {"على", "علي", "الى", "الي", "ل", "لـ", "عـ", "ع", "من", "to", "from", "the"}

_CURRENT_LOCATION_PHRASES = {
    "موقعي",
    "من موقعي",
    "موقعي هلا",
    "مكاني هلا",
    "موقعي الحالي",
    "مكاني",
    "مكاني الحالي",
    "هون",
    "من هون",
    "هنا",
    "انا هون",
    "my location",
    "current location",
    "my current location",
    "here",
}


def contains_arabic(text: str) -> bool:
    return bool(_ARABIC_CHARS.search(text or ""))


def normalize(text: str) -> str:
    """Fold Arabic letter variants, digits, case, punctuation and spacing."""
    text = (text or "").translate(_CHAR_MAP)
    text = _DIACRITICS.sub("", text).lower()
    text = _PUNCT.sub(" ", text)
    return _SPACES.sub(" ", text).strip(" ,.-")


def strip_particles(text: str) -> str:
    """Remove leading prepositions: "عالدار" -> "الدار", "للجامعة" -> "الجامعه", "على اربد" -> "اربد"."""
    words = normalize(text).split()
    while len(words) > 1 and words[0] in _LEADING_WORDS:
        words = words[1:]
    if not words:
        return ""
    first = words[0]
    if first.startswith("عال") and len(first) > 4:
        first = "ال" + first[3:]
    elif first.startswith("لل") and len(first) > 4:
        first = "ال" + first[2:]
    words[0] = first
    return " ".join(words)


def name_variants(text: str) -> list[str]:
    """Normalized forms to try for an exact lookup, most specific first."""
    variants: list[str] = []
    for form in (normalize(text), strip_particles(text)):
        if form and form not in variants:
            variants.append(form)
        # Also try without a leading "ال" ("اليرموك" -> "يرموك").
        if form.startswith("ال") and len(form) > 4:
            bare = form[2:]
            if bare not in variants:
                variants.append(bare)
        # A preposition glued to a name: "لعمان" -> "عمان", "عاربد" -> "اربد".
        glued = ""
        if len(form) > 3 and form[0] == "ل" and form[1] != "ل":
            glued = form[1:]
        elif len(form) > 4 and form.startswith("عا"):
            glued = form[1:]
        if glued and glued not in variants:
            variants.append(glued)
    return variants


def parse_coordinates(text: str) -> tuple[float, float] | None:
    """Parse "32.55, 35.85" into (lat, lng). Returns None if the text is not a coordinate pair."""
    match = _COORDS.match((text or "").translate(_CHAR_MAP))
    if not match:
        return None
    lat, lng = float(match.group(1)), float(match.group(2))
    if -90 <= lat <= 90 and -180 <= lng <= 180:
        return lat, lng
    return None


# Filler around a place name: "اللي عند دوار الشعب" -> "دوار الشعب", "near the 7th circle" -> "the 7th circle".
_FILLER_PREFIX = re.compile(
    r"^(?:(?:اللي|الي|يلي)\s+)?(?:عند|جنب|حد|قريب\s+من|قريب\s+على|بجانب|بالقرب\s+من|مقابل|قبال|ورا|near|next\s+to|close\s+to|by)\s+",
    flags=re.IGNORECASE,
)
# Words that name the role, not the place: "الوجهة الزرقاء" -> "الزرقاء".
_ROLE_PREFIX = re.compile(
    r"^(?:الوجهة|الوجهه|وجهتي|نقطة\s+الانطلاق|نقطه\s+الانطلاق|مكان\s+الانطلاق|the\s+destination|destination|pickup)"
    r"(?:\s+(?:هي|صارت|لـ?|على|ع|to|is))?\s+",
    flags=re.IGNORECASE,
)
_FILLER_SUFFIX = re.compile(r"\s+(?:بالاردن|بالأردن|في\s+الاردن|في\s+الأردن|in\s+jordan)$", flags=re.IGNORECASE)


def clean_place_text(text: str) -> str:
    """Remove words that describe *where* a place is but are not part of its name."""
    text = re.sub(r"\s+", " ", (text or "").strip(" \t\n.,،؟?!"))
    for _ in range(2):
        text = _ROLE_PREFIX.sub("", text).strip()
        text = _FILLER_PREFIX.sub("", text).strip()
        text = _FILLER_SUFFIX.sub("", text).strip()
    return text


def is_current_location_phrase(text: str) -> bool:
    return normalize(text) in {normalize(p) for p in _CURRENT_LOCATION_PHRASES}


# Personal places only the user knows. If one isn't saved, it must never be searched on the
# map: a shop called "الدار" somewhere in Jordan is not the user's home.
_PERSONAL_PLACES = {
    "الدار", "دار", "داري", "دارنا", "البيت", "بيت", "بيتي", "بيتنا",
    "الشغل", "شغلي", "الدوام", "دوامي", "المكتب", "مكتبي",
    "جامعتي", "مدرستي",
    "home", "my home", "my house", "work", "my work", "the office", "my office",
}
_PERSONAL_KEYS = {normalize(p) for p in _PERSONAL_PLACES}


def is_personal_place(text: str) -> bool:
    """"الدار", "عالبيت", "my work": places that only the user's saved places can answer."""
    return normalize(text) in _PERSONAL_KEYS or strip_particles(text) in _PERSONAL_KEYS
