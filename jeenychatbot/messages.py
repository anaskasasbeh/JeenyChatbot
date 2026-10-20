"""All user-facing reply templates, in Arabic (Jordanian, friendly) and English."""

from __future__ import annotations

import re

from .models import CarType, Trip
from .pricing import CAR_OPTIONS
from .text import contains_arabic

_ERRORS = {
    "missing_place": ("ما فهمت اسم المكان، ممكن تكتبه مرة ثانية؟", "I didn't catch the place name. Could you type it again?"),
    "missing_end": ("لوين حابب تروح؟", "Where would you like to go?"),
    "missing_start": (
        "من وين بدك تنطلق؟ اكتب المكان، أو شارك موقعك من زر 📍.",
        "Where should I pick you up? Type a place, or share your location with the 📍 button.",
    ),
    "no_current_location": (
        "ما عندي موقعك الحالي. كبس زر 📍 عشان تشاركه، أو اكتب اسم المكان.",
        "I don't have your current location. Tap 📍 to share it, or type a place name.",
    ),
    "not_found": (
        "ما لقيت مكان اسمه «{place}» بالأردن. جرّب اسم أوضح أو أقرب مَعلم.",
        "I couldn't find “{place}” in Jordan. Try a clearer name or a nearby landmark.",
    ),
    "geo_unavailable": (
        "خدمة الخرائط مش متاحة هلأ، فما قدرت ألاقي «{place}». جرّب بعد شوي أو استخدم مكان من أماكنك المحفوظة.",
        "The map service is unavailable right now, so I couldn't look up “{place}”. "
        "Try again shortly, or use one of your saved places.",
    ),
    "not_found_pin": (
        "ما لقيت «{place}» على الخريطة. احكيلي شو قريب منه (شارع، دوار أو معلم)، أو إذا بتعرف مكانه حدّده بالزر تحت.",
        "I couldn't find “{place}” on the map. Tell me what's near it (a street, roundabout or landmark), or if you know where it is, pin it with the button below.",
    ),
    "not_saved": (
        "«{place}» مش محفوظ عندك لسا. احفظه من قائمة أماكني، أو اكتب اسم المنطقة.",
        "“{place}” isn't saved yet. Add it in My places, or type the area name.",
    ),
    "not_saved_pin": (
        "«{place}» مش محفوظ عندك لسا. حدّده على الخريطة بالزر تحت وبحفظه لك للمرات الجاية.",
        "“{place}” isn't saved yet. Pin it on the map with the button below and I'll save it for next time.",
    ),
    "outside_jordan": (
        "«{place}» برّا الأردن، والخدمة داخل الأردن بس.",
        "“{place}” is outside Jordan. The service only covers Jordan.",
    ),
    "same_place": (
        "نقطة الانطلاق والوجهة نفس المكان! اختار وجهة ثانية.",
        "Pickup and destination are the same place. Please choose another destination.",
    ),
    "no_trip": (
        "ما في رحلة حالية لأعدّل عليها. احكيلي من وين لوين أول.",
        "There's no current ride to change yet. Tell me where from and where to first.",
    ),
    "nothing_to_change": (
        "شو بدك تغيّر بالزبط؟ البداية ولا الوجهة؟",
        "What would you like to change, the pickup or the destination?",
    ),
    "internal": (
        "صار خطأ عندي، جرّب كمان مرة بعد شوي.",
        "Something went wrong on my side. Please try again in a moment.",
    ),
}

_HELP = (
    "أهلين! احكيلي لوين رايح ومن وين، وأنا بجهّزلك الرحلة.",
    "Hi! Tell me where you're going and where from, and I'll set up the ride.",
)

_THANKS = ("العفو! رحلة سعيدة 🚗", "You're welcome! Have a safe ride 🚗")


def _pick(pair: tuple[str, str], lang: str) -> str:
    return pair[1] if lang == "en" else pair[0]


def reply_language(message: str, ui_lang: str) -> str:
    """Reply in the language the user typed; fall back to the UI language."""
    if contains_arabic(message):
        return "ar"
    if len(re.findall(r"[A-Za-z]{2,}", message)) >= 2:
        return "en"
    return ui_lang


def error_message(code: str, lang: str, **details: str) -> str:
    template = _pick(_ERRORS.get(code, _ERRORS["internal"]), lang)
    return template.format(**details) if details else template.replace("{place}", "")


def help_message(lang: str) -> str:
    return _pick(_HELP, lang)


def thanks_message(lang: str) -> str:
    return _pick(_THANKS, lang)


def ar_minutes(n: int) -> str:
    """Arabic counting rules: 1 دقيقة, 2 دقيقتين, 3-10 دقائق, 11+ دقيقة."""
    if n == 1:
        return "دقيقة وحدة"
    if n == 2:
        return "دقيقتين"
    if 3 <= n <= 10:
        return f"{n} دقائق"
    return f"{n} دقيقة"


def _car(car: CarType, lang: str) -> str:
    return CAR_OPTIONS[car].label(lang)


def _price(trip: Trip, lang: str) -> str:
    return f"{trip.price:.2f} JOD" if lang == "en" else f"{trip.price:.2f} د.أ"


