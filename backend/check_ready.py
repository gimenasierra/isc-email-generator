from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

from app.runtime import RUNTIME_SIGNATURE


def main() -> int:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=0.8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return 1
    return 0 if response.status == 200 and payload.get("runtime_signature") == RUNTIME_SIGNATURE else 1


if __name__ == "__main__":
    raise SystemExit(main())
