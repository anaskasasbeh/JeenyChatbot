"""Web entry point. Locally: uvicorn app:app --reload · On Render: see render.yaml."""

from jeenychatbot.api import app

__all__ = ["app"]
