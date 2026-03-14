"""Vercel Python serverless function handler."""

import json
import sys
from http.server import BaseHTTPRequestHandler

# Add the project root to Python path for imports
sys.path.insert(0, '/var/task')

try:
    from api.main import app
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    app = None


class handler(BaseHTTPRequestHandler):
    """Vercel Python HTTP handler."""
    
    def do_GET(self):
        self._send_json_response(200, {
            'success': True,
            'data': {
                'status': 'healthy',
                'message': 'Trading Control API is running',
                'fastapi_available': FASTAPI_AVAILABLE,
                'endpoints': [
                    '/api/health',
                    '/api/trades', 
                    '/api/signals',
                    '/api/dashboard/pnl',
                    '/api/dashboard/learning-velocity'
                ]
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
