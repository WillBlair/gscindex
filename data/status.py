import os
from pathlib import Path

# Use the same cache directory as data/cache.py
_CACHE_DIR = Path(os.path.dirname(__file__)) / ".cache"
_STATUS_FILE = _CACHE_DIR / "loading_status.txt"

def set_status(message: str):
    """Write the current loading status to a file."""
    try:
        if not _CACHE_DIR.exists():
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            
        with open(_STATUS_FILE, "w") as f:
            f.write(message)
    except Exception:
        pass  # Fail silently to avoid crashing the app

def get_status() -> str:
    """Read the current loading status from the file."""
    try:
        if not _STATUS_FILE.exists():
            return "Initializing..."
            
        with open(_STATUS_FILE, "r") as f:
            return f.read().strip()
    except Exception:
        return "Initializing..."
