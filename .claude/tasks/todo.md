# Fix: DB High-Scale Connections, SafeWriter Bugs, Redis Config, WebSocket Page-Load

## Issues
1. [ ] SafeWriter bugs: missing raise, KeyError, error=str(e) violations
2. [ ] DB: no pool settings → add pool_size/max_overflow/pool_timeout/pool_recycle
3. [ ] Config: add DB pool + Redis pool env vars
4. [ ] Redis: hardcoded max_connections=30 → configurable
5. [ ] WebSocket: depends on page-load HTTP polling → push initial snapshot + periodic updates
6. [ ] Frontend: remove setInterval polling → use WS store data

## Files
- api/core/writer/safe_writer.py
- api/database.py
- api/config.py
- api/redis_client.py
- api/routes/ws.py
- api/services/websocket_broadcaster.py
- frontend/src/stores/useCodexStore.ts
- frontend/src/app/dashboard/DashboardView.tsx
- frontend/src/hooks/useGlobalWebSocket.ts

## Results
