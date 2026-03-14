"""Vercel Python serverless function handler."""

import json
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from wsgiref.handlers import SimpleHandler
import io

sys.path.insert(0, '/var/task')

FASTAPI_AVAILABLE = False
FASTAPI_IMPORT_ERROR = None
wsgi_app = None

try:
    from api.main import app
    from a2wsgi import ASGIMiddleware
    wsgi_app = ASGIMiddleware(app)
    FASTAPI_AVAILABLE = True
except Exception as e:
    FASTAPI_AVAILABLE = False
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
        # Get the full path including leading slash
        path = self.path
        
        # Debug logging
        print(f"DEBUG: Received request: {method} {path}")
        print(f"DEBUG: FastAPI available: {FASTAPI_AVAILABLE}")
        print(f"DEBUG: WSGI app available: {wsgi_app is not None}")
        
        # If FastAPI is available, delegate to WSGI app
        if FASTAPI_AVAILABLE and wsgi_app:
            try:
                # Convert BaseHTTPRequestHandler to WSGI environ
                environ = self._to_environ()
                
                # Use WSGI handler to process the request
                stdout = io.BytesIO()
                handler = SimpleHandler(self.rfile, stdout, sys.stderr, environ)
                handler.run(wsgi_app)
                return
                
            except Exception as e:
                # Log error and send error response
                import traceback
                traceback.print_exc()
                print(f"DEBUG: WSGI handler error: {str(e)}")
                self._send_json_response(500, {
                    'success': False,
                    'data': None,
                    'error': f'WSGI error: {str(e)}'
                })
                return
        
        # Health endpoint with error visibility
        if path in ('/api/health', '/health'):
            print(f"DEBUG: Serving health endpoint, FastAPI available: {FASTAPI_AVAILABLE}")
            self._send_json_response(200, {
                'success': True,
                'data': {
                    'status': 'healthy', 
                    'fastapi_available': FASTAPI_AVAILABLE,
                    'import_error': FASTAPI_IMPORT_ERROR
                },
                'error': None
            })
            return
        
        # Test endpoint to verify routing
        if path == '/api/test':
            print(f"DEBUG: Test endpoint reached, FastAPI available: {FASTAPI_AVAILABLE}")
            self._send_json_response(200, {
                'success': True,
                'data': {
                    'message': 'Test endpoint working',
                    'fastapi_available': FASTAPI_AVAILABLE,
                    'import_error': FASTAPI_IMPORT_ERROR
                },
                'error': None
            })
            return
        
        # All other endpoints return 404 when FastAPI not available
        self._send_json_response(404, {
            'success': False,
            'data': None,
            'error': f'Endpoint not found: {method} {path}'
        })

    def _to_environ(self):
        """Convert BaseHTTPRequestHandler to WSGI environ dict."""
        # Parse path to separate path and query string
        parsed_path = urlparse(self.path)
        path_info = parsed_path.path
        query_string = parsed_path.query
        
        return {
            'REQUEST_METHOD': self.command,
            'SCRIPT_NAME': '',
            'PATH_INFO': path_info,
            'QUERY_STRING': query_string,
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
