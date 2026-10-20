"""The LLM agent: understands the message and calls one of three tools.

Built with LangChain's `create_agent` (the replacement for the removed
`initialize_agent`). The model reads the user's message and fills the tool
arguments itself (pickup, destination, car type), so one model call is usually
enough. Tools are `return_direct`, so the tool's reply ends the turn without a
second "summarize the result" call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ModelFallbackMiddleware
from langchain.tools import tool
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from .actions import TurnContext
from .models import CarType, ChatTurn
from .pricing import CAR_OPTIONS

logger = logging.getLogger(__name__)

MAX_MODEL_CALLS = 3
HISTORY_TURNS = 8
HISTORY_CHARS = 400

# Jordan has used UTC+3 all year since 2022. A fixed offset needs no time-zone database,
# which Windows and some servers don't ship.
JORDAN_TZ = timezone(timedelta(hours=3))

SYSTEM_PROMPT = """You are the assistant inside JeenyChatbot, a ride-booking demo for Jordan.
Users write in Jordanian Arabic dialect or in English. Act like a smart ride app: remember what the user already told you.

Tools:
- request_trip: a NEW ride (also "how much from X to Y").
- modify_trip: change ONLY the pickup and/or ONLY the destination of the current ride. Whatever is not mentioned is kept.
- change_car_type: another car type for the current ride.
- confirm_trip: the user clearly agrees to book ("أكد", "اطلبها", "تمام احجز", "yes, book it").
- cancel_trip: the user wants to cancel the ride.
- place_near: only when a place was just "not found" (see Context) and the user now says where it is or what is near it.
Car types: economy (عادية, default), taxi (تاكسي), family (عائلية, 7 seats), vip (VIP, فاخرة).

Context rules:
- If a current ride exists and the user mentions only a new pickup ("من موقعي", "خليها من الدار", "pick me up at ..."), call modify_trip with new_pickup only. If they mention only a destination, call modify_trip with new_destination only. Never ask again for something you already know.
- Combine details across turns: a pickup mentioned earlier still applies when the user later gives the destination.
- "موقعي" / "my location" means the user's shared location: pass it as "موقعي".
- If the user shared their location and gives only a destination, leave pickup empty: the shared location is the pickup.
- If they want to start from their location but it isn't shared yet, still call the tool (pickup "موقعي", or empty): the app asks the browser for the location by itself. Don't tell them to press a button.
- Copy each place with ALL its words as the user wrote them ("الجامعة الأردنية", not "الجامعة"), only without words like "الوجهة", "اللي عند", "قريب من", "near". A saved place counts only when the user says its name.
- Understand places like a local would: ALSO fill the *_full_name field with the official full name you know, in English with its city, so the map search finds it (e.g. "البزنس بارك" -> "King Hussein Business Park, Amman"; "الشط الجنوبي بالعقبة" -> "South Beach, Aqaba"). Leave *_full_name empty for the user's saved places or when unsure.
- When the context says a place was not found, an answer like "قريب من مجمع عمان", "جنب الجامعة", "it's inside Abdali Mall" or just a landmark name tells you where that place is: call place_near with that landmark.
- Ask a short question only when there is no current ride and the destination is unknown.
- Never invent prices, distances, places or drivers. Only the tools compute them.
- For anything else, answer in 1-2 short sentences in {language}. The service covers Jordan only.
- For the time or date, use the "Now in Jordan" line below. Never guess a time.

