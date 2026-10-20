"""One chat turn, end to end. Used by the web API and the CLI.

LLM agent first; if no key is configured or every model fails (quota, outage),
the rule-based parser answers instead, so the demo keeps working.
"""

from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel

from . import messages
from .actions import TurnContext
from .agent import run_agent
from .config import Settings, get_settings
from .fallback_parser import parse, parse_nearby
from .geocoding import OSMGeocoder
from .llm import build_models
from .models import ChatRequest, ChatResponse, TripActionRequest
from .places import build_place_book
from .routing import OSRMRouter
from .trips import TripPlanner

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(self, planner: TripPlanner, models: list[BaseChatModel] | None = None) -> None:
        self.planner = planner
        self.models = list(models or [])

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "ChatService":
        settings = settings or get_settings()
        geocoder = OSMGeocoder(
            user_agent=settings.user_agent,
            nominatim_url=settings.nominatim_url,
            photon_url=settings.photon_url,
            timeout_s=settings.http_timeout_s,
        )
        router = OSRMRouter(settings.osrm_url, settings.user_agent, max(settings.http_timeout_s, 12.0))
        return cls(TripPlanner(geocoder, router), build_models(settings))

    @property
    def ai_enabled(self) -> bool:
        return bool(self.models)

    # ------------------------------------------------------------------ chat
    def handle(self, req: ChatRequest) -> ChatResponse:
        lang = messages.reply_language(req.message, req.lang)
        if self.models:
            ctx = self._context(req, lang)
            try:
                run = run_agent(self.models, ctx, req.message, req.history)
                # The model answered with nothing usable (no tool ran): let the rules try this turn.
                reply = run.reply or self.answer_with_rules(ctx, req.message)
                return ChatResponse(
                    reply=reply, action=ctx.action, mode="ai", trip=ctx.trip, pin=ctx.pin, need_location=ctx.need_location
                )
            except Exception as exc:  # quota, network, provider outage...
                logger.warning("LLM unavailable, answering with rules: %s", exc)
        ctx = self._context(req, lang)
        reply = self.answer_with_rules(ctx, req.message)
        return ChatResponse(
            reply=reply, action=ctx.action, mode="rules", trip=ctx.trip, pin=ctx.pin, need_location=ctx.need_location
        )

    def trip_action(self, req: TripActionRequest) -> ChatResponse:
        """Trip panel buttons (car type, confirm, cancel, use my location): deterministic, no LLM call."""
        ctx = TurnContext(self.planner, build_place_book(), req.lang, trip=req.trip, current_location=req.current_location)
        if req.trip is None and req.action != "pin":
            reply = messages.error_message("no_trip", req.lang)
        elif req.action == "car" and req.car_type:
            reply = ctx.change_car_type(req.car_type)
        elif req.action == "confirm":
            reply = ctx.confirm_trip()
        elif req.action == "cancel":
            reply = ctx.cancel_trip()
        elif req.action == "pickup_here":
            reply = ctx.use_current_location_as_pickup()
        elif req.action == "pin" and req.pin and req.point:
            reply = ctx.pin_on_map(req.pin, req.point)
        else:
            reply = messages.error_message("internal", req.lang)
        return ChatResponse(reply=reply, action=ctx.action, mode="rules", trip=ctx.trip)

    # --------------------------------------------------------------- helpers
    def _context(self, req: ChatRequest, lang: str) -> TurnContext:
        return TurnContext(
            planner=self.planner,
            book=build_place_book(req.saved_places),
            lang=lang,
            trip=req.trip,
            current_location=req.current_location,
            pending=req.pending_pin,
        )

    @staticmethod
    def answer_with_rules(ctx: TurnContext, message: str) -> str:
        nearby = parse_nearby(message) if ctx.pending else None
        if nearby:
            return ctx.place_near(nearby)
        intent = parse(message, has_trip=ctx.trip is not None)
        if intent.action == "new_trip":
            return ctx.request_trip(intent.end, intent.start, intent.car_type)
        if intent.action == "change_car" and intent.car_type:
            return ctx.change_car_type(intent.car_type)
        if intent.action == "modify_trip":
            return ctx.modify_trip(intent.start, intent.end)
        if intent.action == "confirm":
            return ctx.confirm_trip()
        if intent.action == "cancel":
            return ctx.cancel_trip()
        if intent.action == "thanks":
            return messages.thanks_message(ctx.lang)
        return messages.help_message(ctx.lang)
