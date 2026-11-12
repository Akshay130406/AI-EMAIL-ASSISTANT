import sys
from pathlib import Path

# Keep backend imports ahead of the legacy root-level app.py when launched from
# the repository root as `uvicorn backend.main:app`.
backend_directory = str(Path(__file__).resolve().parent)
if backend_directory not in sys.path:
    sys.path.insert(0, backend_directory)

from app.main import app

__all__ = ["app"]
