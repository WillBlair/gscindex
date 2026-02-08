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

from app import create_app

# Create the Dash app instance
dash_app = create_app()

# Export the Flask WSGI app as 'app' for Vercel
# Vercel's Python runtime will automatically detect and use this WSGI application
app = dash_app.server
