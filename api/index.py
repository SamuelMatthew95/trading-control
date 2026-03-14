"""Vercel Python serverless function handler."""

import json
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, '/var/task')

FASTAPI_AVAILABLE = False
app = None

# Temporarily disable import to test if it's causing the handler conflict
# try:
#     from api.main import app
#     FASTAPI_AVAILABLE = True
# except Exception:
#     pass


class handler(BaseHTTPRequestHandler):
    
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()
        
        response_data = {
            'success': True,
            'data': {
                'status': 'healthy',
                'message': 'Trading Control API is running',
                'fastapi_available': FASTAPI_AVAILABLE,
                'debug': 'import_disabled'
            },
            'error': None
        }
        self.wfile.write(json.dumps(response_data).encode())
    
    def do_POST(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()
        
        response_data = {
            'success': True,
            'data': {'message': 'POST endpoint working'},
            'error': None
        }
        self.wfile.write(json.dumps(response_data).encode())
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()
        
        response_data = {
            'success': True,
            'data': {'message': 'CORS preflight successful'},
            'error': None
        }
        self.wfile.write(json.dumps(response_data).encode())
