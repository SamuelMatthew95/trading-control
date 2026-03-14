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
        """Handle HTTP request with basic routing."""
        try:
            # Parse path
            path = self.path.rstrip('/')
            
            # Basic routing for health check
            if path == '/api/health' or path == '/health':
                self._send_json_response(200, {
                    'success': True,
                    'data': {
                        'status': 'healthy',
                        'message': 'API is running',
                        'fastapi_available': FASTAPI_AVAILABLE
                    },
                    'error': None
                })
                return
            
            # Basic routing for trades
            if path == '/api/trades' or path == '/trades':
                if method == 'GET':
                    self._send_json_response(200, {
                        'success': True,
                        'data': {'trades': []},
                        'error': None
                    })
                elif method == 'POST':
                    # Read request body
                    content_length = int(self.headers.get('Content-Length', 0))
                    post_data = self.rfile.read(content_length) if content_length > 0 else b''
                    
                    self._send_json_response(201, {
                        'success': True,
                        'data': {'message': 'Trade created', 'id': 'mock-id'},
                        'error': None
                    })
                return
            
            # Basic routing for signals
            if path == '/api/signals' or path == '/signals':
                self._send_json_response(200, {
                    'success': True,
                    'data': {'items': []},
                    'error': None
                })
                return
            
            # Default response for other paths
            self._send_json_response(404, {
                'success': False,
                'data': None,
                'error': f'Endpoint not found: {method} {path}'
            })
            
        except Exception as e:
            self._send_json_response(500, {
                'success': False,
                'data': None,
                'error': f'Internal server error: {str(e)}'
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
