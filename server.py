import os
import sys

# Add api directory to path
sys.path.insert(0, './api')

from main import app

# Vercel handler
handler = app
