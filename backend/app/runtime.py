from __future__ import annotations

import hashlib
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_APP_PORT = 8000


def app_port() -> int:
    raw_value = os.getenv("ISC_EMAIL_GENERATOR_PORT", str(DEFAULT_APP_PORT)).strip()
    try:
        port = int(raw_value)
    except ValueError as exc:
        raise ValueError("ISC_EMAIL_GENERATOR_PORT debe ser un número entero entre 1 y 65535.") from exc
    if not 1 <= port <= 65535:
        raise ValueError("ISC_EMAIL_GENERATOR_PORT debe estar entre 1 y 65535.")
    return port


def runtime_signature() -> str:
    """Identify the backend code and compiled frontend loaded by a server process."""
    digest = hashlib.sha256()
    candidates = [
        *sorted((ROOT / "backend" / "app").rglob("*.py")),
        *sorted((ROOT / "frontend" / "dist").rglob("*")),
    ]
    for path in candidates:
        if not path.is_file():
            continue
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


RUNTIME_SIGNATURE = runtime_signature()
