from __future__ import annotations

import base64
import os
import re
import threading
from pathlib import Path

from .paths import BACKEND_DIR, state_path
from . import server_runtime


ENV_PATH = state_path(".env", development_default=BACKEND_DIR / ".env")
CONNECTION_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_write_lock = threading.Lock()


class ISCSecretError(ValueError):
    pass


def _keys(connection_id: str) -> tuple[str, str]:
    if not CONNECTION_ID_RE.fullmatch(connection_id):
        raise ISCSecretError("El identificador interno de la conexión no es válido.")
    suffix = connection_id.upper()
    return f"ISC_CONNECTION_{suffix}_CLIENT_ID_B64", f"ISC_CONNECTION_{suffix}_CLIENT_SECRET_B64"


def _encode(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _decode(value: str) -> str:
    try:
        return base64.b64decode(value.strip().encode("ascii"), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ISCSecretError("Las credenciales ISC guardadas no tienen un formato válido.") from exc


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


def get_credentials(connection_id: str, path: Path | None = None) -> tuple[str, str]:
    if server_runtime.enabled() and path is None:
        _keys(connection_id)
        return (
            server_runtime.get_secret("isc", f"{connection_id}:client_id"),
            server_runtime.get_secret("isc", f"{connection_id}:client_secret"),
        )
    client_key, secret_key = _keys(connection_id)
    values = _file_values(path or ENV_PATH)
    encoded_client = os.environ.get(client_key, values.get(client_key, ""))
    encoded_secret = os.environ.get(secret_key, values.get(secret_key, ""))
    return (_decode(encoded_client) if encoded_client else "", _decode(encoded_secret) if encoded_secret else "")


def credential_status(connection_id: str, path: Path | None = None) -> tuple[bool, bool]:
    client_id, client_secret = get_credentials(connection_id, path)
    return bool(client_id), bool(client_secret)


def set_credentials(connection_id: str, client_id: str, client_secret: str, path: Path | None = None) -> None:
    with _write_lock:
        _set_credentials_unlocked(connection_id, client_id, client_secret, path)


def _set_credentials_unlocked(connection_id: str, client_id: str, client_secret: str, path: Path | None = None) -> None:
    if server_runtime.enabled() and path is None:
        _keys(connection_id)
        existing_client, existing_secret = get_credentials(connection_id)
        final_client = client_id.strip() or existing_client
        final_secret = client_secret or existing_secret
        if not final_client or not final_secret:
            raise ISCSecretError("Ingresá Client ID y Client Secret para guardar la conexión.")
        server_runtime.set_secret("isc", f"{connection_id}:client_id", final_client)
        server_runtime.set_secret("isc", f"{connection_id}:client_secret", final_secret)
        return
    target = path or ENV_PATH
    client_key, secret_key = _keys(connection_id)
    existing_client, existing_secret = get_credentials(connection_id, target)
    final_client = client_id.strip() or existing_client
    final_secret = client_secret or existing_secret
    if not final_client or not final_secret:
        raise ISCSecretError("Ingresá Client ID y Client Secret para guardar la conexión.")

    replacements = {client_key: _encode(final_client), secret_key: _encode(final_secret)}
    lines = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
    output: list[str] = []
    replaced: set[str] = set()
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in replacements:
            output.append(f"{key}={replacements[key]}")
            replaced.add(key)
        else:
            output.append(line)
    for key, value in replacements.items():
        if key not in replaced:
            output.append(f"{key}={value}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    temporary.replace(target)
    os.environ[client_key] = replacements[client_key]
    os.environ[secret_key] = replacements[secret_key]


def delete_credentials(connection_id: str, path: Path | None = None) -> None:
    """Remove only the two persisted secrets that belong to one ISC connection."""
    with _write_lock:
        _delete_credentials_unlocked(connection_id, path)


def _delete_credentials_unlocked(connection_id: str, path: Path | None = None) -> None:
    if server_runtime.enabled() and path is None:
        _keys(connection_id)
        server_runtime.delete_secret("isc", f"{connection_id}:client_id")
        server_runtime.delete_secret("isc", f"{connection_id}:client_secret")
        return
    target = path or ENV_PATH
    client_key, secret_key = _keys(connection_id)
    secret_keys = {client_key, secret_key}
    lines = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
    output = [
        line
        for line in lines
        if (line.split("=", 1)[0].strip() if "=" in line else "") not in secret_keys
    ]
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text("\n".join(output).rstrip() + ("\n" if output else ""), encoding="utf-8")
    temporary.replace(target)
    os.environ.pop(client_key, None)
    os.environ.pop(secret_key, None)
