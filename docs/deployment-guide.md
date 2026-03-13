# Deployment Guide

This project is typically deployed as:

- FastAPI backend (`api.main:app`) on an ASGI-compatible platform.
- Optional frontend (`frontend/`) deployed separately (e.g., Vercel).

## Required environment variables

- `DATABASE_URL` (PostgreSQL)
- `NODE_ENV` (`production` in prod)

Optional:

- `ANTHROPIC_API_KEY`
- `FRONTEND_URL` (CORS origin for backend)

## Backend deployment checklist

1. Provision PostgreSQL and set `DATABASE_URL`.
2. Deploy app with entrypoint `api.main:app`.
3. Ensure startup passes DB connectivity and schema init.
4. Verify endpoints:
   - `GET /`
   - `GET /api/health`
   - key API routes under `/api/*`
5. Monitor application logs for startup/runtime exceptions.

## Frontend deployment notes

- Configure frontend API base URL to target deployed backend.
- Ensure backend `FRONTEND_URL` allows the deployed frontend origin.

## Post-deploy smoke checks

```bash
curl -sS https://<backend-host>/api/health
curl -sS https://<backend-host>/
```
