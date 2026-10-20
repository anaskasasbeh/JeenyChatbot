"""FastAPI web API. On Vercel the `public/` folder is served by the CDN; locally we mount it here."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict, deque
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import PROJECT_ROOT, get_settings, setup_logging
from .models import ChatRequest, ChatResponse, TripActionRequest
from .places import load_demo_saved_places, load_landmarks
from .service import ChatService

settings = get_settings()
setup_logging(settings.log_level)
logger = logging.getLogger(__name__)

PUBLIC_DIR = PROJECT_ROOT / "public"

app = FastAPI(
    title="JeenyChatbot API",
    version=__version__,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)


@lru_cache(maxsize=1)
def get_service() -> ChatService:
    return ChatService.from_settings(settings)


# ------------------------------------------------------------------ rate limit
class RateLimiter:
    """Best-effort per-IP sliding window. Protects the free LLM quota from abuse."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def __call__(self, request: Request) -> None:
        if self.per_minute <= 0:
            return
        forwarded = request.headers.get("x-forwarded-for", "")
        ip = forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")
        now = time.monotonic()
        with self._lock:
            hits = self._hits[ip]
            while hits and now - hits[0] > 60:
                hits.popleft()
            if len(hits) >= self.per_minute:
                raise HTTPException(status_code=429, detail="Too many requests. Please wait a minute.")
            hits.append(now)


rate_limit = RateLimiter(settings.rate_limit_per_minute)  # chat messages (may call the LLM)
button_limit = RateLimiter(max(60, settings.rate_limit_per_minute * 4))  # panel buttons (no LLM)


# ---------------------------------------------------------------------- routes
@app.get("/api/health")
def health(service: ChatService = Depends(get_service)) -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "mode": "ai" if service.ai_enabled else "rules",
        "llm": {
            "primary": settings.primary_llm.model if settings.primary_llm.enabled else None,
            "fallback": settings.fallback_llm.model if settings.fallback_llm.enabled else None,
        },
        "tiles": {"url": settings.map_tiles_url, "attribution": settings.map_tiles_attribution},
    }


@app.get("/api/places")
def places() -> dict:
    """Public landmarks (for map hints) and demo saved places (pre-filled in the browser)."""
    return {
        "landmarks": [
            {"id": lm.id, "kind": lm.kind, "name_ar": lm.name_ar, "name_en": lm.name_en, "lat": lm.lat, "lng": lm.lng}
            for lm in load_landmarks()
        ],
        "demo_saved_places": load_demo_saved_places(),
    }


@app.post("/api/chat", response_model=ChatResponse, dependencies=[Depends(rate_limit)])
def chat(req: ChatRequest, service: ChatService = Depends(get_service)) -> ChatResponse:
    return service.handle(req)


@app.post("/api/trip/action", response_model=ChatResponse, dependencies=[Depends(button_limit)])
def trip_action(req: TripActionRequest, service: ChatService = Depends(get_service)) -> ChatResponse:
    """Trip panel buttons (car type, confirm, cancel, use my location): instant, no LLM call."""
    return service.trip_action(req)


# Local development only: Vercel serves public/ from its CDN and must not mount it.
if not os.getenv("VERCEL") and PUBLIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=PUBLIC_DIR, html=True), name="public")
