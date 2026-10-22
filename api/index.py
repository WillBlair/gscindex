"""
Vercel serverless function wrapper for Dash application.
This file is the entry point for Vercel deployments.

Vercel's Python runtime supports WSGI applications. Since Dash uses Flask
under the hood, we can export the Flask app directly as 'app'.
"""

from __future__ import annotations

import os
import sys

# Add parent directory to path so imports work
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

# Serverless functions are frozen between requests, so the 5-minute
# background refresh loop can't run here; disable it before importing app.
os.environ.setdefault("GSC_DISABLE_BACKGROUND", "1")

# Reuse the module-level app (importing app already builds it once).
from app import app as dash_app

# Export the Flask WSGI app as 'app' for Vercel
# Vercel's Python runtime will automatically detect and use this WSGI application
app = dash_app.server
