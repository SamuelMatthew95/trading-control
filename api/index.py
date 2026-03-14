"""Vercel Python serverless function handler."""

import json
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, '/var/task')

FASTAPI_AVAILABLE = False
FASTAPI_IMPORT_ERROR = None
app = None
mangum_handler = None

try:
    from api.main import app
    from mangum import Mangum
    mangum_handler = Mangum(app, lifespan="off")
    FASTAPI_AVAILABLE = True
except Exception as e:
    FASTAPI_IMPORT_ERROR = str(e)


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
        
        # If FastAPI is available, delegate to Mangum handler
        if FASTAPI_AVAILABLE and mangum_handler:
            try:
                # Use Mangum to handle ASGI app
                from mangum.handler import MangumHandler
                
                # Create ASGI scope from BaseHTTPRequestHandler
                scope = {
                    'type': 'http',
                    'method': method,
                    'path': path,
                    'query_string': '',
                    'headers': dict(self.headers.items()),
                    'server': ('vercel', '1.0'),
                }
                
                # Create receive callable
                def receive():
                    # Read request body
                    content_length = int(self.headers.get('Content-Length', 0))
                    if content_length > 0:
                        body = self.rfile.read(content_length)
                        return {'type': 'http.request', 'body': body, 'more_body': False}
                    return {'type': 'http.request', 'body': b'', 'more_body': False}
                
                # Create send callable
                async def send(message):
                    if message['type'] == 'http.response.start':
                        self.send_response(message['status'])
                        for name, value in message.get('headers', []):
                            self.send_header(name, value)
                        self.end_headers()
                    elif message['type'] == 'http.response.body':
                        self.wfile.write(message.get('body', b''))
                
                # Use MangumHandler to process ASGI app
                handler = MangumHandler(mangum_handler)
                
                # Run the ASGI app
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(handler(scope, receive, send))
                return
                
            except Exception as e:
                # Fallback to basic response if ASGI handling fails
                self._send_json_response(500, {
                    'success': False,
                    'data': None,
                    'error': f'ASGI error: {str(e)}'
                })
        
        # Fallback responses when FastAPI not available
        if path in ('/api/health', '/health'):
            self._send_json_response(200, {
                'success': True,
                'data': {
                    'status': 'healthy', 
                    'fastapi_available': FASTAPI_AVAILABLE,
                    'import_error': FASTAPI_IMPORT_ERROR
                },
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
