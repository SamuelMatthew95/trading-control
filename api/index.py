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
            print(f"DEBUG: Attempting WSGI delegation for {method} {path}")
            try:
                # Convert BaseHTTPRequestHandler to WSGI environ
                environ = self._to_environ()
                print(f"DEBUG: WSGI environ created: {list(environ.keys())}")
                
                # Use WSGI handler to process the request
                stdout = io.BytesIO()
                handler = SimpleHandler(self.rfile, stdout, sys.stderr, environ)
                print(f"DEBUG: About to run WSGI handler")
                handler.run(wsgi_app)
                print(f"DEBUG: WSGI handler completed")
                
                # Extract response from WSGI output
                stdout.seek(0)
                response_data = stdout.read()
                print(f"DEBUG: WSGI response data length: {len(response_data)}")
                
                # Parse response headers and body
                if response_data:
                    header_end = response_data.find(b'\r\n\r\n')
                    if header_end != -1:
                        headers_data = response_data[:header_end]
                        body_data = response_data[header_end + 4:]
                        
                        # Parse headers
                        headers = headers_data.decode('utf-8').split('\r\n')
                        status_line = headers[0] if headers else '200 OK'
                        
                        print(f"DEBUG: Parsed status line: {status_line}")
                        
                        # Send response
                        self.send_response(int(status_line.split()[0]), ' '.join(status_line.split()[1:]))
                        
                        # Send headers
                        for header_line in headers[1:]:
                            if ':' in header_line:
                                key, value = header_line.split(':', 1)
                                self.send_header(key.strip(), value.strip())
                        
                        self.end_headers()
                        
                        # Send body
                        if body_data:
                            self.wfile.write(body_data)
                        
                        print(f"DEBUG: Response sent successfully")
                        return
                
                # Fallback if parsing failed
                print(f"DEBUG: Failed to parse WSGI response")
                self._send_json_response(500, {
                    'success': False,
                    'data': None,
                    'error': 'Failed to parse WSGI response'
                })
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
            'SERVER_NAME': self.server.server_name if hasattr(self.server, 'server_name') else 'vercel.app',
            'SERVER_PORT': str(self.server.server_port) if hasattr(self.server, 'server_port') else '443',
            'SERVER_PROTOCOL': self.request_version,  # e.g. 'HTTP/1.1'
            'REMOTE_ADDR': self.client_address[0] if hasattr(self, 'client_address') else '127.0.0.1',
            'HTTP_HOST': self.headers.get('Host', 'vercel.app'),
            'HTTP_COOKIE': self.headers.get('Cookie', ''),
            'HTTP_USER_AGENT': self.headers.get('User-Agent', ''),
            'HTTP_ACCEPT': self.headers.get('Accept', ''),
            'wsgi.input': io.BytesIO(self._get_body()),  # must be a file-like object, not raw bytes
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
