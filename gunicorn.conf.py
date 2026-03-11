"""
Gunicorn configuration for Render.com deployment.
Binds to 0.0.0.0:PORT so Render can detect the open port.

Uses gthread (threaded) workers so the health endpoint stays responsive
even while serve_layout() is doing disk I/O or the background data
thread is initializing.  A single sync worker would block ALL requests
whenever any one request is slow.
"""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '10000')}"
workers = 1
threads = 8
worker_class = "gthread"
timeout = 120
