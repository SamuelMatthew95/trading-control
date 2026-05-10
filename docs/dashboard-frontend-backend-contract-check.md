# Dashboard Frontend/Backend Contract Check

This note records a route-level contract verification between frontend dashboard API calls and backend routes in `api/routes/dashboard_v2.py`.

## Verified

- Frontend API paths in `frontend/src/lib/apiClient.ts` match backend dashboard routes.
- `api(path)` uses `NEXT_PUBLIC_API_URL` and includes a `guardDoublePrefix` check for `/api/api/`.
- WebSocket URL derivation in `frontend/src/hooks/useGlobalWebSocket.ts` points to `/ws/dashboard` and strips trailing `/api` when deriving from `NEXT_PUBLIC_API_URL`.

## Operator/debug dashboard paths

- `/dashboard/events/recent`
- `/dashboard/history/events`
- `/dashboard/performance-trends`
- `/dashboard/agent-instances`
- `/dashboard/trace/{trace_id}`

All above exist in `dashboard_v2.py`.
