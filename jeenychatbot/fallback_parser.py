"""Rule-based understanding of ride requests: the offline fallback when no LLM is available.

It covers the common patterns ("من إربد لعمان", "غير الوجهة للسلط", "خليها VIP",
"from Irbid to Amman"). It is less flexible than the LLM, but it keeps the demo
working when free LLM quotas run out, and it is the baseline in the evaluation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .models import CarType
from .text import strip_particles

IntentAction = Literal["new_trip", "change_car", "modify_trip", "confirm", "cancel", "help", "thanks"]


@dataclass(frozen=True)
class ParsedIntent:
    action: IntentAction
    start: str | None = None
    end: str | None = None
    car_type: CarType | None = None


# ----------------------------------------------------------------- normalizing
_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟـ]")
_PUNCT = re.compile(r"[؟?!.,،:;\"'«»()\[\]]")


def _light_normalize(text: str) -> str:
    """Fold hamza forms and remove diacritics/punctuation, but keep ة/ى so names stay readable."""
    text = _DIACRITICS.sub("", text or "")
    text = re.sub("[أإآٱ]", "ا", text)
    text = _PUNCT.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


# ------------------------------------------------------------------ car types
_CAR_PATTERNS: list[tuple[CarType, str]] = [
    ("vip", r"\bvip\b|في اي بي|فاخر[ةه]?|فخم[ةه]?|درج[ةه] اولى|luxury|premium"),
    ("family", r"عائلي[ةه]?|عايلي[ةه]?|كبير[ةه]|7 ركاب|سبع[ةه]? ركاب|\bفان\b|باص صغير|family|\bvan\b|7[- ]?seat"),
    ("taxi", r"تاكسي|تكسي|اجر[ةه]|taxi|\bcab\b"),
    ("economy", r"عادي[ةه]?|طبيعي[ةه]|economy|regular|normal|standard"),
]

# Words that describe the car, removed before extracting place names.
_CAR_PHRASES = re.compile(
    r"(?:ب|بال)?(?:سيار[ةه]|سياره|car|ride)?\s*(?:نوع(?:ها)?\s*)?"
    r"(?:\bvip\b|في اي بي|فاخر[ةه]?|فخم[ةه]?|عائلي[ةه]?|عايلي[ةه]?|تاكسي|تكسي|عادي[ةه]?|family|taxi|economy)"
)


def detect_car_type(text: str) -> CarType | None:
    norm = _light_normalize(text)
    for car, pattern in _CAR_PATTERNS:
        if re.search(pattern, norm):
            return car
    return None


# ----------------------------------------------------------------- vocabulary
_THANKS = re.compile(r"^(?:شكرا|مشكور|يعطيك العافي[ةه]|تسلم|thanks|thank you|thx)\b")
_CONFIRM = re.compile(
    r"^(?:(?:تمام|اوكي|ok|okay|yes|yeah|اه|ايوا|نعم|يلا)\s*[,،]?\s*)*"
    r"(?:اكد|اكّد|اكدها|تاكيد|ثبت|اطلب|اطلبها|اطلبلي ياها|احجز|احجزها|confirm|book it|book|go ahead)\b"
    r"|^(?:تمام|اوكي|ok|okay|yes|يلا)\s*$"
)
_CANCEL = re.compile(r"\b(?:الغي|الغيها|الغاء|كنسل|بطلت|cancel)\b")
_CHANGE_VERB = re.compile(
    r"\b(?:غير|غيّر|غيري|بدل|بدّل|عدل|عدّل|اعدل|اغير|ابدل|خلي|خليها|خليه|حول|صير|خليني|change|switch|update|make)\b"
)
_DEST_WORDS = r"(?:الوجه[ةه]|النهاي[ةه]|المكان اللي رايح|مكان الوصول|destination|drop ?off|dropoff)"
_START_WORDS = r"(?:البداي[ةه]|نقط[ةه] الانطلاق|الانطلاق|مكاني|مكان الانطلاق|pickup|pick up|start)"
_GO_VERBS = (
    r"(?:اروح|نروح|روح|روحني|وصلني|وصّلني|خذني|اخذني|ودّيني|وديني|رايح|رايحه|رايحين|انزل|اطلع|طلعني|"
    r"take me|go|drive me|ride)"
)
_TO_WORDS = {"الى", "الي", "على", "علي", "ع", "عـ", "ل", "لـ", "لعند", "to"}

_FILLERS = re.compile(
    r"(?:يا حلو|يا غالي|يا باشا|يا معلم|لو سمحت|من فضلك|الله يخليك|يعطيك العافي[ةه]|بسرع[ةه]|هلا|هلأ|هسا|هسه|"
    r"الحين|please|plz|now|asap|thanks|شكرا)\s*$"
)
_LEADING = re.compile(
    r"^(?:(?:مساء الخير|صباح الخير|مرحبا|مرحبتين|هلا|اهلين|السلام عليكم|hi|hello|hey)\s*)?"
    r"(?:(?:بدي|بدنا|ممكن|حاب|اريد|i want|i need|can you|please)\s*)?"
)


def _clean_place(text: str) -> str:
    text = _CAR_PHRASES.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for _ in range(3):
        text = _FILLERS.sub("", text).strip()
    return strip_particles_keep(text)


def strip_particles_keep(text: str) -> str:
    """Remove leading prepositions but keep the original spelling of the name."""
    words = text.split()
    while len(words) > 1 and words[0] in _TO_WORDS | {"من", "from", "the"}:
        words = words[1:]
    if not words:
        return ""
    first = words[0]
    if first.startswith("عال") and len(first) > 4:
        words[0] = "ال" + first[3:]
    elif first.startswith("لل") and len(first) > 4:
        words[0] = "ال" + first[2:]
    elif first.startswith("ل") and len(first) > 3 and len(strip_particles(first)) > 2:
        # glued "ل": "لعمان" -> "عمان", but keep names that really start with "ال"
        if not first.startswith("ال"):
            words[0] = first[1:]
    elif first.startswith("عا") and len(first) > 4:
        words[0] = first[1:]
    return " ".join(words).strip()


def _is_to_marker(word: str) -> bool:
    if word in _TO_WORDS:
        return True
    return (word.startswith("لل") or word.startswith("عال")) and len(word) > 4


def _split_from_to(tokens: list[str]) -> tuple[str | None, str | None]:
    """Find "من X (الى|ل|على) Y" (or "from X to Y") and return (X, Y)."""
    for from_word in ("من", "from"):
        if from_word not in tokens:
            continue
        i = tokens.index(from_word)
        left, right = tokens[:i], tokens[i + 1 :]
        for j in range(1, len(right)):
            word = right[j]
            glued_l = word.startswith("ل") and not word.startswith("ال") and len(word) > 3
            if _is_to_marker(word) or (glued_l and from_word == "من"):
                start = " ".join(right[:j])
                end = " ".join(right[j:]) if not word in _TO_WORDS else " ".join(right[j + 1 :])
                return _clean_place(start) or None, _clean_place(end) or None
        # No "to" after the start: maybe the destination came first ("بدي اروح عالمطار من الدار").
        start = _clean_place(" ".join(right)) or None
        end = _destination_after_verb(" ".join(left))
        return start, end
    return None, None


def _destination_after_verb(text: str) -> str | None:
    match = re.search(rf"{_GO_VERBS}\s+(?P<place>.+)$", text)
    if not match:
        match = re.search(r"\bto\s+(?P<place>.+)$", text)
    if not match:
        return None
    return _clean_place(match.group("place")) or None


# --------------------------------------------------------------------- parse
# "قريب من مجمع عمان", "هو جنب الجامعة", "موجود بالعبدلي مول", "next to the 7th circle"
_NEARBY = re.compile(
    r"^(?:(?:اسمع|طيب|يا\s+زلمه|يا\s+زلمة|هو|هي|المكان|موجود|موجوده|موجودة|بتلاقيه|بتلاقيها)\s+)*"
    r"(?:(?:قريب(?:\s+(?:من|على|ع))?|جنب|بجانب|عند|حد|مقابل|قبال|ورا|داخل|جوا|في|"
    r"near|next\s+to|close\s+to|inside|by|at|in)\s+|ب(?=ال))(?P<place>\S.*)$",
    flags=re.IGNORECASE,
)


def parse_nearby(message: str) -> str | None:
    """The place in an answer to "what's near it?", or None if the message isn't one."""
    match = _NEARBY.match(_light_normalize(message))
    return _clean_place(match.group("place")) or None if match else None


