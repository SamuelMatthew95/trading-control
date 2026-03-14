"""Vercel Python serverless function handler."""

import json
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, '/var/task')

FASTAPI_AVAILABLE = False
app = None

try:
    from api.main import app
    FASTAPI_AVAILABLE = True
except Exception:
    pass


class handler(BaseHTTPRequestHandler):
    """Vercel Python HTTP handler."""
    
    def do_GET(self):
        self._send_json_response(200, {
            'success': True,
            'data': {
                'status': 'healthy',
                'message': 'Trading Control API is running',
                'fastapi_available': FASTAPI_AVAILABLE
            },
            'error': None
        })
    
    def do_POST(self):
        self._send_json_response(200, {
            'success': True,
            'data': {'message': 'POST endpoint working'},
            'error': None
        })
    
    def do_OPTIONS(self):
        self._send_json_response(200, {
            'success': True,
            'data': {'message': 'CORS preflight successful'},
            'error': None
        })
    
    def _send_json_response(self, status_code, data):
        """Send JSON response."""
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
