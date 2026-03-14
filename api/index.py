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
        
        # If FastAPI is available, delegate to it
        if FASTAPI_AVAILABLE and app:
            try:
                # Create a mock request for FastAPI
                from io import BytesIO
                from fastapi.testclient import TestClient
                
                client = TestClient(app)
                
                # Read request body for POST/PUT
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length) if content_length > 0 else b''
                
                # Route to FastAPI
                if method == 'GET':
                    response = client.get(path)
                elif method == 'POST':
                    response = client.post(path, content=body)
                elif method == 'PUT':
                    response = client.put(path, content=body)
                elif method == 'DELETE':
                    response = client.delete(path)
                elif method == 'OPTIONS':
                    response = client.options(path)
                else:
                    response = client.get(path)
                
                # Send FastAPI response
                self.send_response(response.status_code)
                for key, value in response.headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(response.content)
                return
                
            except Exception as e:
                # Fallback to basic response if FastAPI fails
                self._send_json_response(500, {
                    'success': False,
                    'data': None,
                    'error': f'FastAPI error: {str(e)}'
                })
        
        # Fallback responses when FastAPI not available
        if path in ('/api/health', '/health'):
            self._send_json_response(200, {
                'success': True,
                'data': {'status': 'healthy', 'fastapi_available': FASTAPI_AVAILABLE},
                'error': None
            })
        elif path.startswith('/api/dashboard/'):
            # Mock dashboard responses since FastAPI isn't available
            if path == '/api/dashboard/pnl':
                self._send_json_response(200, {
                    'success': True,
                    'data': {
                        'total_pnl': 0.0,
                        'pnl_today': 0.0,
                        'pnl_today_pct_change': 0.0,
                        'avg_slippage_saved': 0.0,
                        'execution_cost': 0.0,
                        'net_alpha': 0.0
                    },
                    'error': None
                })
            elif path == '/api/dashboard/learning-velocity':
                self._send_json_response(200, {
                    'success': True,
                    'data': {
                        'passk_trend': [],
                        'passk_series': [],
                        'coherence_series': []
                    },
                    'error': None
                })
            elif path == '/api/dashboard/health-signals':
                self._send_json_response(200, {
                    'success': True,
                    'data': {'items': []},
                    'error': None
                })
            elif path == '/api/dashboard/run-summary':
                self._send_json_response(200, {
                    'success': True,
                    'data': {'items': []},
                    'error': None
                })
            else:
                self._send_json_response(404, {
                    'success': False,
                    'data': None,
                    'error': f'Endpoint not found: {method} {path}'
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
