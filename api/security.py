"""API auth utilities."""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from api.config import settings

PROTECTED_PREFIXES = (
    "/api/analyze",
    "/api/shadow",
    "/api/trades",
    "/api/performance",
    "/api/statistics",
    "/api/runs",
)


def enforce_api_key(request: Request) -> None:
    if not settings.API_SECRET_KEY:
        return

    if request.method == "OPTIONS" or not request.url.path.startswith(
        PROTECTED_PREFIXES
    ):
        return

    provided = request.headers.get("x-api-key")
    if provided != settings.API_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized API request"
        )
