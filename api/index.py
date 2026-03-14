"""Vercel Python serverless function handler."""

import json
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, '/var/task')

FASTAPI_AVAILABLE = False
FASTAPI_IMPORT_ERROR = None
mangum_handler = None

try:
    from api.main import app
    from mangum import Mangum
    mangum_handler = Mangum(app, lifespan="off")
    FASTAPI_AVAILABLE = True
except Exception as e:
    FASTAPI_IMPORT_ERROR = str(e)
    import traceback
    traceback.print_exc()


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
                # Convert BaseHTTPRequestHandler to WSGI environ for Mangum
                environ = self._to_environ()
                
                # Use Mangum to handle the request
                response = mangum_handler(environ)
                
                # Send response back to client
                self.send_response(response.status_code)
                for key, value in response.headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(response.data)
                return
                
            except Exception as e:
                # Log error and send error response
                import traceback
                traceback.print_exc()
                self._send_json_response(500, {
                    'success': False,
                    'data': None,
                    'error': f'Mangum error: {str(e)}'
                })
        
        # Health endpoint with error visibility
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
        
        # All other endpoints return 404 when FastAPI not available
        self._send_json_response(404, {
            'success': False,
            'data': None,
            'error': f'Endpoint not found: {method} {path}'
        })

    def _to_environ(self):
        """Convert BaseHTTPRequestHandler to WSGI environ dict for Mangum."""
        return {
            'REQUEST_METHOD': self.command,
            'SCRIPT_NAME': '',
            'PATH_INFO': self.path,
            'QUERY_STRING': '',
            'CONTENT_TYPE': self.headers.get('Content-Type', ''),
            'CONTENT_LENGTH': self.headers.get('Content-Length', '0'),
            'SERVER_NAME': 'vercel.app',
            'SERVER_PORT': '443',
            'HTTP_HOST': self.headers.get('Host', 'vercel.app'),
            'HTTP_COOKIE': self.headers.get('Cookie', ''),
            'HTTP_USER_AGENT': self.headers.get('User-Agent', ''),
            'HTTP_ACCEPT': self.headers.get('Accept', ''),
            'wsgi.input': self._get_body(),
            'wsgi.errors': sys.stderr,
            'wsgi.version': (1, 0),
            'wsgi.multithread': False,
            'wsgi.multiprocess': False,
            'wsgi.run_once': True,
            'wsgi.url_scheme': 'https',
        }

    def _get_body(self):
        """Get request body for WSGI environ."""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length > 0:
                return self.rfile.read(content_length)
            return b''
        except (ValueError, AttributeError):
            return b''

    def _send_json_response(self, status_code, data):
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
