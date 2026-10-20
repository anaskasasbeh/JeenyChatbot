"""Measure how well the assistant understands ride requests (data/eval_set.jsonl).

Only the "understanding" step is measured: which action was chosen and which
pickup / destination / car type were extracted. Maps are replaced by offline
fakes, so the score does not depend on OpenStreetMap being up.

Usage:
    python scripts/evaluate.py --mode rules                 # rule-based parser (offline)
    python scripts/evaluate.py --mode ai                    # primary LLM from .env
    python scripts/evaluate.py --mode ai --model fallback   # fallback LLM from .env

Results are printed as a Markdown table and saved to eval_results/.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jeenychatbot.actions import TurnContext  # noqa: E402
from jeenychatbot.agent import run_agent  # noqa: E402
from jeenychatbot.config import get_settings, setup_logging  # noqa: E402
from jeenychatbot.geocoding import GeocodeResult  # noqa: E402
from jeenychatbot.llm import _make  # noqa: E402
from jeenychatbot.messages import reply_language  # noqa: E402
from jeenychatbot.models import ChatTurn, LatLng, Place, SavedPlace  # noqa: E402
from jeenychatbot.places import build_place_book  # noqa: E402
from jeenychatbot.routing import estimate_route  # noqa: E402
from jeenychatbot.service import ChatService  # noqa: E402
from jeenychatbot.text import clean_place_text, is_current_location_phrase, strip_particles  # noqa: E402
from jeenychatbot.trips import TripPlanner  # noqa: E402

EVAL_FILE = ROOT / "data" / "eval_set.jsonl"
OUT_DIR = ROOT / "eval_results"
TOOL_TO_ACTION = {
    "request_trip": "new_trip",
    "change_car_type": "change_car",
    "modify_trip": "modify_trip",
    "confirm_trip": "confirm",
    "cancel_trip": "cancel",
    "place_near": "modify_trip",
}


# --------------------------------------------------------------- offline maps
class AnywhereGeocoder:
    """Returns a distinct point inside Jordan for any name, so planning never blocks scoring."""

    def geocode(self, query: str, lang: str = "ar", feature_type=None, near=None) -> GeocodeResult:
        offset = (sum(map(ord, query)) % 200) / 1000
        return GeocodeResult(31.9 + offset, 35.9 + offset, query, "eval")


class StraightLineRouter:
    def route(self, start, end):
        return estimate_route(start, end)

    def snap(self, point):
        return point


DEMO_SAVED = [
    SavedPlace(name="الدار", aliases=["البيت", "داري", "بيتي", "home"], lat=32.50, lng=35.86),
    SavedPlace(name="الشغل", aliases=["الدوام", "الشركة", "work", "the office"], lat=31.98, lng=35.86),
    SavedPlace(name="الجامعة", aliases=["الكلية", "uni", "university"], lat=32.54, lng=35.86),
]


def _current_trip(planner: TripPlanner):
    start = Place(name="إربد", lat=32.556, lng=35.85, source="landmark")
    end = Place(name="عمان", lat=31.952, lng=35.911, source="landmark")
    return planner._build(start, end, "economy")


# -------------------------------------------------------------------- scoring
def same_place(pred: str | None, expected: str | None, book, has_location: bool) -> bool:
    p, e = (pred or "").strip(), (expected or "").strip()
    if not p and not e:
        return True
    if (not p or is_current_location_phrase(p)) and (not e or is_current_location_phrase(e)):
        return True  # no pickup == "my location": the app uses (or asks the browser for) the user's location
    if not p or not e:
        return False
    if strip_particles(clean_place_text(p)) == strip_particles(clean_place_text(e)):
        return True
    mp, me = book.lookup(clean_place_text(p)), book.lookup(clean_place_text(e))
    return bool(mp and me and (mp.name, mp.source) == (me.name, me.source))


def score(item: dict, pred: dict, book) -> dict:
    exp = item["expected"]
    action_ok = pred["action"] == exp["action"]
    places_ok = car_ok = None
    if exp["action"] in {"new_trip", "modify_trip"}:
        has_loc = bool(item.get("has_location"))
        # A place counts as understood if either the words or the AI's official-name hint point to it.
        pickup_ok = same_place(pred["pickup"], exp["pickup"], book, has_loc) or (
            bool(pred.get("pickup_hint")) and same_place(pred["pickup_hint"], exp["pickup"], book, has_loc))
        dest_ok = same_place(pred["destination"], exp["destination"], book, has_loc) or (
            bool(pred.get("destination_hint")) and same_place(pred["destination_hint"], exp["destination"], book, has_loc))
        places_ok = action_ok and pickup_ok and dest_ok
    if exp["action"] in {"new_trip", "change_car"}:
        want = exp["car_type"]
        got = pred["car_type"]
        car_ok = action_ok and (got in (None, "economy") if want is None else got == want)
    exact = action_ok and places_ok is not False and car_ok is not False
    return {"action_ok": action_ok, "places_ok": places_ok, "car_ok": car_ok, "exact": exact}


# ----------------------------------------------------------------------- run
def predict(item: dict, mode: str, models, planner: TripPlanner, retries: int = 3) -> dict:
    ctx = TurnContext(
        planner=planner,
        book=build_place_book(DEMO_SAVED),
        lang=reply_language(item["text"], "ar"),
        trip=_current_trip(planner) if item.get("has_trip") else None,
        current_location=LatLng(lat=32.55, lng=35.85) if item.get("has_location") else None,
    )
    calls, error = 0, None
    started = time.perf_counter()
    if mode == "rules":
        ChatService.answer_with_rules(ctx, item["text"])
    else:
        for attempt in range(retries + 1):
            try:
                history = [ChatTurn(**turn) for turn in item.get("history", [])]
                calls = run_agent(models, ctx, item["text"], history).model_calls
                error = None
                break
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"[:200]
                if "rate" in error.lower() or "429" in error:
                    wait = 20 * (attempt + 1)
                    print(f"   rate-limited, waiting {wait}s ...", flush=True)
                    time.sleep(wait)
                    ctx.tool_calls.clear()
                    continue
                break
    latency = time.perf_counter() - started
    first = ctx.tool_calls[0] if ctx.tool_calls else {}
    return {
        "action": TOOL_TO_ACTION.get(first.get("name"), "message"),
        "pickup": first.get("pickup"),
        "destination": first.get("destination"),
        "car_type": first.get("car_type"),
        "pickup_hint": first.get("pickup_hint"),
        "destination_hint": first.get("destination_hint"),
        "latency_s": round(latency, 3),
        "model_calls": calls,
        "error": error,
    }


def pct(values: list[bool]) -> str:
    values = [v for v in values if v is not None]
    return f"{100 * sum(values) / len(values):.1f}% ({sum(values)}/{len(values)})" if values else "n/a"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["rules", "ai"], default="rules")
    parser.add_argument("--model", choices=["primary", "fallback"], default="primary")
    parser.add_argument("--delay", type=float, default=8.0, help="seconds between LLM calls (free-tier limits)")
    args = parser.parse_args()

    setup_logging("WARNING")
    settings = get_settings()
    models, label = [], "rule-based parser"
    if args.mode == "ai":
        llm = settings.primary_llm if args.model == "primary" else settings.fallback_llm
        if not llm.enabled:
            sys.exit(f"No API key for the {args.model} model. Fill it in .env first.")
        models, label = [_make(llm, settings.llm_timeout_s)], llm.model

    planner = TripPlanner(AnywhereGeocoder(), StraightLineRouter())
    items = [json.loads(line) for line in EVAL_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    book = build_place_book(DEMO_SAVED)
    rows = []
    print(f"Evaluating {label} on {len(items)} messages ...")
    for i, item in enumerate(items, 1):
        pred = predict(item, args.mode, models, planner)
        result = {**item, "predicted": pred, **score(item, pred, book)}
        rows.append(result)
        mark = "✓" if result["exact"] else "✗"
        hint = f" [{pred['destination_hint']}]" if pred.get("destination_hint") else ""
        print(f"{mark} {i:>2}. {item['text'][:55]:55s} -> {pred['action']} {pred['pickup']!r} {pred['destination']!r}{hint} {pred['car_type']}")
        if args.mode == "ai" and i < len(items):
            time.sleep(args.delay)

    latencies = [r["predicted"]["latency_s"] for r in rows]
    summary = {
        "brain": label,
        "messages": len(rows),
        "action_accuracy": pct([r["action_ok"] for r in rows]),
        "place_accuracy": pct([r["places_ok"] for r in rows]),
        "car_type_accuracy": pct([r["car_ok"] for r in rows]),
        "exact_match": pct([r["exact"] for r in rows]),
        "latency_p50_s": round(statistics.median(latencies), 3),
        "latency_p95_s": round(sorted(latencies)[max(0, int(0.95 * len(latencies)) - 1)], 3),
        "avg_model_calls_per_turn": round(statistics.mean(r["predicted"]["model_calls"] for r in rows), 2),
        "errors": sum(1 for r in rows if r["predicted"]["error"]),
    }

    OUT_DIR.mkdir(exist_ok=True)
    tag = "rules" if args.mode == "rules" else args.model
    (OUT_DIR / f"summary_{tag}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (OUT_DIR / f"details_{tag}.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print("\n| Metric | Value |\n|---|---|")
    for key, value in summary.items():
        print(f"| {key} | {value} |")
    failures = [r for r in rows if not r["exact"]]
    if failures:
        print("\nMisses:")
        for r in failures:
            p = r["predicted"]
            print(f"  #{r['id']} {r['text']} | expected {r['expected']} | got {p['action']} {p['pickup']!r} {p['destination']!r} {p['car_type']} {p['error'] or ''}")


if __name__ == "__main__":
    main()
