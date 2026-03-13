from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from api.config import settings


async def enforce_api_key(request: Request, call_next):
    """Optional API key middleware.

    If `API_KEY` is not configured, enforcement is disabled.
    """
    configured_key = settings.API_KEY
    if configured_key:
        supplied = request.headers.get("x-api-key")
        if supplied != configured_key:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)
