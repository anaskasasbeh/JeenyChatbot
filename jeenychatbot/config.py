"""Application settings, read once from environment variables (and an optional .env file)."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

DEFAULT_USER_AGENT = "JeenyChatbot/1.0 (+https://github.com/anaskasasbeh/JeenyChatbot)"


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class LLMSettings:
    """One OpenAI-compatible chat endpoint (Groq, Gemini, OpenAI, ...)."""

    api_key: str
    base_url: str
    model: str
    reasoning_effort: str = ""  # only for reasoning models such as gpt-oss ("low" = faster)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.model)


@dataclass(frozen=True)
class Settings:
    primary_llm: LLMSettings
    fallback_llm: LLMSettings
    llm_timeout_s: float
    user_agent: str
    nominatim_url: str
    photon_url: str
    osrm_url: str  # comma-separated list, tried in order
    http_timeout_s: float
    rate_limit_per_minute: int
    log_level: str
    map_tiles_url: str
    map_tiles_attribution: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process."""
    load_dotenv(PROJECT_ROOT / ".env")
    return Settings(
        primary_llm=LLMSettings(
            api_key=_env("LLM_API_KEY"),
            base_url=_env("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
            model=_env("LLM_MODEL", "openai/gpt-oss-120b"),
            reasoning_effort=_env("LLM_REASONING_EFFORT", "low"),
        ),
        fallback_llm=LLMSettings(
            api_key=_env("FALLBACK_LLM_API_KEY"),
            base_url=_env(
                "FALLBACK_LLM_BASE_URL",
                "https://generativelanguage.googleapis.com/v1beta/openai/",
            ),
            model=_env("FALLBACK_LLM_MODEL", "gemini-flash-lite-latest"),
            reasoning_effort=_env("FALLBACK_LLM_REASONING_EFFORT", ""),
        ),
        llm_timeout_s=float(_env("LLM_TIMEOUT_S", "25")),
        user_agent=_env("GEO_USER_AGENT", DEFAULT_USER_AGENT),
        nominatim_url=_env("NOMINATIM_URL", "https://nominatim.openstreetmap.org"),
        photon_url=_env("PHOTON_URL", "https://photon.komoot.io"),
        osrm_url=_env("OSRM_URL", "https://router.project-osrm.org,https://routing.openstreetmap.de/routed-car"),
        http_timeout_s=float(_env("HTTP_TIMEOUT_S", "8")),
        rate_limit_per_minute=int(_env("RATE_LIMIT_PER_MINUTE", "15")),
        log_level=_env("LOG_LEVEL", "INFO").upper(),
        # OSM tile policy: https://operations.osmfoundation.org/policies/tiles/ (no key, attribution required)
        map_tiles_url=_env("MAP_TILES_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png"),
        map_tiles_attribution=_env(
            "MAP_TILES_ATTRIBUTION",
            '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        ),
    )


def use_utf8_console() -> None:
    """Print Arabic safely on Windows terminals such as Git Bash (whose default encoding is cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def setup_logging(level: str = "INFO") -> None:
    """Configure a simple, readable log format (idempotent)."""
    use_utf8_console()
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    root.setLevel(level)
    # Third-party HTTP clients are noisy at INFO.
    for noisy in ("httpx", "httpcore", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
