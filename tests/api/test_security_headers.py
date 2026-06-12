"""Security headers must be present on every response (Phase 8 hardening)."""

from httpx import ASGITransport, AsyncClient

from api.main import app


async def test_security_headers_present():
    # base_url must be http://localhost — TrustedHostMiddleware rejects "test".
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
        response = await client.get("/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cache-Control"] == "no-store"
    assert "X-Request-ID" in response.headers
    # Plain-http test client → HSTS must NOT be set (https-only header).
    assert "Strict-Transport-Security" not in response.headers
