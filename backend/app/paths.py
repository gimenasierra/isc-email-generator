from __future__ import annotations

import os
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = APP_ROOT / "backend"
STATE_DIR_ENV = "ISC_EMAIL_GENERATOR_STATE_DIR"


def configured_state_dir() -> Path | None:
    """Return the optional writable state root selected by a launcher."""
    raw_value = os.getenv(STATE_DIR_ENV, "").strip()
    return Path(raw_value).expanduser() if raw_value else None


def state_path(*parts: str, development_default: Path) -> Path:
    state_dir = configured_state_dir()
    return state_dir.joinpath(*parts) if state_dir is not None else development_default
