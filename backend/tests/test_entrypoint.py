import subprocess
import sys
from pathlib import Path


def test_backend_entrypoint_imports_from_repository_root():
    repository_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from backend.main import app; print(app.title)",
        ],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "AI Email Assistant API"
