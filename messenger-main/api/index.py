import os
import sys

# Add the parent directory to the path so we can import from the main app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the Flask app from the main app.py
from app import app

# Vercel expects the app to be named 'app' for WSGI
application = app
