from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


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
