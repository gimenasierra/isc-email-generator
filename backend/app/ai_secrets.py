from __future__ import annotations

import base64
import os
import threading
from pathlib import Path


ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
PROVIDER_ENV_KEYS = {
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openai_compatible": "LOCAL_OPENAI_API_KEY",
}
_write_lock = threading.Lock()


class AISecretError(ValueError):
    pass


def _keys(provider_id: str) -> tuple[str, str]:
    try:
        raw_key = PROVIDER_ENV_KEYS[provider_id]
    except KeyError as exc:
        raise AISecretError("El proveedor no admite una API key persistente.") from exc
    return raw_key, f"{raw_key}_B64"


def _file_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _decode(value: str) -> str:
    try:
        return base64.b64decode(value.strip().encode("ascii"), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise AISecretError("La API key guardada no tiene un formato válido.") from exc


def get_persistent_key(provider_id: str, path: Path | None = None) -> str:
    raw_key, encoded_key = _keys(provider_id)
    target = path or ENV_PATH
    values = _file_values(target)
    raw_value = os.environ.get(raw_key, values.get(raw_key, "")).strip()
    if raw_value:
        return raw_value
    encoded_value = os.environ.get(encoded_key, values.get(encoded_key, "")).strip()
    return _decode(encoded_value) if encoded_value else ""


def set_persistent_key(provider_id: str, api_key: str, path: Path | None = None) -> None:
    value = api_key.strip()
    if not value:
        return
    _, encoded_key = _keys(provider_id)
    encoded_value = base64.b64encode(value.encode("utf-8")).decode("ascii")
    target = path or ENV_PATH
    with _write_lock:
        lines = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
        output: list[str] = []
        replaced = False
        for line in lines:
            key = line.split("=", 1)[0].strip() if "=" in line else ""
            if key == encoded_key:
                output.append(f"{encoded_key}={encoded_value}")
                replaced = True
            else:
                output.append(line)
        if not replaced:
            output.append(f"{encoded_key}={encoded_value}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
        temporary.replace(target)
        os.environ[encoded_key] = encoded_value