Context:
- Now in Jordan: {now}
- Current ride: {trip}
- User's saved places: {saved}
- User shared their current location: {location}
- Place not found yet: {pending}"""


@dataclass
class AgentRun:
    reply: str
    model_calls: int


class _ModelCallCounter(BaseCallbackHandler):
    """Counts chat-model calls in one turn (reported by the evaluation script)."""

    def __init__(self) -> None:
        self.count = 0

    def on_chat_model_start(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.count += 1


def build_tools(ctx: TurnContext) -> list:
    """Tools bound to this turn's context (trip, saved places, location)."""

    @tool(return_direct=True, parse_docstring=True)
    def request_trip(
        destination: str,
        pickup: Optional[str] = None,
        car_type: Optional[CarType] = None,
        destination_full_name: Optional[str] = None,
        pickup_full_name: Optional[str] = None,
    ) -> str:
        """Plan a NEW ride and show its route and fares (the user confirms later).

        Args:
            destination: The destination as the user said it, without filler words (e.g. "البزنس بارك", "الدار").
            pickup: The pickup as the user said it, or "موقعي" for the shared location. Empty if not said.
            car_type: One of economy, taxi, family, vip. Empty if not mentioned.
            destination_full_name: Your best guess of the destination's official full name for a map search, in English, with its city (e.g. "King Hussein Business Park, Amman"). Empty for saved places or if unsure.
            pickup_full_name: Same for the pickup.
        """
        return ctx.request_trip(destination, pickup, car_type, destination_full_name, pickup_full_name)

    @tool(return_direct=True, parse_docstring=True)
    def modify_trip(
        new_pickup: Optional[str] = None,
        new_destination: Optional[str] = None,
        new_pickup_full_name: Optional[str] = None,
        new_destination_full_name: Optional[str] = None,
    ) -> str:
        """Change only the pickup and/or only the destination of the CURRENT ride; everything else is kept.

        Args:
            new_pickup: New pickup as the user said it, or "موقعي". Empty to keep the current pickup.
            new_destination: New destination as the user said it. Empty to keep the current destination.
            new_pickup_full_name: Official full name of the new pickup for a map search, in English with its city. Empty if unsure.
            new_destination_full_name: Official full name of the new destination for a map search, in English with its city. Empty if unsure.
        """
        return ctx.modify_trip(new_pickup, new_destination, new_pickup_full_name, new_destination_full_name)

    @tool(return_direct=True, parse_docstring=True)
    def change_car_type(car_type: CarType) -> str:
        """Change the car type of the CURRENT ride and re-price it.

        Args:
            car_type: One of economy, taxi, family, vip.
        """
        return ctx.change_car_type(car_type)

    @tool(return_direct=True)
    def confirm_trip() -> str:
        """Book the CURRENT ride after the user clearly agrees. Assigns a (simulated) driver."""
        return ctx.confirm_trip()

    @tool(return_direct=True)
    def cancel_trip() -> str:
        """Cancel the CURRENT ride."""
        return ctx.cancel_trip()

    @tool(return_direct=True, parse_docstring=True)
    def place_near(nearby: str, nearby_full_name: Optional[str] = None) -> str:
        """The place that was not found is at or near this landmark. Puts it there; the user can fine-tune it on the map.

        Args:
            nearby: The landmark the user named, as they said it (e.g. "مجمع عمان", "العبدلي مول").
            nearby_full_name: Its official full name for a map search, in English with its city. Empty if unsure.
        """
        return ctx.place_near(nearby, nearby_full_name)

    # Always offered: a model that calls a tool missing from the request gets an error from the provider.
    return [request_trip, modify_trip, change_car_type, confirm_trip, cancel_trip, place_near]


def _system_prompt(ctx: TurnContext) -> str:
    if ctx.trip:
        car = CAR_OPTIONS[ctx.trip.car_type].label("en")
        trip = (
            f"pickup {ctx.trip.start.name} -> destination {ctx.trip.end.name}, {car}, "
            f"{ctx.trip.price:.2f} JOD, status {ctx.trip.status}"
        )
    else:
        trip = "none"
    saved = ", ".join(ctx.book.saved_names()) or "none"
    return SYSTEM_PROMPT.format(
        now=datetime.now(JORDAN_TZ).strftime("%A %Y-%m-%d, %H:%M (UTC+3)"),
        language="English" if ctx.lang == "en" else "Jordanian Arabic",
        trip=trip,
        saved=saved,
        location="yes" if ctx.current_location else "no",
        pending=f"«{ctx.pending.label}» ({ctx.pending.role})" if ctx.pending else "none",
    )


def _history(turns: list[ChatTurn]) -> list[BaseMessage]:
    result: list[BaseMessage] = []
    for turn in turns[-HISTORY_TURNS:]:
        content = turn.content[:HISTORY_CHARS]
        result.append(HumanMessage(content) if turn.role == "user" else AIMessage(content))
    return result


def _text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, list):  # some providers return content blocks
        content = " ".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    return str(content or "").strip()


def run_agent(models: list[BaseChatModel], ctx: TurnContext, message: str, history: list[ChatTurn]) -> AgentRun:
    """Run one turn. Raises if every configured model fails (the caller falls back to rules)."""
    primary, *fallbacks = models
    middleware = [ModelCallLimitMiddleware(run_limit=MAX_MODEL_CALLS, exit_behavior="end")]
    if fallbacks:
        middleware.insert(0, ModelFallbackMiddleware(*fallbacks))
    agent = create_agent(primary, build_tools(ctx), system_prompt=_system_prompt(ctx), middleware=middleware)

    counter = _ModelCallCounter()
    result = agent.invoke(
        {"messages": [*_history(history), HumanMessage(message)]},
        config={"callbacks": [counter]},
    )
    last = result["messages"][-1]
    reply = _text(last)
    if not isinstance(last, ToolMessage) and (not reply or counter.count >= MAX_MODEL_CALLS):
        reply = ""  # no usable answer: the service lets the rules answer this turn
    logger.info("Agent turn: %d model call(s), action=%s", counter.count, ctx.action)
    return AgentRun(reply=reply, model_calls=counter.count)
