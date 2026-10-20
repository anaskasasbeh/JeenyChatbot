import pytest
from fastapi.testclient import TestClient

from jeenychatbot.api import app, button_limit, get_service, rate_limit
from jeenychatbot.service import ChatService


@pytest.fixture
def client(planner):
    app.dependency_overrides[get_service] = lambda: ChatService(planner, [])
    rate_limit._hits.clear()
    button_limit._hits.clear()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["mode"] == "rules"


def test_places(client):
    body = client.get("/api/places").json()
    assert len(body["landmarks"]) >= 40
    assert {p["name"] for p in body["demo_saved_places"]} == {"الدار", "الشغل", "الجامعة"}


def test_chat_then_panel_buttons(client):
    resp = client.post("/api/chat", json={"message": "من اربد لعمان"})
    assert resp.status_code == 200
    trip = resp.json()["trip"]
    assert trip["start"]["name"] == "إربد" and len(trip["quotes"]) == 4 and trip["status"] == "draft"

    switched = client.post("/api/trip/action", json={"trip": trip, "action": "car", "car_type": "vip"}).json()
    assert switched["trip"]["car_type"] == "vip" and switched["action"] == "car_changed"

    booked = client.post("/api/trip/action", json={"trip": switched["trip"], "action": "confirm"}).json()
    assert booked["trip"]["status"] == "confirmed" and booked["trip"]["driver"]["eta_min"] >= 1


def test_saved_place_from_the_browser(client):
    saved = [{"name": "الدار", "lat": 32.50, "lng": 35.86}]
    body = client.post("/api/chat", json={"message": "من الدار لعمان", "saved_places": saved}).json()
    assert body["trip"]["start"]["source"] == "saved"


def test_input_limits(client):
    assert client.post("/api/chat", json={"message": "x" * 301}).status_code == 422
    assert client.post("/api/chat", json={"message": ""}).status_code == 422


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(rate_limit, "per_minute", 2)
    codes = [client.post("/api/chat", json={"message": "مرحبا"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
