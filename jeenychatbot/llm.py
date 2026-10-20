"""Chat models behind an OpenAI-compatible API.

Groq, Google Gemini and OpenAI all expose the same chat-completions API, so one
`ChatOpenAI` class works for all of them: only `base_url`, `api_key` and `model`
change (set in `.env`). Switching provider never needs a code change.
"""

from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from .config import LLMSettings, Settings

logger = logging.getLogger(__name__)


def _make(llm: LLMSettings, timeout_s: float) -> BaseChatModel:
    kwargs = {}
    if llm.reasoning_effort:
        kwargs["reasoning_effort"] = llm.reasoning_effort  # e.g. "low" for gpt-oss: faster tool calls
    return ChatOpenAI(
        model=llm.model,
        base_url=llm.base_url,
        api_key=llm.api_key,
        temperature=0,
        timeout=timeout_s,
        max_retries=1,  # fail over to the next model quickly instead of retrying a dead quota
        **kwargs,
    )


def build_models(settings: Settings) -> list[BaseChatModel]:
    """Return the configured models in priority order (may be empty = rule-based mode)."""
    models: list[BaseChatModel] = []
    if settings.primary_llm.enabled:
        models.append(_make(settings.primary_llm, settings.llm_timeout_s))
        logger.info("Primary LLM: %s @ %s", settings.primary_llm.model, settings.primary_llm.base_url)
    if settings.fallback_llm.enabled:
        models.append(_make(settings.fallback_llm, settings.llm_timeout_s))
        logger.info("Fallback LLM: %s @ %s", settings.fallback_llm.model, settings.fallback_llm.base_url)
    if not models:
        logger.warning("No LLM API key configured: running in rule-based mode.")
    return models
