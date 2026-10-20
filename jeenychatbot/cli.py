"""Terminal chat: `python -m jeenychatbot` (add `--lang en` or `--rules`)."""

from __future__ import annotations

import argparse
import logging

from .config import get_settings, setup_logging
from .models import ChatRequest, ChatTurn, SavedPlace, Trip
from .places import load_demo_saved_places
from .pricing import CAR_OPTIONS
from .service import ChatService

EXIT_WORDS = {"exit", "quit", "خروج", "انهاء", "انهي", "باي"}


def _demo_saved_places() -> list[SavedPlace]:
    return [
        SavedPlace(name=p["name"], aliases=p["aliases"], lat=p["lat"], lng=p["lng"])
        for p in load_demo_saved_places()
        if p["lat"] is not None and p["lng"] is not None
    ]


def _summary(trip: Trip, lang: str) -> str:
    car = CAR_OPTIONS[trip.car_type].label(lang)
    fares = "  ".join(f"{CAR_OPTIONS[c].label(lang)}={p:.2f}" for c, p in trip.quotes.items())
    return f"   [{trip.start.name} -> {trip.end.name} | {car} | {trip.route.source}]  {fares}"


def main() -> None:
    parser = argparse.ArgumentParser(description="JeenyChatbot - ride assistant in the terminal")
    parser.add_argument("--lang", choices=["ar", "en"], default="ar", help="default reply language")
    parser.add_argument("--rules", action="store_true", help="ignore LLM keys and use the rule-based parser")
    parser.add_argument("--verbose", action="store_true", help="show debug logs")
    args = parser.parse_args()

    settings = get_settings()
    setup_logging("DEBUG" if args.verbose else "WARNING")
    service = ChatService.from_settings(settings)
    if args.rules:
        service.models = []
    logging.getLogger(__name__).debug("AI enabled: %s", service.ai_enabled)

    saved = _demo_saved_places()
    history: list[ChatTurn] = []
    trip: Trip | None = None
    mode = "AI" if service.ai_enabled else "rule-based"
    print(f"JeenyChatbot ({mode} mode). Type 'exit' to quit.")
    if saved:
        print("Saved places:", ", ".join(p.name for p in saved))

    while True:
        try:
            message = input("\nأنت / You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not message:
            continue
        if message.lower() in EXIT_WORDS:
            break
        req = ChatRequest(message=message[:300], lang=args.lang, history=history[-12:], trip=trip, saved_places=saved)
        resp = service.handle(req)
        print(f"🤖 {resp.reply}")
        if resp.trip and resp.action in {"new_trip", "car_changed", "trip_modified"}:
            print(_summary(resp.trip, args.lang))
        trip = resp.trip
        history += [ChatTurn(role="user", content=message), ChatTurn(role="assistant", content=resp.reply[:2000])]


if __name__ == "__main__":
    main()