def _estimate_note(trip: Trip, lang: str) -> str:
    if trip.route.source != "estimate":
        return ""
    if lang == "en":
        return "\n(Distance is estimated: the routing service is unavailable right now.)"
    return "\n(المسافة تقديرية لأنه خدمة الطرق مش متاحة هلأ.)"


# The trip panel in the UI shows the route and the fare of every car. Replies stay short and
# natural, and mention the price only once the user has chosen and confirmed (it changes with the car).

def trip_ready(trip: Trip, lang: str) -> str:
    minutes = round(trip.route.duration_min)
    special = trip.car_type != "economy"  # only mention the car when the user picked one
    if lang == "en":
        car = f" {_car(trip.car_type, lang)}" if special else ""
        text = (
            f"Your{car} ride from {trip.start.name} to {trip.end.name} is ready "
            f"({trip.route.distance_km:.0f} km, about {minutes} min). Pick a car and confirm when you're ready."
        )
    else:
        car = f" {_car(trip.car_type, lang)}" if special else ""
        text = (
            f"تمام، جهّزتلك رحلة{car} من {trip.start.name} إلى {trip.end.name} "
            f"({trip.route.distance_km:.0f} كم، تقريباً {ar_minutes(minutes)}). اختار السيارة وأكّد الطلب لما تكون جاهز."
        )
    return text + _estimate_note(trip, lang)


def car_changed(trip: Trip, old: CarType, was_confirmed: bool, lang: str) -> str:
    if old == trip.car_type:
        return f"It's already {_car(old, lang)}." if lang == "en" else f"الرحلة أصلاً {_car(old, lang)}."
    if lang == "en":
        return f"Switched to {_car(trip.car_type, lang)}." + (" Please confirm the updated ride." if was_confirmed else "")
    return f"تمام، صارت {_car(trip.car_type, lang)}." + (" أكّد الطلب الجديد لو سمحت." if was_confirmed else "")


def trip_modified(old: Trip, new: Trip, was_confirmed: bool, lang: str) -> str:
    changes = []
    if (old.start.lat, old.start.lng) != (new.start.lat, new.start.lng):
        changes.append(f"pickup is now {new.start.name}" if lang == "en" else f"الانطلاق صار من {new.start.name}")
    if (old.end.lat, old.end.lng) != (new.end.lat, new.end.lng):
        changes.append(f"destination is now {new.end.name}" if lang == "en" else f"الوجهة صارت {new.end.name}")
    if not changes:
        return "Nothing changed." if lang == "en" else "ما تغيّر إشي على الرحلة."
    if lang == "en":
        text = f"Done, {' and '.join(changes)} ({new.route.distance_km:.0f} km)."
        text += " Please confirm the updated ride." if was_confirmed else ""
    else:
        text = f"تمام، {' و'.join(changes)} ({new.route.distance_km:.0f} كم)."
        text += " أكّد الطلب الجديد لو سمحت." if was_confirmed else ""
    return text + _estimate_note(new, lang)


def trip_confirmed(trip: Trip, lang: str) -> str:
    d = trip.driver
    if d is None:
        return error_message("internal", lang)
    car = _car(trip.car_type, lang)
    if lang == "en":
        return (
            f"Your {car} ride is confirmed for {_price(trip, lang)}. "
            f"{d.name_en or d.name} ({d.car_model}) will pick you up in {d.eta_min} min."
        )
    return f"تم تأكيد رحلتك ({car}) بـ {_price(trip, lang)}. {d.name} ({d.car_model}) بوصلك خلال {ar_minutes(d.eta_min)}."


def placed_near(place: str, nearby: str, lang: str) -> str:
    if lang == "en":
        return f"📍 I put “{place}” at “{nearby}”. If you know the exact spot, adjust it on the map."
    return f"📍 حطيت «{place}» عند «{nearby}». إذا بتعرف مكانه بالضبط عدّله على الخريطة."


def check_place(name: str, lang: str) -> str:
    """Added when the map found a place that only partly matches the user's words."""
    if lang == "en":
        return f"📍 Please check on the map that “{name}” is the place you mean."
    return f"📍 اتأكد إن «{name}» هو المكان اللي بدك إياه على الخريطة."


def already_confirmed(lang: str) -> str:
    return "Your ride is already confirmed and the driver is on the way." if lang == "en" else "رحلتك مؤكدة، والسائق بالطريق."


def trip_cancelled(lang: str) -> str:
    return "Your ride is cancelled. Tell me where you'd like to go next." if lang == "en" else "تم إلغاء الرحلة. احكيلي إذا بدك رحلة ثانية."


def pickup_updated(trip: Trip, was_confirmed: bool, lang: str) -> str:
    if lang == "en":
        text = f"Pickup set to your current location ({trip.route.distance_km:.0f} km to {trip.end.name})."
        return text + (" Please confirm the ride again." if was_confirmed else "")
    text = f"صارت نقطة الانطلاق موقعك الحالي (المسافة إلى {trip.end.name}: {trip.route.distance_km:.0f} كم)."
    return text + (" أكّد الرحلة من جديد." if was_confirmed else "")