def parse(message: str, has_trip: bool) -> ParsedIntent:
    """Best-effort intent + slots from one message."""
    text = _light_normalize(message)
    car = detect_car_type(text)

    if _THANKS.search(text):
        return ParsedIntent("thanks")
    if has_trip and _CANCEL.search(text):
        return ParsedIntent("cancel")

    body = _LEADING.sub("", text).strip()
    tokens = body.split()
    is_change = bool(_CHANGE_VERB.search(body)) or "بدل" in body

    # English "to X from Y"
    en = re.search(r"\bto (?P<end>.+?) from (?P<start>.+)$", body)
    if en:
        start, end = _clean_place(en.group("start")), _clean_place(en.group("end"))
    else:
        start, end = _split_from_to(tokens)
    if not start:
        pick_en = re.search(r"\bpick me up (?:from|at) (?P<start>.+)$", body)
        if pick_en:
            start = _clean_place(pick_en.group("start")) or None

    if has_trip and not (start or end) and _CONFIRM.search(text):
        return ParsedIntent("confirm")

    if has_trip and is_change:
        dest = re.search(rf"{_DEST_WORDS}\s+(?P<place>.+)$", body)
        pick = re.search(rf"{_START_WORDS}\s+(?P<place>.+)$", body)
        if start or end:
            return ParsedIntent("modify_trip", start=start, end=end)
        if dest:
            return ParsedIntent("modify_trip", end=_clean_place(dest.group("place")) or None)
        if pick:
            return ParsedIntent("modify_trip", start=_clean_place(pick.group("place")) or None)
        if car:
            return ParsedIntent("change_car", car_type=car)

    if has_trip and start and not end:
        # Only a new pickup while a ride exists ("بدي تاخذني من موقعي"): keep the destination.
        return ParsedIntent("modify_trip", start=start)

    if start or end:
        return ParsedIntent("new_trip", start=start, end=end, car_type=car)

    end = _destination_after_verb(body)
    if end:
        return ParsedIntent("new_trip", end=end, car_type=car)

    if has_trip and car:
        return ParsedIntent("change_car", car_type=car)
    return ParsedIntent("help")
