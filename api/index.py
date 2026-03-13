"""Vercel/FastAPI compatibility entrypoint."""

from api.main import app, handler

__all__ = ["app", "handler"]
