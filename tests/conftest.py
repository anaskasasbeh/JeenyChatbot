"""Shared test fixtures. Everything is offline: no LLM, no map services."""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jeenychatbot.geocoding import GeocodeResult  # noqa: E402
from jeenychatbot.models import RouteInfo  # noqa: E402
from jeenychatbot.routing import estimate_route  # noqa: E402
from jeenychatbot.text import normalize  # noqa: E402
from jeenychatbot.trips import TripPlanner  # noqa: E402

# Rough test-only coordinates (fixtures, not shipped data).
FAKE_GAZETTEER = {
    "irbid": (32.556, 35.850),
    "اربد": (32.556, 35.850),
    "amman": (31.952, 35.911),
    "عمان": (31.952, 35.911),
    "salt": (32.039, 35.727),
    "السلط": (32.039, 35.727),
    "zarqa": (32.072, 36.088),
    "الزرقاء": (32.072, 36.088),
    "ajloun": (32.333, 35.752),
    "عجلون": (32.333, 35.752),
    "queen alia": (31.722, 35.993),
    "yarmouk university": (32.536, 35.856),
    "university of jordan": (32.016, 35.872),
    "abdali": (31.962, 35.910),
    "al-balad": (31.952, 35.934),
    "tabarbour": (32.010, 35.940),
    "king hussein business park": (31.981, 35.860),
    "aydoun": (32.509, 35.857),
    "الدوار السابع": (31.954, 35.857),
    "دوار الشعب": (32.540, 35.850),
    "south beach, aqaba": (29.400, 34.980),
    "paris": (48.857, 2.352),
}


class FakeGeocoder:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.near: list = []

    def geocode(self, query: str, lang: str = "ar", feature_type=None, near=None) -> GeocodeResult | None:
        self.calls.append(query)
        self.near.append(near)
        q = normalize(query)
        for key, (lat, lng) in FAKE_GAZETTEER.items():
            if normalize(key) in q:
                return GeocodeResult(lat, lng, query, "fake")
        return None


class FakeRouter:
    def __init__(self, source: str = "osrm") -> None:
        self.source = source
        self.calls = 0

    def route(self, start, end) -> RouteInfo:
        self.calls += 1
        est = estimate_route(start, end)
        return est.model_copy(update={"source": self.source})

    def snap(self, point):
        return point


class FakeToolModel(GenericFakeChatModel):
    """A chat model that replays scripted AIMessages (optionally with tool calls)."""

    calls: int = 0
    fail: bool = False

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ANN003
        return self

    def _generate(self, *args, **kwargs):  # noqa: ANN002, ANN003
        object.__setattr__(self, "calls", self.calls + 1)
        if self.fail:
            raise RuntimeError("simulated provider outage")
        return super()._generate(*args, **kwargs)


def tool_call(name: str, **args) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{name}"}])


def scripted_model(*replies: AIMessage, fail: bool = False) -> FakeToolModel:
    return FakeToolModel(messages=iter(list(replies)), fail=fail)


@pytest.fixture
def geocoder() -> FakeGeocoder:
    return FakeGeocoder()


@pytest.fixture
def router() -> FakeRouter:
    return FakeRouter()


@pytest.fixture
def planner(geocoder, router) -> TripPlanner:
    return TripPlanner(geocoder, router, rng=random.Random(7))
