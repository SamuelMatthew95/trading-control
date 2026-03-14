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

    def do_GET(self):
        self._handle_request('GET')

    def do_POST(self):
        self._handle_request('POST')

    def do_PUT(self):
        self._handle_request('PUT')

    def do_DELETE(self):
        self._handle_request('DELETE')

    def do_OPTIONS(self):
        self._handle_request('OPTIONS')

    def _handle_request(self, method):
        path = self.path.rstrip('/')
        if path in ('/api/health', '/health'):
            self._send_json_response(200, {
                'success': True,
                'data': {'status': 'healthy', 'fastapi_available': FASTAPI_AVAILABLE},
                'error': None
            })
        else:
            self._send_json_response(404, {
                'success': False,
                'data': None,
                'error': f'Endpoint not found: {method} {path}'
            })

    def _send_json_response(self, status_code, data):
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
