import os
import sys

# In Vercel, /var/task is the root, so we need to add current directory to path
# to import main.py directly from the same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import app


class Handler:
    def __init__(self):
        self.app = app

    def __call__(self, environ, start_response):
        return self.app(environ, start_response)


# Vercel needs this
handler_instance = Handler()
