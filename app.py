"""Web entry point, auto-detected by Vercel. Run locally with: uvicorn app:app --reload"""

from jeenychatbot.api import app

__all__ = ["app"]
