"""Check that the LLM keys in .env work: lists the models you can use and sends one tiny request.

Usage:
    python scripts/check_llm.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from openai import OpenAI  # noqa: E402  (installed with langchain-openai)

from jeenychatbot.config import LLMSettings, get_settings, use_utf8_console  # noqa: E402


def check(label: str, llm: LLMSettings) -> bool:
    if not llm.enabled:
        print(f"[{label}] no API key in .env - skipped")
        return False
    client = OpenAI(api_key=llm.api_key, base_url=llm.base_url, timeout=30, max_retries=0)
    try:
        ids = sorted(m.id for m in client.models.list())
    except Exception as exc:  # noqa: BLE001
        print(f"[{label}] could not list models at {llm.base_url}: {type(exc).__name__}: {exc}")
        return False
    if llm.model not in ids:
        print(f"[{label}] model '{llm.model}' is not in your account's list. Available models:")
        for model_id in ids:
            print("   ", model_id)
        return False
    started = time.perf_counter()
    try:
        reply = client.chat.completions.create(
            model=llm.model,
            messages=[{"role": "user", "content": "رد بكلمة وحدة: أهلين"}],
            max_tokens=200,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[{label}] request failed: {type(exc).__name__}: {exc}")
        return False
    elapsed = time.perf_counter() - started
    text = (reply.choices[0].message.content or "").strip()
    print(f"[{label}] OK  model={llm.model}  reply={text!r}  time={elapsed:.2f}s")
    return True


def main() -> None:
    use_utf8_console()
    settings = get_settings()
    ok = check("primary", settings.primary_llm)
    check("fallback", settings.fallback_llm)
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
