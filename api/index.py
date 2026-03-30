import os
import sys
import logging

# Configure logging for debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In Vercel, /var/task is the root, so we need to add current directory to path
# to import main.py directly from the same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from main import app

    logger.info("✅ FastAPI app imported successfully")

    # Test if dashboard routes are registered
    from fastapi.routing import APIRoute

    dashboard_routes = [r.path for r in app.routes if hasattr(r, "path") and "/dashboard" in r.path]
    logger.info(f"📋 Dashboard routes found: {dashboard_routes}")

except Exception as e:
    logger.error(f"❌ Failed to import FastAPI app: {e}")
    app = None


class Handler:
    def __init__(self):
        self.app = app

    def __call__(self, environ, start_response):
        if not self.app:
            start_response("500 Internal Server Error", [("Content-Type", "text/plain")])
            return [b"FastAPI app failed to load"]

        # Log incoming requests for debugging
        path = environ.get("PATH_INFO", "")
        method = environ.get("REQUEST_METHOD", "")
        logger.info(f"🌐 {method} {path}")

        # Handle root path with a helpful response
        if path == '/':
            start_response('200 OK', [('Content-Type', 'application/json')])
            response = {
                "message": "Trading Control API",
                "status": "running",
                "endpoints": {
                    "health": "/api/health",
                    "dashboard": "/api/dashboard/*",
                    "docs": "/docs"
                },
                "dashboard_routes": dashboard_routes if 'dashboard_routes' in locals() else []
            }
            import json
            return [json.dumps(response).encode()]

        return self.app(environ, start_response)


# Vercel needs this
handler_instance = Handler()
